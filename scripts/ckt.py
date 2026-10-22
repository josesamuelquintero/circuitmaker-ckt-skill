#!/usr/bin/env python3
"""ckt.py - Lector/generador de archivos CircuitMaker 2000 (.CKT texto, v5.6).

Uso como libreria:
    from ckt import Circuit
    c = Circuit()
    v = c.add('PULSER', 80, 60);      c.net(v['Q1'], 'CLK')
    u = c.add('74LS93', 300, 150);    c.net(u['CP0'], 'CLK'); c.wire(u['Q0'], u['CP1'])
    for q in 'Q0 Q1 Q2 Q3'.split(): c.net(u[q], 'B' + q[1])
    c.net(u['MR1'], 'GND'); c.net(u['MR2'], 'GND')
    c.text(500, 40, 'Mi circuito')
    c.save('salida.CKT')

CLI:
    python ckt.py parts                  lista de componentes disponibles
    python ckt.py info  archivo.CKT      componentes, redes y verificacion
    python ckt.py render archivo.CKT out.png   vista previa aproximada
    python ckt.py learn a.CKT [b.CKT..]  agrega a ckt_parts.json los tipos nuevos (pines cableados; vota entre archivos)
    python ckt.py export nuevas.txt     partes aprendidas listas para incorporarlas al skill
    python ckt.py models CARPETA [archivo.CKT | texto]   modelos SPICE de la carpeta MODELS de CircuitMaker
    python ckt.py roundtrip archivo.CKT  verifica lectura/escritura identica
"""
import json, os, re, sys, random, datetime

NL = b'\r\n'

# ----------------------------------------------------------------- lectura
def _tok(x):
    """entero si lo es; si no (0.1, 1e+06, 5.89e-315) se conserva el texto tal cual para reescribirlo identico."""
    return int(x) if re.fullmatch(r'-?\d+', x) else x

class _R:
    def __init__(s, b): s.b = b; s.p = 0
    def line(s):
        i = s.b.index(NL, s.p); l = s.b[s.p:i]; s.p = i + 2; return l.decode('latin-1')
    def ints(s): return [_tok(x) for x in s.line().split()]
    def str_(s):
        m = re.match(rb'(\d+)', s.b[s.p:s.p + 12]); n = int(m.group(1)); q = s.p + len(m.group(1))
        if n == 0:
            s.p = q + 2; return ''
        q += 1; out = bytearray()
        while len(out) < n:
            if s.b[q:q + 3] == b'\r\r\n': out += NL; q += 3          # salto dentro de cadena
            elif s.b[q:q + 3] == b'\xef\xbf\xbd': out += b'?'; q += 3  # UTF-8 roto (tolerancia)
            else: out.append(s.b[q]); q += 1
        s.p = q + 2; return out.decode('cp1252', 'replace')

EXTRA_LINES = {'Data Seq~': 1}   # lineas extra conocidas tras el bloque del componente

def parse(data):
    """bytes|ruta -> dict(hdr, comps, wires, texts, tail)"""
    if isinstance(data, str): data = open(data, 'rb').read()
    r = _R(data); hdr = [r.line() for _ in range(3)]  # 'CircuitMaker Text', version, 'Probes: N'
    if hdr[2].startswith('Probes:'):
        hdr += [r.line() for _ in range(3 * int(hdr[2].split(':')[1]) + 26)]  # N sondas de 3 lineas + 26 fijas
    else:  # versiones 4-5.5: sin sondas; la cabecera acaba 6 lineas despues de la linea 'banderas 0'
        while not (len(hdr) > 9 and re.fullmatch(r'\d{6,} \d+', hdr[-1])): hdr.append(r.line())
        hdr += [r.line() for _ in range(6)]
    comps = []
    for _ in range(int(r.line())):
        c = {'name': r.str_(), 'g': r.ints()}; arr = []
        while len(arr) < c['g'][4] + 1: arr += r.ints()
        c['arr'] = arr; c['A'] = r.line(); xs = []
        n_ = int(c['A']) if c['A'].isdigit() else 0  # texto ('12 NPN Trans:C~') o conteo de un bloque numerico
        while n_:  # bloques extra de numeros (p. ej. Signal Gen~: 20 parametros), terminados en 0
            xa = []
            while len(xa) < n_: xa += r.ints()
            xs.append(xa); n_ = int(r.line())
        if xs: c['xarr'] = xs
        c['flags'] = r.ints()
        c['value'] = r.str_(); c['vrect'] = r.ints() if c['value'] else None
        c['des'] = r.str_(); c['drect'] = r.ints() if c['des'] else None  # sin designador no hay rectangulo
        c['s'] = [r.str_()]
        if c['s'][0]: c['srect'] = r.ints()  # tercer rotulo opcional (K1 de un rele, VDD de +V) con su rectangulo
        c['s'] += [r.str_() for _ in range(5)]
        n = int(r.line()); r.line(); pm = []
        while len(pm) < n + 1: pm += r.ints()
        c['pm'] = pm; c['L8'] = r.ints(); c['prefix'] = r.str_(); c['id'] = r.ints()
        c['dbl'] = r.line() if int(r.line()) else None; c['end'] = r.line()
        ex = []  # lineas propias tras el bloque (p. ej. el patron de datos de Data Seq~)
        for _ in range(EXTRA_LINES.get(c['name'], 0)): ex.append(r.line())
        while r.p < len(r.b) and not re.match(rb'-?\d', r.b[r.p:r.p + 2]): ex.append(r.line())
        if ex: c['extra'] = ex
        comps.append(c)
    wires = []
    for _ in range(int(r.line())):
        h = r.ints(); wires.append([h, [r.ints() for _ in range(h[11])]])
    texts = []
    for _ in range(int(r.line())):
        texts.append({'font': r.line(), 'face': r.str_(), 'col': r.ints(), 'r1': r.ints(),
                      'r2': r.ints(), 'text': r.str_()})
    return {'hdr': hdr, 'comps': comps, 'wires': wires, 'texts': texts, 'tail': r.b[r.p:]}

# --------------------------------------------------------------- escritura
def _s(t):
    b = t.replace('\r\n', '\n').replace('\n', '\r\n').encode('cp1252', 'replace')
    return b'0' if not b else str(len(b)).encode() + b' ' + b.replace(NL, b'\r\r\n')
def _i(v): return ' '.join(str(x) for x in v).encode()
def _wrap(v): return [_i(v[k:k + 10]) for k in range(0, len(v), 10)]

def serialize(d):
    L = [h.encode('latin-1') for h in d['hdr']] + [str(len(d['comps'])).encode()]
    for c in d['comps']:
        L += [_s(c['name']), _i(c['g'])] + _wrap(c['arr'])
        L.append(c['A'].encode())
        xs = c.get('xarr') or []
        for k, xa in enumerate(xs):
            L += _wrap(xa); L.append(str(len(xs[k + 1]) if k + 1 < len(xs) else 0).encode())
        L += [_i(c['flags']), _s(c['value'])]
        if c['value']: L.append(_i(c['vrect']))
        L.append(_s(c['des']))
        if c['des']: L.append(_i(c['drect']))
        L.append(_s(c['s'][0]))
        if c['s'][0]: L.append(_i(c['srect']))
        L += [_s(x) for x in c['s'][1:]]
        L += [str(len(c['pm']) - 1).encode(), b''] + _wrap(c['pm'])
        L += [_i(c['L8']), _s(c['prefix']), _i(c['id'])]
        L += [b'2', c['dbl'].encode()] if c['dbl'] is not None else [b'0']
        L.append(c['end'].encode())
        L += [x.encode('latin-1') for x in c.get('extra', [])]
    L.append(str(len(d['wires'])).encode())
    for h, pts in d['wires']: L += [_i(h)] + [_i(p) for p in pts]
    L.append(str(len(d['texts'])).encode())
    for t in d['texts']:
        L += [t['font'].encode(), _s(t['face']), _i(t['col']), _i(t['r1']), _i(t['r2']), _s(t['text'])]
    return NL.join(L) + NL + d['tail']

# ---------------------------------------------------- plantillas / partes
HEADER = ['CircuitMaker Text', '5.6', 'Probes: 0', '41 35 62 4 97 108 86 46 82 16 73 113 113 59 105 107 ',
          '0 5 0 1e+09 0.001 2', '33', '13 10 13 12 18 10 20 20 12 20 ', '10 13 13 10 20 13 46 20 14 20 ',
          '18 17 14 16 20 20 20 20 10 13 ', '20 18 11 ', '0 0 10 120 10', '176 80 1705 998',
          '7 5.000 V', '7 5.000 V', '3 GND', '0 0', '24 100 0 1 0', '20 Package,Description,',
          '42 C:\\Program Files\\CircuitMaker 2000\\BOM.DAT', '0 7', '2 4 0.340757 0.500000',
          '344 176 457 273', '9437202 0', '0', '6 Title:', '5 Name:', '0', '0', '0']
TAIL = ('0\r\n2049 0 0\r\n0\r\n0\r\n0\r\n0 0 0\r\n0\r\n0 0 0\r\n0 0 0 0\r\n0 0 0 0\r\n0\r\n0\r\n0 0 0\r\n'
        '0 0 0\r\n0\r\n0\r\n0 0 0 0\r\n0\r\n0 0 0 0 0\r\n0 0 0 0\r\n0\r\n0 0 0\r\n0\r\n0 0 0\r\n'
        '0 0 0 0 0 0 0 0 0\r\n0 0 0 0 0 0\r\n0 0 0 0\r\n0 0 0 0\r\n0 0\r\n0 0\r\n0 0\r\n0 0\r\n0 0\r\n'
        + ('0 0 0 0 0 0\r\n0 0\r\n0 0 0\r\n0\r\n0 0 0 0 0 0\r\n0 0 0 0\r\n0 0 0 0\r\n0 0\r\n0 0\r\n0 0\r\n'
           '0 0\r\n0 0\r\n') * 7 + '0 0 0 0 0 0\r\n0 0\r\n0 0 0\r\n0\r\n').encode()

BUILTIN = json.loads(r'''{"IN":{"tpl":{"name":"Input~","g":[177,0,0,0,17,19],"arr":[0,22,0,0,0,0,0,0,0,0,66,55,32,32,32,32,32,32],"A":"0","flags":[0,0,53344,0],"value":"","vrect":null,"des":"T33","drect":[-11,-26,10,-18],"s":["","","","","",""],"pm":[0,1,1,0],"L8":[0,0,0,0,1,0,0,0],"prefix":"T","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"1":[1,34,0]},"sections":1,"desc":"Etiqueta de red (Input~), pin a la derecha","npins":1},"OUT":{"tpl":{"name":"Output~","g":[178,0,0,0,17,19],"arr":[0,20,0,0,0,0,0,0,0,0,82,68,32,32,32,32,32,32],"A":"0","flags":[0,0,53344,0],"value":"","vrect":null,"des":"T35","drect":[-17,-26,4,-18],"s":["","","","","",""],"pm":[0,1,1,0],"L8":[0,0,0,0,1,0,0,0],"prefix":"T","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"1":[1,-40,0]},"sections":1,"desc":"Etiqueta de red (Output~), pin a la izquierda","npins":1},"GND":{"tpl":{"name":"Ground~","g":[168,0,0,0,1,3],"arr":[0,2],"A":"0","flags":[0,0,53344,0],"value":"","vrect":null,"des":"GND1","drect":[-14,-26,14,-18],"s":["","GND;","","","",""],"pm":[0,1,1,0],"L8":[0,0,0,0,1,0,0,0],"prefix":"GND","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"1":[1,0,-6]},"sections":1,"desc":"Tierra (net 2)","npins":1},"PULSER":{"tpl":{"name":"Pulser~","g":[4,0,0,0,10,12],"arr":[0,28,29,19,30,0,0,5,5,3,8],"A":"0","flags":[0,0,4640,0],"value":"","vrect":null,"des":"V1","drect":[-7,-28,7,-20],"s":["","","","","","SIP2"],"pm":[0,1,2,3,4,1,2,3,4,0],"L8":[0,0,0,512,1,0,0,0],"prefix":"V","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"Q1":[3,24,-9]},"sections":1,"desc":"Generador de pulsos (reloj). Salida Q1","npins":4},"HEX":{"tpl":{"name":"Hex Display~","g":[7,0,0,0,16,19],"arr":[10,3,2,2,2,0,0,0,0,0,0,1,1,1,1,1,1],"A":"0","flags":[0,0,53856,0],"value":"1MEG","vrect":[-15,-42,13,-34],"des":"DISP7","drect":[-18,-38,17,-30],"s":["","","%DA %1 0 %V\r\n%DB %2 0 %V\r\n%DC %3 0 %V\r\n%DD %4 0 %V","","",""],"pm":[0,1,2,3,4,1,2,3,4,0],"L8":[82,0,0,0,1,0,0,0],"prefix":"DISP","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"1":[1,9,24],"2":[2,3,24],"3":[3,-3,24],"4":[4,-9,24]},"sections":1,"desc":"Display 7 seg. hexadecimal con decodificador; pin 1 = LSB, 4 = MSB","npins":4},"ASCII":{"tpl":{"name":"Ascii Display~","g":[172,0,0,0,42,44],"arr":[0,12,13,14,18,17,15,16,19,0,16,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224,8224],"A":"0","flags":[0,0,21088,0],"value":"1MEG","vrect":[-15,-42,13,-34],"des":"DISP1","drect":[-3,-48,32,-40],"s":["","","%DA %1 0 %V\r\n%DB %2 0 %V\r\n%DC %3 0 %V\r\n%DD %4 0 %V\r\n%DE %5 0 %V\r\n%DF %6 0 %V\r\n%DG %7 0 %V\r\n%DH %8 0 %V","","",""],"pm":[0,1,2,3,4,5,6,7,8,1,2,3,4,5,6,7,8,0],"L8":[82,0,0,0,1,0,0,0],"prefix":"DISP","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"7":[1,-66,-31],"6":[2,-66,-22],"5":[3,-66,-13],"4":[4,-66,-4],"3":[5,-66,5],"2":[6,-66,14],"1":[7,-66,23],"CP":[8,-72,31]},"sections":1,"desc":"Pantalla ASCII: entradas 1..7 (1 = bit0 LSB) y CP","npins":8},"74LS93":{"tpl":{"name":"74LS93","g":[109,0,0,0,8,17],"arr":[0,22,22,19,16,18,17,15,16],"A":"0","flags":[0,0,4832,0],"value":"74LS93","vrect":[-21,-35,21,-27],"des":"U1","drect":[-7,-36,7,-28],"s":["","DVCC=5;DGND=10;","%D [%5bi %10bi %1i %2i %3i %4i]\r\n+ [%5bo %1o %2o %3o %4o %5o %6o %7o %8o] %M","","type:digital","DIP14"],"pm":[0,2,3,14,1,11,8,9,12,2,3,14,1,11,8,9,12,0],"L8":[65,0,0,0,1,0,0,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"MR1":[1,-32,-9],"MR2":[2,-32,0],"CP0":[3,-38,9],"CP1":[4,-38,18],"Q3":[5,32,-9],"Q2":[6,32,0],"Q1":[7,32,9],"Q0":[8,32,18]},"sections":1,"desc":"Contador binario 4 bits (FF /2 + /8)","npins":8},"4071":{"tpl":{"name":"4071~","g":[219,0,0,0,3,22],"arr":[0,22,23,21],"A":"0","flags":[0,0,608,0],"value":"4071","vrect":[-7,-24,21,-16],"des":"U7A","drect":[-3,-25,18,-17],"s":["","DVCC=14;DGND=7;","%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M","","type:digital","DIP14"],"pm":[0,1,2,3,1,2,3,5,6,4,8,9,10,12,13,11,0,0,0,0,0,1,0],"L8":[65,0,0,0,4,1,2,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"A":[1,-13,-9],"B":[2,-13,9],"Y":[3,33,0]},"sections":4,"desc":"OR de 2 entradas (4 por chip)","npins":3},"4081":{"tpl":{"name":"4081~","g":[219,0,0,0,3,22],"arr":[0,10,11,23],"A":"0","flags":[0,0,608,0],"value":"4081","vrect":[-7,-24,21,-16],"des":"U6A","drect":[-12,-25,9,-17],"s":["","DVDD=14;DGND=7;","%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M","","type:digital","DIP14"],"pm":[0,1,2,3,1,2,3,5,6,4,8,9,10,12,13,11,0,0,0,0,0,1,0],"L8":[65,0,0,0,4,1,1,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"A":[1,-24,-9],"B":[2,-24,9],"Y":[3,21,0]},"sections":4,"desc":"AND de 2 entradas (4 por chip)","npins":3},"4040":{"tpl":{"name":"4040","g":[219,0,0,0,20,29],"arr":[0,39,2,26,25,27,23,24,22,33,34,32,36,35,37,0,0,0,0,0,0],"A":"0","flags":[0,0,4832,0],"value":"4040","vrect":[-14,-60,14,-52],"des":"U13","drect":[-11,-61,10,-53],"s":["","DVDD=16;DGND=8;","%D [%16bi %8bi %1i %2i]\r\n+ [%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M","","type:digital","DIP16"],"pm":[0,10,11,9,7,6,5,3,2,4,13,12,14,15,1,10,11,9,7,6,5,3,2,4,13,12,14,15,1,0],"L8":[65,0,0,0,1,0,0,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"CP":[1,-38,27],"MR":[2,-32,45],"Q0":[3,32,63],"Q1":[4,32,54],"Q2":[5,32,45],"Q3":[6,32,36],"Q4":[7,32,27],"Q5":[8,32,18],"Q6":[9,32,9],"Q7":[10,32,0],"Q8":[11,32,-9],"Q9":[12,32,-18],"Q10":[13,32,-27],"Q11":[14,32,-36]},"sections":1,"desc":"Contador binario 12 bits (flanco de bajada en CP)","npins":14},"CD4520":{"tpl":{"name":"CD4520","g":[78,0,0,0,14,29],"arr":[0,2,37,2,2,28,38,28,31,29,30,43,44,45,38],"A":"0","flags":[0,0,4832,0],"value":"4520","vrect":[-14,-60,14,-52],"des":"U12","drect":[-11,-61,10,-53],"s":["","DVDD=16;DGND=8;","%D [%16bi %8bi %1i %2i %3i %4i %5i %6i]\r\n+ [%16bo %1i %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M","","type:digital","DIP16"],"pm":[0,1,2,7,9,10,15,6,5,4,3,14,13,12,11,1,2,7,9,10,15,6,5,4,3,14,13,12,11,0],"L8":[65,0,0,512,1,0,0,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"CP0A":[1,-32,-27],"CP1A":[2,-38,-18],"MRA":[3,-32,-9],"CP0B":[4,-32,9],"CP1B":[5,-38,18],"MRB":[6,-32,27],"Q3A":[7,32,-36],"Q2A":[8,32,-27],"Q1A":[9,32,-18],"Q0A":[10,32,-9],"Q3B":[11,32,9],"Q2B":[12,32,18],"Q1B":[13,32,27],"Q0B":[14,32,36]},"sections":1,"desc":"Doble contador binario 4 bits","npins":14},"4518":{"tpl":{"name":"4518","g":[219,0,0,0,7,32],"arr":[0,2,6,38,12,13,11,14],"A":"0","flags":[0,0,4832,0],"value":"4518","vrect":[-14,-60,14,-52],"des":"U2A","drect":[-11,-61,10,-53],"s":["","DVDD=16;DGND=8;","%D [%16bi %8bi %1i %2i %3i][%16bo %1o %2o %3o %4o %5o %6o %7o] %M","","type:digital","DIP16"],"pm":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,19,0],"L8":[65,0,0,0,2,1,5,0],"prefix":"U","id":[0,0,0],"dbl":"0 0","end":"0"},"pins":{"CP0":[1,-32,-27],"CP1":[2,-38,-18],"MR":[3,-32,0],"Q0":[4,32,0],"Q1":[5,32,-9],"Q2":[6,32,-18],"Q3":[7,32,-27]},"sections":2,"desc":"Contador BCD (2 por chip)","npins":7}}''')
# Nombres de pin deducidos del netlist SPICE de cada simbolo (General.CKT de Jose).
# Solo donde la convencion SPICE lo fija: D anodo/catodo, Q colector/base/emisor, V +/-,
# potenciometro (R entre 1-2 y 2-3 => 2 es el cursor). El resto queda P1..Pn salvo los confirmados abajo.
_AK = {1: 'A', 2: 'K'}; _PM = {1: '+', 2: '-'}; _12 = {1: '1', 2: '2'}; _CBE = {1: 'C', 2: 'B', 3: 'E'}
PIN_NAMES = {
    'V Source~': _PM, 'I Source~': _PM, 'Battery~': _PM, 'Signal Gen~': _PM, '+V': {1: 'V'},
    'Resistor~': _12, 'Resistor:A~': _12, 'SemiResistor~': _12, 'SemiResistorA~': _12,
    'Var Resistor~': {1: '1', 2: 'W', 3: '3'}, 'Var ResistorA~': {1: '1', 2: 'W', 3: '3'},
    'Capacitor~': _12, 'Polar Cap~': _PM, 'SemiCapacitor~': _12, 'Var Capacitor~': _12,
    'Inductor~': _12, 'Var Inductor~': _12, 'Coil 3T~': _12, 'Coil 5T~': _12,
    'Diode~': _AK, 'Schottky~': _AK, 'Varactor~': _AK, 'Varactor:A~': _AK, 'Zener Diode~': _AK, 'LED~': _AK,
    'NPN Trans:B~': _CBE, 'NPN Trans:C~': _CBE, 'PNP Trans:B~': _CBE, 'PNP Trans:C~': _CBE,
    # Confirmados viendo los simbolos en CircuitMaker (captura de Jose):
    'Multimeter~': {1: '+', 4: '-'},
    'FW Bridge~': {1: '-', 2: 'AC1', 3: '+', 4: 'AC2'},
    'Diode AKA~': {1: 'A1', 2: 'K', 3: 'A2'}, 'Zener AKA~': {1: 'A1', 2: 'K', 3: 'A2'},
    'Diode KAK~': {1: 'K1', 2: 'A', 3: 'K2'}, 'Diode ACK~': {1: 'A', 2: 'C', 3: 'K'},
    'Data Seq~': dict([(k, str(9 - k)) for k in range(1, 9)] + [(9, 'CP1'), (10, 'CP2')]),
}

# Pines del netlist sin terminal en el simbolo (Jose cableo todos los visibles en General.CKT)
HIDDEN_PINS = {'Multimeter~': (2, 3)}

# Modelos SPICE de la carpeta MODELS de CircuitMaker 2000 de Jose. CircuitMaker busca <prefijo><valor> en el
# archivo de la familia (D diodos, Q BJT, X subcircuitos, R, C); la ~ marca el modelo por defecto.
# familia: (archivo, prefijo, valor por defecto que existe, otros modelos comunes verificados en ese archivo)
MODELS = {
    'DIODE': ('Diode.mod', 'D', 'DIODE', '1N4148 1N914 1N4448 1N4001 1N4002 1N4004 1N4007 1N5400 1N5408 1N34'),
    'SCHOTTKY': ('SCHOTTKY.MOD', 'D', 'SKYDIODE', '11DQ03 11DQ04 11DQ06 10BQ040 30BQ040 MBR1045 1N5828'),
    'ZENER': ('ZENER.MOD', 'D', 'ZENER', '1N746 1N750 1N751 1N752 1N758 1N759 1N4728 1N4732 1N4733 1N4734 '
              '1N4735 1N4736 1N4739 1N4740 1N4742 1N4744 1N4747'),
    'VARACTOR': ('VARACTOR.MOD', 'D', 'FMMV109', 'BBY31 BBY40 FMMV105G FMMV2101 FMMV2105 FMMV2109 ZC830A ZC836A'),
    'LED': ('LED.MOD', 'D', 'LED1', 'LED0 LED2 LED3'),
    'NPN': ('NPN.MOD', 'Q', 'NPN', '2N3904 2N2222 2N2222A 2N4401 2N5551 BC547A BC547B BC547C BC548A BC548B BC548C '
            'BC337-25 2N3055 MPSA42'),
    'PNP': ('PNP.MOD', 'Q', 'PNP', '2N3906 2N2907 2N2907A 2N4403 2N5401 BC557 BC557B BC327 BC328'),
    'RESISTOR': ('RESISTOR.MOD', 'R', 'RESISTOR', ''),
    'CAP': ('CAP.MOD', 'C', 'CAP', ''),
    'AKA': ('Diodeaka.sub', 'X', 'BAV70', 'BAV74 BAV170 MMBD6100 MSD6100'),
    'KAK': ('Diodekak.sub', 'X', 'BAW56', 'BAW156 MMBD2835 MMBD2836 MSD6150'),
    'ACK': ('Diodeack.sub', 'X', 'BAV99', 'BAV199 MMBD7000'),
    'ZAKA': ('Zeneraka.sub', 'X', 'DZ23C2V7', 'DZ23C3V3 DZ23C5V1 DZ23C6V2 DZ23C10 DZ23C12 DZ23C15'),
    'BRIDGE': ('FWBRIDGE.SUB', 'X', 'BRIDGE', 'MDA2500 DF005 DF01 DF02 DF04 DF06 DF08 DF10'),
}
MODEL_FAMILY = {'DIODE': 'DIODE', 'SCHOTTKY': 'SCHOTTKY', 'ZENERDIODE': 'ZENER', 'VARACTOR': 'VARACTOR',
                'VARACTORA': 'VARACTOR', 'LED': 'LED', 'NPNTRANSB': 'NPN', 'NPNTRANSC': 'NPN', 'PNPTRANSB': 'PNP',
                'PNPTRANSC': 'PNP', 'SEMIRESISTOR': 'RESISTOR', 'SEMIRESISTORA': 'RESISTOR', 'SEMICAPACITOR': 'CAP',
                'DIODEAKA': 'AKA', 'DIODEKAK': 'KAK', 'DIODEACK': 'ACK', 'ZENERAKA': 'ZAKA', 'FWBRIDGE': 'BRIDGE'}
def known_models(fam): f = MODELS[fam]; return {f[2]} | set(f[3].split())

def auto_bbox(t, pins):
    """caja aproximada del cuerpo: entre los pines (metidos 4 hacia dentro). Si todos los pines salen por
    un mismo lado (multimetro, generador), el cuerpo queda hacia los rotulos y se incluyen."""
    xs = [v[1] for v in pins.values()]; ys = [v[2] for v in pins.values()]
    x1, y1, x2, y2 = min(xs) + 4, min(ys) + 4, max(xs) - 4, max(ys) - 4
    if x2 - x1 < 12: x1, x2 = min(x1, -6), max(x2, 6)
    if y2 - y1 < 12: y1, y2 = min(y1, -6), max(y2, 6)
    one_side = len(pins) > 1 and (min(xs) > 0 or max(xs) < 0 or min(ys) > 0 or max(ys) < 0)
    for r in ((t.get('vrect'), t.get('drect')) if one_side else ()):
        if r: x1, y1, x2, y2 = min(x1, r[0]), min(y1, r[1]), max(x2, r[2]), max(y2, r[3])
    return [x1, y1, x2, y2]

# Partes analogicas e instrumentos aprendidos de General.CKT de Jose (cada pin con un cable).
# clave|simbolo CM|devid|m|flags|valor|rect valor|designador|rect designador|netlist SPICE (\n = salto)|encapsulado|L8[0]|pines nombre:num:dx:dy
ANALOG = r'''
RESISTOR|Resistor~|219|5|864|1k|-7 -14 7 -6|R1|-7 -24 7 -16|%D %1 %2 %V|AXIAL0.4|82|1:1:-18:0 2:2:18:0
RESISTORA|Resistor:A~|219|5|864|1k|-7 -14 7 -6|R2|-7 -24 7 -16|%D %1 %2 %V|AXIAL0.4|82|1:1:-18:0 2:2:18:0
SEMIRESISTOR|SemiResistor~|219|5|832|RESISTOR|-28 -14 28 -6|R3|-7 -24 7 -16|%D %1 %2 %M 1K|AXIAL0.4|82|1:1:-18:0 2:2:18:0
SEMIRESISTORA|SemiResistorA~|219|5|832|RESISTOR|-28 -14 28 -6|R4|-7 -24 7 -16|%D %1 %2 %M 1K|AXIAL0.4|82|1:1:-18:0 2:2:18:0
VARRESISTOR|Var Resistor~|219|7|832|10k 40%|-25 18 24 26|R5|-7 8 7 16|%DA %1 %2 4K\n%DB %2 %3 6K|SIP3|82|1:1:-18:0 W:2:-2:-12 3:3:18:0
VARRESISTORA|Var ResistorA~|219|7|832|10k 40%|-25 18 24 26|R6|-7 8 7 16|%DA %1 %2 4K\n%DB %2 %3 6K|SIP3|82|1:1:-18:0 W:2:-2:-12 3:3:18:0
CAPACITOR|Capacitor~|219|5|832|1uF|-11 -18 10 -10|C1|-7 -28 7 -20|%D %1 %2 %V|RAD0.2|67|1:1:-9:0 2:2:9:0
POLARCAP|Polar Cap~|219|5|832|1uF|-9 -18 12 -10|C2|-5 -28 9 -20|%D %1 %2 %V|POLAR0.6|67|+:1:-11:0 -:2:6:0
SEMICAPACITOR|SemiCapacitor~|219|5|832|CAP|-11 -18 10 -10|C3|-7 -28 7 -20|%D %1 %2 %M|RAD0.2|67|1:1:-9:0 2:2:9:0
VARCAPACITOR|Var Capacitor~|219|5|832|1uF|-11 -20 10 -12|C4|-7 -30 7 -22|%D %1 %2 %V|RAD0.2|67|1:1:-14:0 2:2:14:0
INDUCTOR|Inductor~|219|5|832|1uH|-10 -17 11 -9|L3|-7 -27 7 -19|%D %1 %2 %V|AXIAL0.4|76|1:1:-18:0 2:2:18:0
VARINDUCTOR|Var Inductor~|219|5|832|1uH|-12 -22 9 -14|L4|-8 -32 6 -24|%D %1 %2 %V|AXIAL0.4|76|1:1:-18:0 2:2:18:0
COIL3T|Coil 3T~|219|5|832|1uH|-11 -16 10 -8|L1|-7 -26 7 -18|%D %1 %2 %V|AXIAL0.4|76|1:1:-20:0 2:2:20:0
COIL5T|Coil 5T~|219|5|832|1mH|-11 -16 10 -8|L2|-7 -26 7 -18|%D %1 %2 %V|AXIAL0.6|76|1:1:-26:0 2:2:26:0
DIODE|Diode~|219|5|832|DIODE|-18 -18 17 -10|D1|-7 -28 7 -20|%D %1 %2 %M|DOIODE0.4|68|A:1:-10:0 K:2:10:0
SCHOTTKY|Schottky~|219|5|832|SCHOTTKY|-27 -18 29 -10|D7|-6 -28 8 -20|%D %1 %2 %M|DIODE0.4|68|A:1:-11:0 K:2:12:0
ZENERDIODE|Zener Diode~|219|5|832|ZENER|-16 -22 19 -14|D11|-9 -32 12 -24|%D %1 %2 %M|DIODE0.4|100|A:1:-10:0 K:2:10:0
VARACTOR|Varactor~|219|5|832|VARACTOR|-28 -18 28 -10|D8|-7 -28 7 -20|%D %1 %2 %M|DIODE0.4|68|A:1:-11:0 K:2:12:0
VARACTORA|Varactor:A~|219|5|832|VARACTOR|-25 -18 31 -10|D9|-4 -28 10 -20|%D %1 %2 %M|DIODE0.4|68|A:1:-11:0 K:2:12:0
LED|LED~|171|2|880|LED1|17 0 45 8|D6|24 -10 38 -2|%D %1 %2 %M|SIP2|68|A:1:0:-10 K:2:0:10
DIODEAKA|Diode AKA~|219|7|832|DIODE|-18 -21 17 -13|D3|-7 -31 7 -23|%D %1 %2 %3 %S||88|A1:1:-31:-3 K:2:0:12 A2:3:31:-3
DIODEKAK|Diode KAK~|219|7|832|DIODE|-18 -21 17 -13|D4|-7 -31 7 -23|%D %1 %2 %3 %S||88|K1:1:-31:-3 A:2:0:12 K2:3:31:-3
DIODEACK|Diode ACK~|219|7|832|DIODE|-18 -21 17 -13|D2|-7 -31 7 -23|%D %1 %2 %3 %S||88|A:1:-31:-3 C:2:0:12 K:3:31:-3
ZENERAKA|Zener AKA~|219|7|832|DZ23C2V7|-28 -21 28 -13|D10|-11 -31 10 -23|%D %1 %2 %3 %S||88|A1:1:-31:0 K:2:0:15 A2:3:31:0
FWBRIDGE|FW Bridge~|219|9|832|BRIDGE|32 -40 74 -32|D5|46 -50 60 -42|%D %1 %2 %3 %4 %S|SIP4|88|-:1:-30:-4 AC1:2:2:-36 +:3:34:-4 AC2:4:2:28
NPNTRANSB|NPN Trans:B~|219|7|832|NPN|17 0 38 8|Q1|21 -10 35 -2|%D %1 %2 %3 %M|TO-92B|81|C:1:5:-18 B:2:-18:0 E:3:5:18
NPNTRANSC|NPN Trans:C~|219|7|832|NPN|17 0 38 8|Q2|21 -10 35 -2|%D %1 %2 %3 %M|TO-92B|81|C:1:5:-18 B:2:-18:0 E:3:5:18
PNPTRANSB|PNP Trans:B~|219|7|832|PNP|18 1 39 9|Q3|22 -9 36 -1|%D %1 %2 %3 %M|TO-92B|113|C:1:5:-18 B:2:-18:0 E:3:5:18
PNPTRANSC|PNP Trans:C~|219|7|832|PNP|17 0 38 8|Q4|21 -10 35 -2|%D %1 %2 %3 %M|TO-92B|113|C:1:5:-18 B:2:-18:0 E:3:5:18
BATTERY|Battery~|219|5|864|10V|12 -2 33 6|V3|16 -12 30 -4|%D %1 %2 DC %V||86|+:1:0:-13 -:2:0:11
V|+V|167|3|54240|10V|-7 -23 14 -15|V2|-7 -32 7 -24|%D %1 0 DC %V||86|V:1:0:9
VSOURCE|V Source~|197|5|17248|10V|13 0 34 8|Vs1|13 -10 34 -2|%D %1 %2 %V||86|+:1:0:-21 -:2:0:21
ISOURCE|I Source~|198|5|17248|100mA|13 0 48 8|Is1|20 -10 41 -2|%D %1 %2 %V||73|+:1:0:-21 -:2:0:21
SIGNALGEN|Signal Gen~|195|64|832|-1/1V|-18 -30 17 -22|V1|-7 -40 7 -32|%D %1 %2 DC 0 SIN(0 1 1k 0 0) AC 1 0|SIP2|86|+:1:31:-5 -:2:31:5
MULTIMETER|Multimeter~|205|21|16448|100.0Meg|-28 -19 28 -11|MM0|-11 -29 10 -21|%D %1 %4 %V||82|+:1:-25:23 -:4:25:23
DATASEQ|Data Seq~|170|18|4704|DIGSRC|-21 -44 21 -36|DS1|-11 -44 10 -36|%D [%9i %10i][%1o %2o %3o %4o %5o %6o %7o %8o] %M|SIP10|65|8:1:32:-27 7:2:32:-18 6:3:32:-9 5:4:32:0 4:5:32:9 3:6:32:18 2:7:32:27 1:8:32:36 CP1:9:-32:27 CP2:10:-38:36
'''
# Lo que se sale del formato comun (arreglo de estado, mapa de pines, lineas extra)
ANALOG_SPECIAL = json.loads(r'''{"DIODE":{"pm":[0,-54,-44,-54,-44,0]},"LED":{"g4":1,"set":{"0":10}},"SIGNALGEN":{"g4":64,"A":"20","xarr":[[1,1000,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]],"set":{"3":2,"4":86,"5":-8,"6":8,"16":1065353216,"17":1148846080,"19":1065353216,"64":46}},"MULTIMETER":{"g4":17,"prefix":"R","set":{"10":78,"11":79,"12":32,"13":68,"14":65,"15":84,"16":65,"17":32}},"DATASEQ":{"g4":17,"s4":"type:source {file=%D.src}","pm":[0,8,7,6,5,4,3,2,1,9,10,8,7,6,5,4,3,2,1,9,10,0],"extra":["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],"set":{"11":1,"12":1,"13":1,"14":1,"15":1,"17":33}}}''')

def _mk_parts(table, special, src='General.CKT'):
    out = {}
    ints = lambda v: [int(x) for x in v.split()] if v else None
    for line in table.strip().splitlines():
        k, name, dev, m, fl, val, vr, des, dr, sp, pkg, l8, pins = line.split('|')
        pins = {a: [int(b), int(c), int(d)] for a, b, c, d in (x.split(':') for x in pins.split())}
        n = max(v[0] for v in pins.values()); x = special.get(k, {})
        arr = [0] * (x.get('g4', n) + 1)
        for i, v in x.get('set', {}).items(): arr[int(i)] = v
        t = {'name': name, 'g': [int(dev), 0, 0, 0, len(arr) - 1, int(m)], 'arr': arr, 'A': x.get('A', '0'),
             'flags': [0, 0, int(fl), 0], 'value': val, 'vrect': ints(vr), 'des': des, 'drect': ints(dr),
             's': ['', '', sp.replace('\\n', '\r\n'), '', x.get('s4', ''), pkg],
             'pm': x.get('pm', [0] + list(range(1, n + 1)) * 2 + [0]), 'L8': [int(l8), 0, 0, 512, 1, 0, 0, 0],
             'prefix': x.get('prefix', re.match(r'[A-Za-z]+', des).group(0)), 'id': [0, 0, 0], 'dbl': '0 0', 'end': '0'}
        if 'xarr' in x: t['xarr'] = x['xarr']
        if 'extra' in x: t['extra'] = x['extra']
        out[k] = {'tpl': t, 'pins': pins, 'sections': 1, 'npins': n, 'bbox': auto_bbox(t, pins), 'desc': name + ' (' + src + ')'}
    return out

BUILTIN.update(_mk_parts(ANALOG, ANALOG_SPECIAL))

# Partes aprendidas de los 82 ejemplos de CircuitMaker y verificadas por Jose en un catalogo (todos los cables
# llegaron a su pin). Una por linea:
# clave|simbolo|devid g4 m|flags|L8|campo A|valor|rect valor|designador|rect desig.|s0|rect s0|s1 (VCC/GND)|
# netlist (\n = salto)|s4|encapsulado|prefijo|mapa de pines (=P1 P2..;fin si es simetrico)|arreglo extra i:v|
# pines (num:dx:dy => nombre Pnum, o nombre:num:dx:dy)|pines ocultos|descripcion
def _ints(v): return [int(x) for x in v.split()] if v else None
def _mk_learned(table):
    out = {}
    for line in table.strip().splitlines():
        (k, name, g, fl, l8, A, val, vr, des, dr, s0, sr, s1, sp, s4, pkg, pre, pm, st, pins, hid, desc) = line.split('|')
        dev, g4, m = _ints(g); L8 = _ints(l8)
        if pm.startswith('='):
            a, end = pm[1:].split(';'); a = _ints(a); pm = [0] + a + a + [int(end)]
        else: pm = _ints(pm)
        arr = [0] * (g4 + 1)
        for x in st.split(): i, v = x.split(':'); arr[int(i)] = int(v)
        P = {}
        for x in pins.split():
            f = x.split(':')
            if len(f) == 3: f = ['P' + f[0]] + f
            P[f[0]] = [int(f[1]), int(f[2]), int(f[3])]
        t = {'name': name, 'g': [dev, 0, 0, 0, g4, m], 'arr': arr, 'A': A, 'flags': [0, 0, int(fl), 0], 'value': val,
             'vrect': _ints(vr), 'des': des, 'drect': _ints(dr), 's': [s0, s1, sp.replace('\\n', '\r\n'), '', s4, pkg],
             'pm': pm, 'L8': L8, 'prefix': pre, 'id': [0, 0, 0], 'dbl': '0 0', 'end': '0'}
        if s0: t['srect'] = _ints(sr)
        secs = L8[4] if L8[0] == 65 and L8[5] else 1
        n = max([v[0] for v in P.values()] + _ints(hid or '0'))
        out[k] = {'tpl': t, 'pins': P, 'sections': secs, 'npins': n, 'bbox': auto_bbox(t, P), 'desc': desc}
        if hid: out[k]['hidden'] = _ints(hid)
    return out

LEARNED = r'''
74LS139|74LS139|118 14 29|12528|65 0 0 0 1 1 0 0|0|74LS139|-24 -51 25 -43|U3|-7 -61 7 -53|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i]\n+[%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type: digital|DIP16|U|=3 2 1 13 14 15 7 6 5 4 9 10 11 12;-33686019||1:-32:-18 2:-32:-9 3:-38:0 4:-32:18 5:-32:27 6:-38:36 7:38:-27 8:38:-18 9:38:-9 10:38:0 11:38:9 12:38:18 13:38:27 14:38:36||Doble decodificador 2 a 4, salidas activas en bajo
74LS75|74LS75|103 14 29|12528|65 0 0 512 1 1 0 0|0|74LS75|-21 -51 21 -43|U4|-7 -61 7 -53|||DVCC=5;DGND=12;|%D [%5bi %12bi %1i %2i %3i %4i %5i %6i]\n+ [%5bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=7 6 4 3 2 13 9 8 10 11 15 14 16 1;-33686019||1:-32:-27 2:-32:-18 3:-32:-9 4:-32:9 5:-32:18 6:-32:27 7:32:-27 8:38:-18 9:32:-9 10:38:0 11:32:9 12:38:18 13:32:27 14:38:36||4 latches D (cerrojos transparentes)
4INOR|4-In OR~|219 5 21|112|65 0 0 0 2 1 3 0|0|4072|-14 -24 14 -16|U2A|-11 -34 10 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i %3i %4i][%14bo %1o %2o %3o %4o %5o] %M|type:digital|DIP14|U|0 2 3 4 5 1 2 3 4 5 1 9 10 11 12 13 -33686019||1:-17:-13 2:-17:-4 3:-17:5 4:-17:14 5:33:0||OR de 4 entradas 4072 (2 por chip)
2INNORDM|2-In NOR:DM~|219 3 21|112|65 0 0 0 4 1 2 0|12 2-In NOR:DM~|74LS02|-21 -24 21 -16|U1D|-11 -34 10 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 12 13 11 1 2 3 4 5 6 9 10 8 12 13 11 -33686019||1:-30:-9 2:-30:9 3:21:0||NOR de 2 entradas 74LS02, simbolo De Morgan (4 por chip)
QUADDFLOP|Quad D Flop~|47 9 19|4208|65 0 0 512 1 1 0 0|0|QDFF|-14 -44 14 -36|U5|-7 -54 7 -46|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %9i][%16bo %1o %2o %3o %4o %9o %5o %6o %7o %8o] %M|type:digital|DIP16|U|=4 5 12 13 2 7 10 15 9;-33686019||1:-24:-30 2:-24:-18 3:-24:-6 4:-24:6 5:24:-30 6:24:-18 7:24:-6 8:24:6 9:0:36||4 flip-flops D con reloj comun (QDFF)
4X4SWITCH|4x4 Switch~|193 11 17|20592|0 0 0 0 1 0 0 0|0|||SW1|-20 -52 1 -44|||||||SW|=1 2 3 4 5 6 7 8;0|10:10 11:25|1:-51:-22 2:-51:-7 3:-51:7 4:-51:22 5:22:51 6:-22:51 7:-7:51 8:7:51||Matriz de 4x4 interruptores (teclado)
DOTIC|.IC~|207 1 64|53584|86 0 0 0 1 0 0 0|0|5V|-7 -15 7 -7|CMD1|-14 -25 14 -17||||.IC V(%1)=%V|||CMD|=1;-33686019||1:0:12||Directiva .IC: voltaje inicial de un nodo (valor = voltaje)
555TIMER|555 Timer~|219 8 17|6480|88 0 0 0 1 1 0 0|10 555 Timer~|555|-10 -23 11 -15|U7|-7 -33 7 -25||||%D %1 %2 %3 %4 %5 %6 %7 %8 %S||DIP8|U|=1 2 3 4 5 6 7 8;-33686019||1:-32:-9 2:-32:0 3:-32:9 4:-32:18 5:32:18 6:32:9 7:32:0 8:32:-9||Temporizador 555
NPNTRANS|NPN Trans~|219 3 64|592|81 0 0 0 1 1 0 0|10 NPN Trans~|2N2222A|8 -4 57 4|Q1|6 -4 20 4||||%D %1 %2 %3 %M||TO-18|Q|=3 2 1;-33686019||1:7:-18 2:-6:0 3:7:18||Transistor NPN 2N2222A (TO-18)
IVSOURCE|I->V Source~|201 4 64|17232|72 0 0 0 1 0 0 0|0|1K|-8 -19 6 -11|HLIM|-12 11 16 19||||V%D %3 %4 DC 0V\n%D %1 %2 V%D %V|||IcVs|=3 4 1 2;-33686019||1:20:-27 2:20:27 3:-20:-27 4:-20:27||Fuente de voltaje controlada por corriente (H)
VISOURCE|V->I Source~|200 4 64|17232|71 0 0 0 1 0 0 0|0|2.574E-9|-20 -19 36 -11|GCM|-10 11 11 19||||%D %1 %2 %3 %4 %V|||VcIs|=3 4 1 2;-33686019||1:20:-27 2:20:27 3:-20:-27 4:-20:27||Fuente de corriente controlada por voltaje (G)
NLISOURCE|NLI Source~|204 2 64|16976|66 0 0 0 1 0 0 0|0|100mA|-17 -31 18 -23|BB|14 -3 28 5||||%D %1 %2 I=I(VB)*10.61E6-I(VC)*10E6+I(VE)*10E6+I(VLP)*10E6-I(VLN)*10E6|||NLIs|=1 2;-33686019||1:0:-21 2:0:21||Fuente de corriente no lineal (B)
NLVSOURCE|NLV Source~|203 2 64|16976|66 0 0 0 1 0 0 0|0|||BGND|-41 0 -13 8||||%D %1 %2 V=V(vcc_1)*0.5+V(vee_1)*0.5|||NLVs|=1 2;-33686019||1:0:-21 2:0:21||Fuente de voltaje no lineal (B)
ADC0800|ADC0800|219 18 37|4976|88 0 0 0 1 1 0 0|8 ADC0800~|ADC0800|-25 -56 24 -48|U1|-7 -66 7 -58||||%D %1 %2 %3 %4 %5 %6 %7 %8 %9 %10 %11 %12 %13 %14 %15 %16 %17 %18 %S||DIP18|U|=1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18;-1610612644||1:-33:-27 2:-33:-18 3:-33:-9 4:-33:0 5:-33:9 6:-33:18 7:-33:27 8:-33:36 9:-33:45 10:33:45 11:33:36 12:33:27 13:33:18 14:33:9 15:33:0 16:33:-9 17:33:-18 18:33:-27||Convertidor A/D de 8 bits ADC0800
ADC8|ADC8|219 14 29|13040|65 0 0 512 1 1 0 0|4 ADC8|ADC8|-14 -56 14 -48|U1|-7 -66 7 -58|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i]\n+ [%16bo %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=1 2 3 4 5 6 7 9 10 11 12 13 14 15;-33686019||1:-33:-18 2:-33:0 3:-33:9 4:-33:27 5:-33:36 6:33:45 7:33:36 8:33:27 9:33:18 10:33:9 11:33:0 12:33:-9 13:33:-18 14:33:-27||Convertidor A/D de 8 bits generico
PIEZOBUZZER|Piezo Buzzer~|174 2 5|4208|67 0 0 0 1 1 0 0|0|.1uF|10 -16 38 -8||||||%D %1 %2 %V||SIP2|BZ|=1 2;-33686019|0:10|1:-31:0 2:31:0||Zumbador piezoelectrico
SPSTSWITCH|SPST Switch~|165 2 5|20592|0 0 0 0 1 0 0 0|0|||||||||||S|=1 2;0||1:17:0 2:-17:0||Interruptor SPST (se conmuta con clic)
SPDTRELAY|SPDT Relay~|176 10 64|880|88 0 0 0 1 0 0 0|0|12VSPDT|-45 -36 4 -28|RLY1|-38 -47 -10 -39||||%D %1 %2 %3 %4 %5 %S|alias:XSPDTRELAY {PULLIN=9.6 RESISTANCE=1000}|SIP5|RLY|=1 2 3 4 5;-33686019|10:1|1:14:-18 2:14:-25 3:14:-11 4:-16:-5 5:-16:19||Rele SPDT de 12 V
ASCIIKEY|Ascii Key~|169 11 11|20528|0 0 0 0 1 0 0 0|0|||||||||||KBD|=1 2 3 4 5 6 7 8;0|11:46|1:21:24 2:15:24 3:9:24 4:3:24 5:-3:24 6:-9:24 7:-15:24 8:-21:24||Teclado ASCII (7 bits + strobe)
HEXKEY|Hex Key~|166 11 64|20528|0 0 0 0 1 0 0 0|0||||||||||||=1 2 3 4;-1610612511|10:2 11:50|1:9:24 2:3:24 3:-3:24 4:-9:24||Teclado hexadecimal (4 bits)
LOGICDISPLAY|Logic Display~|6 1 3|53360|82 0 0 0 1 0 0 0|0|100MEG|3 -16 45 -8|R7|17 -26 31 -18||||%D %1 0 %V|||L|=1;0|0:10|1:0:18||Indicador logico de un bit
INVERTER|Inverter~|13 2 21|112|65 0 0 0 6 1 7 0|0|4069|-14 -19 14 -11|U1A|-11 -29 10 -21|||DVDD=14;DGND=7;|%D [%14bi %7bi %1i][%14bo %1o %2o] %M|type:digital|DIP14|U|0 1 2 1 2 3 4 5 6 9 8 11 10 13 12 -33686019||1:-15:0 2:21:0||Inversor 4069 (6 por chip)
74LS74|74LS74|17 12 64|4272|0 0 0 512 1 0 0 0|0|74LS74|-21 -61 21 -53|||||VCC=14;GND=7;|||DIP14|U|=3 2 4 1 11 12 10 13 5 6 9 8;-1610612632||1:-32:-36 2:-32:-27 3:-38:-18 4:-38:-9 5:-32:9 6:-32:18 7:-38:27 8:-38:36 9:32:-27 10:38:-18 11:32:18 12:38:27||Doble flip-flop D. Solo dibujo: sin modelo de simulacion
NOPUSHBUTTON|NO PushButton~|191 2 64|20592|0 0 0 0 1 0 0 0|0|||||||||||S|=1 2;-1610612495||1:17:8 2:-17:8||Pulsador normalmente abierto
MC1496|MC1496|219 10 64|12480|88 0 0 0 1 0 0 0|6 MC1496|MC1496|-21 -42 21 -34|U1|-7 -52 7 -44||||%D %1 %2 %3 %4 %5 %6 %7 %8 %9 %10 %S||DIP14|U|=2 8 10 1 4 14 5 12 6 3;-33686019||1:-32:-18 2:-32:-9 3:-32:0 4:-32:9 5:-32:18 6:32:18 7:32:9 8:32:0 9:32:-9 10:32:-18||Modulador/demodulador balanceado MC1496
OPAMP5|Op-Amp5~|219 5 64|848|88 0 0 0 1 0 0 0|8 Op-Amp5~|UA741|7 -13 42 -5|U1|15 -23 29 -15||||%D %1 %2 %3 %4 %5 %S||DIP8|U|=3 2 7 4 6;-33686019||1:-18:6 2:-18:-6 3:0:-13 4:0:13 5:18:0||Op-amp de 5 pines (UA741)
SPDTSWITCH|SPDT Switch~|164 3 11|20832|0 0 0 512 1 0 -1 0|0|S1|-7 -17 7 -9|S1|-7 -27 7 -19|||||||S|=1 2 3;0||1:17:0 2:-17:-4 3:-17:4||Interruptor SPDT
COAX|Coax~|219 64 64|16640|0 0 252 512 1 0 0 0|5 Coax~|Coax Cable 3|-42 -20 42 -12|CABL1|-18 -30 17 -22|||||||CABL|=1 2 3 4;0|64:-33686019|1:-48:-4 2:-48:4 3:48:-4 4:45:7||Cable coaxial (linea de transmision)
FUSE|Fuse~|219 2 64|4928|88 0 246 0 1 0 0 0|5 Fuse~|10A|-10 -16 11 -8|F2|-7 -26 7 -18||||%D %1 %2 %S||FUSE|F|=1 2;-33686019||1:-22:0 2:22:0||Fusible
NEMOS3TA|N-EMOS 3T:A~|219 3 64|832|77 0 546 0 1 0 0 0|12 N-EMOS 3T:A~|IRFP240|17 0 66 8|Q23|31 -10 52 -2||||%D %1 %2 %3 %3 %M||TO-92B|Q|=1 2 3;-33686019||1:6:-18 2:-18:9 3:6:18||MOSFET canal N de enriquecimiento IRFP240
REGULATOR3|Regulator3~|219 3 64|4864|88 0 238 0 1 0 0 0|11 Regulator3~|LM337M|-21 -28 21 -20|IC9|-11 -38 10 -30||||||TO-220|IC|=3 1 2;-33686019||1:-28:-9 2:0:24 3:28:-9||Regulador de 3 terminales (LM337M)
TERMINAL|Terminal~|194 1 64|20736|0 0 0 0 1 0 0 0|0|Direct In|-73 -6 -10 2|T2|-49 -16 -35 -8|||||||T|=1;-33686019||1:2:11||Terminal de conexion
TWISTEDPAIR|TwistedPair~|219 4 64|16640|0 0 254 512 1 0 0 0|12 TwistedPair~|Twisted Pair|-41 -18 43 -10|CABL3|-17 -28 18 -20|||||||CABL|=1 2 3 4;-33686019||1:-48:-4 2:-48:4 3:48:-4 4:48:4||Par trenzado (linea de transmision)
NODESET|.NODESET~|208 1 64|53568|86 0 0 0 1 0 0 0|0|10V|-10 -15 11 -7|CMD1|-13 -25 15 -17||||.NODESET V(%1)=%V|||CMD|=1;-33686019||1:0:12||Directiva .NODESET: valor inicial de un nodo para el punto de operacion
LOGICSWITCH|Logic Switch~|5 2 11|20592|86 0 0 0 1 0 -1 0|0|0V|-7 -16 7 -8|V1|-7 -26 7 -18||||*0=0V 1=5V\n%D %1 0 DC %V|||V|=1;0|2:-99|1:12:0||Interruptor logico (0/1)
74LS85|74LS85|106 14 29|12784|65 0 0 512 1 1 0 0|0|74LS85|-21 -51 21 -43|A6|-7 -61 7 -53|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i %7i %8i %9i %10i %11i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=15 13 12 10 1 14 11 9 2 3 4 7 6 5;-33686019||1:-32:-27 2:-32:-18 3:-32:-9 4:-32:0 5:-32:9 6:-32:18 7:-32:27 8:-32:36 9:32:-27 10:32:-18 11:32:-9 12:32:18 13:32:27 14:32:36||Comparador de magnitud de 4 bits
SCOPE|SCOPE|12 1 3|61680|0 0 0 0 1 0 0 0|0|TP1|-11 -4 10 4||||||||||=1;0||1:0:12||Punto de prueba para el osciloscopio
CA7SEG|CA 7-Seg~|184 18 64|20512|0 0 0 512 1 0 0 0|0||||||||||||=1 2 3 4 5 6 7 8 9;-1610612616|0:10 10:2 11:2 12:2 13:2 14:2 15:2 16:2 17:2 18:1|1:-21:36 2:-15:36 3:-9:36 4:-3:36 5:3:36 6:9:36 7:15:36 8:21:36 9:0:-36||Display 7 segmentos anodo comun
NJFET|N-JFET~|219 3 64|832|74 0 0 0 1 1 0 0|7 N-JFET~|2N4393|13 -3 55 5|Q1|27 -13 41 -5||||%D %1 %2 %3 %M||TO-18|Q|=2 3 1;-33686019||1:8:-18 2:-13:0 3:8:18||JFET canal N 2N4393
DAC8|DAC8|219 11 23|13040|65 0 0 0 1 0 0 0|4 DAC8|DAC8|-14 -55 14 -47|U1|-7 -55 7 -47|||DVCC=14;DGND=13;|%D [%14bi %13bi %1i %2i %3i %4i %5i %6i %7i %8i %9i %10i]\n+ [%14bo %1o %2o %3o %4o %5o %6o %7o %8o %11o] %M|type:digital|DIP14|U|=1 2 3 4 5 6 7 8 9 10 11;0||1:-33:-27 2:-33:-18 3:-33:-9 4:-33:0 5:-33:9 6:-33:18 7:-33:27 8:-33:36 9:33:18 10:33:9 11:33:-9||Convertidor D/A de 8 bits
3INNAND|3-In NAND~|219 4 21|608|65 0 0 0 3 1 6 0|0|74LS10|-21 -28 21 -20|U2A|-13 -4 8 4|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i %3i][%14bo %1o %2o %3o %4o] %M|type:digital|DIP14|U|0 1 2 13 12 1 2 13 12 3 4 5 6 9 10 11 8 -33686019||1:-24:-9 2:-24:0 3:-24:9 4:27:0||NAND de 3 entradas 74LS10 (3 por chip)
CC7SEG|CC 7-Seg~|183 9 19|20592|88 0 0 0 1 0 0 0|0|REDCC|16 -41 51 -33||||||%D %1 %2 %3 %4 %5 %6 %7 %8 %9 %S|||DISP|=1 2 3 4 5 6 7 8 9;0|0:10|1:-21:36 2:-15:36 3:-9:36 4:-3:36 5:3:36 6:9:36 7:15:36 8:21:36 9:0:-42||Display 7 segmentos catodo comun
STOPLIGHT|StopLight~|181 3 7|20592|82 0 0 0 1 0 0 0|0|1MEG|-15 -42 13 -34||||||%DA %1 0 %V\n%DB %2 0 %V\n%DC %3 0 %V|||SEM|=1 2 3;0||1:-16:-14 2:-16:0 3:-16:14||Semaforo de 3 luces
FVSOURCE|F->V Source~|219 4 9|592|88 0 0 0 0 0 0 0|0|FCVS|34 -2 62 6|V2|29 0 43 8||||%D %1 %2 %3 %4 %S|alias:XFTOV {VIL=0.1 VIH=0.2}||V|=1 2 3 4;0||1:-27:-24 2:-27:30 3:9:-24 4:9:30||Convertidor frecuencia a voltaje
2INOR|2-In OR~|219 3 21|112|65 0 0 0 4 1 10 0|0|74LS32|-21 -24 21 -16|U4C|-11 -34 10 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 9 10 8 1 2 3 4 5 6 9 10 8 12 13 11 -33686019||1:-13:-9 2:-13:9 3:33:0||OR de 2 entradas 74LS32 (4 por chip)
2INAND|2-In AND~|219 3 21|112|65 0 0 0 4 1 9 0|0|74LS08|-21 -24 21 -16|U3B|-11 -34 10 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 4 5 6 1 2 3 4 5 6 9 10 8 12 13 11 -33686019||1:-24:-9 2:-24:9 3:21:0||AND de 2 entradas 74LS08 (4 por chip)
SPEAKER|Speaker~|175 2 5|4208|82 0 0 0 1 1 0 0|0|8|-3 -22 4 -14|SPKR1|-17 -32 18 -24||||%D %1 %2 %V||SIP2|SPK|=1 2;-33686019|0:10|1:-8:-16 2:-8:16||Parlante de 8 ohm
2INNOR|2-In NOR~|219 3 21|112|65 0 0 0 4 1 1 0|0|74LS02|-21 -24 21 -16|U1A|-11 -34 10 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 1 2 3 1 2 3 4 5 6 9 10 8 12 13 11 0||1:-13:-9 2:-13:9 3:39:0||NOR de 2 entradas 74LS02 (4 por chip)
DCMOTOR|DC Motor~|219 2 5|112|76 0 0 0 0 0 0 0|0|100H|-15 -42 13 -34|M1|-8 -52 6 -44||||%D %1 N%D %V\nR%D N%D %2 10|||M|=0 0;0||1:-24:-1 2:24:-1||Motor DC
RELAYCOILA|Relay Coil:A~|209 2 5|5232|88 0 0 0 0 0 -2 0|0|120VCOIL|-28 -44 28 -36|RLY1|-14 -54 14 -46|K1|-10 -24 4 -16||*p=1 r=1\n%D %1 %2 %I %S|alias:XCOIL {PULLIN=96 RESISTANCE=2000}||RLY|=1 2;0||1:-13:-15 2:-13:9||Bobina de rele (diagrama escalera)
CONTACTSD|Contacts:D~|214 3 7|17520|88 0 0 0 0 0 -2 0|0|NORMAL|-21 -44 21 -36|RLY2|-14 -54 14 -46|K1|-6 -20 8 -12||%D %1 %3 N%D %I %S|alias:XCONTACTS||RLY|=1 2 3;0||1:18:0 3:-18:0|2|Contactos de rele, variante D (pin 2 oculto: enlace con la bobina)
SOLENOID|Solenoid~|210 2 5|5232|88 0 0 0 0 0 -3 0|0|5VCOIL|-21 -44 21 -36|RLY3|-14 -54 14 -46|S4|-7 -16 7 -8||*p=1 r=1\n%D %1 %2 %I %S|alias:XCOIL||RLY|=1 2;0||1:-20:0 2:20:0||Solenoide
CONTACTSE|Contacts:E~|214 3 7|17520|88 0 0 0 0 0 -5 0|0|NORMAL|-21 -44 21 -36|RLY11|-18 -54 17 -46|S2|-6 -21 8 -13||%D %1 N%D %2 %I %S|alias:XCONTACTS||RLY|=1 2 3;0||1:18:0 2:-18:0|3|Contactos de rele, variante E (pin 3 oculto: enlace con la bobina)
LAMP|Lamp~|206 2 5|96|82 0 0 0 0 0 0 0|0|100|-10 -24 11 -16|L1|-7 -34 7 -26||||%D %1 %2 %V|||L|=1 2;0|0:11|1:-12:13 2:12:13||Lampara
LOSSLESSLINE|LossLessLine~|219 4 64|848|84 0 0 0 1 0 0 0|13 LossLessLine~|ZO=50 TD=20NS|-46 -20 45 -12|LLTR1|-18 -30 17 -22||||%D %1 %2 %3 %4 %L|||LLTR|=1 2 3 4;-33686019||1:-48:-4 2:-48:4 3:48:-4 4:48:4||Linea de transmision sin perdidas
74LS164|74LS164|127 12 25|12528|65 0 0 512 1 1 0 0|0|74LS164|-24 -51 25 -43|A1|-7 -61 7 -53|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i %3i %4i]\n+ [%14bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o] %M|type:digital|DIP14|U|=1 2 8 9 13 12 11 10 6 5 4 3;-33686019||1:-32:-27 2:-32:-18 3:-32:0 4:-38:18 5:32:-27 6:32:-18 7:32:-9 8:32:0 9:32:9 10:32:18 11:32:27 12:32:36||Registro de desplazamiento 8 bits serie a paralelo
OPAMP7|Op-Amp7~|219 7 15|848|88 0 0 256 1 1 0 0|8 Op-Amp7~|LM301A|6 -24 48 -16|U1|20 -34 34 -26||||%D %1 %2 %3 %4 %5 %6 %7 %S||DIP8|U|=3 2 7 4 6 1 8;-33686019||1:-18:6 2:-18:-6 3:0:-13 4:0:13 5:18:0 6:16:-8 7:16:8||Op-amp de 7 pines (LM301A, con compensacion)
VMATH1|V-Math1~|219 2 5|5184|88 0 0 0 0 0 0 0|8 V-Math1~|UNARYV|-21 -26 21 -18|M1|-7 -36 7 -28|-(V)|-13 -14 15 -6||%D %1 %2 %S||-(V)|M|=1 2;0||1:-34:0 2:34:0||Funcion de un voltaje (por defecto -V)
VMATH2|V-Math2~|219 3 7|5184|88 0 0 256 0 0 0 0|8 V-Math2~|ADDV|-14 -36 14 -27|M3|-7 -46 7 -38|V(A+B)|-20 -23 22 -15||%D %1 %2 %3 %S||V(A+B)|M|=1 2 3;0||1:-34:-9 2:-34:0 3:34:-9||Operacion entre dos voltajes (por defecto A+B)
2INNAND|2-In NAND~|219 3 21|112|65 0 0 0 4 1 6 0|0|74LS00|-14 -24 28 -16|U6A|-4 -34 17 -26|||DVCC=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 1 2 3 1 2 3 4 5 6 9 10 8 12 13 11 -33686019||1:-24:-9 2:-24:9 3:27:0||NAND de 2 entradas 74LS00 (4 por chip)
74112|74112~|219 7 31|4208|65 0 0 512 2 1 3 0|0|74LS112|-3 -60 46 -52|U3A|11 -70 32 -62|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i][%16bo %1o %2o %3o %4o %5o %6o %7o] %M|type:digital|DIP16|U|0 4 3 1 2 15 6 5 4 3 1 2 15 6 5 10 11 13 12 14 7 9 -33686019||1:0:-63 2:-24:-36 3:-30:-27 4:-24:-18 5:0:12 6:30:-18 7:24:-36||Flip-flop JK 74LS112 (2 por chip)
74LS48|74LS48|188 14 29|12512|65 0 0 512 1 1 0 0|0|74LS48|-21 -60 21 -52|U1|-7 -70 7 -62|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i %14i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %14o %7o %8o %9o %10o %11o %12o %13o] %M|type:digital|DIP16|U|=6 2 1 7 3 5 14 15 9 10 11 12 13 4;-33686019||1:-32:-36 2:-32:-27 3:-32:-18 4:-32:-9 5:-32:36 6:-32:45 7:32:-36 8:32:-27 9:32:-18 10:32:-9 11:32:0 12:32:9 13:32:18 14:32:45||Decodificador BCD a 7 segmentos para catodo comun
74LS47|74LS47|187 14 29|12512|65 0 0 512 1 1 0 0|0|74LS47|-21 -60 21 -52|U2|-7 -70 7 -62|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i %14i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %14o %7o %8o %9o %10o %11o %12o %13o] %M|type:digital|DIP16|U|=6 2 1 7 3 5 14 15 9 10 11 12 13 4;-33686019||1:-32:-36 2:-32:-27 3:-32:-18 4:-32:-9 5:-32:36 6:-32:45 7:38:-36 8:38:-27 9:38:-18 10:38:-9 11:38:0 12:38:9 13:38:18 14:32:45||Decodificador BCD a 7 segmentos para anodo comun
OPTOISOLATOR|Opto Isolator~|173 4 9|96|88 0 0 0 1 1 0 0|0|OP4N25|-22 -28 20 -20|U1|-8 -38 6 -30||||%D %1 %2 %3 %4 %S||DIP6|U|=1 2 5 4;-33686019||1:-28:-12 2:-28:12 3:26:-12 4:26:12||Optoacoplador 4N25
4093|4093~|219 3 21|352|65 0 0 0 4 1 1 0|0|4093|2 -26 30 -18|U1A|-4 -34 17 -26|||DVDD=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 1 2 3 1 2 3 5 6 4 8 9 10 12 13 11 0||1:-24:-9 2:-24:9 3:27:0||NAND Schmitt de 2 entradas 4093 (4 por chip)
4011|4011~|219 3 21|96|65 0 0 0 4 1 2 0|0|4011|-7 -24 21 -16|U1B|-4 -34 17 -26|||DVDD=14;DGND=7;|%D [%14bi %7bi %1i %2i][%14bo %1o %2o %3o] %M|type:digital|DIP14|U|0 5 6 4 1 2 3 5 6 4 8 9 10 12 13 11 0||1:-24:-9 2:-24:9 3:27:0||NAND de 2 entradas CMOS 4011 (4 por chip)
SIP2|SIP2~|219 2 64|3952|0 0 0 0 1 1 0 0|5 SIP2~|Output|-22 -21 20 -13|J2|-8 -29 6 -21||||||SIP2|J|=1 2;15481944||1:-12:-4 2:-12:5||Conector de 2 pines
PLL|PLL|219 8 17|15056|88 0 0 0 1 1 0 0|3 PLL|PLL100K|-29 8 20 16|PLL1|-40 -64 -12 -56||||%D %1 %2 %3 %4 %5 %6 %7 %8 %S|alias:XPLLX {Fc=100k Fr=50k}|DIP8|PLL|=1 2 3 4 5 6 7 8;-33686019||1:-59:-36 2:-59:-27 3:-59:-18 4:-59:0 5:5:0 6:5:-9 7:5:-18 8:5:-36||Lazo de seguimiento de fase (PLL)
PEMOS3TA|P-EMOS 3T:A~|219 3 7|832|109 0 552 256 1 1 0 0|12 P-EMOS 3T:A~|IRF9510|16 8 65 16|Q1A|30 -3 51 5||||%D %1 %2 %3 %3 %M||TO-220|Q|=2 1 3;-33686019||1:6:-18 2:-18:9 3:6:18||MOSFET canal P de enriquecimiento IRF9510
4017|4017|219 14 29|12512|65 0 0 512 1 1 0 0|0|4017|-14 -60 14 -52|U3|-7 -70 7 -62|||DVDD=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=13 14 15 3 2 4 7 10 1 5 6 9 11 12;-33686019||1:-38:18 2:-32:27 3:-32:45 4:32:54 5:32:45 6:32:36 7:32:27 8:32:18 9:32:9 10:32:0 11:32:-9 12:32:-18 13:32:-27 14:38:-36||Contador decimal Johnson con 10 salidas decodificadas
3INNOR|3-In NOR~|219 4 21|96|65 0 0 0 3 1 2 0|0|4025|-14 -24 14 -16|U1C|-11 -34 10 -26|||DVDD=14;DGND=7;|%D [%14bi %7bi %1i %2i %3i][%14bo %1o %2o %3o %4o] %M|type:digital|DIP14|U|0 11 12 13 10 3 4 5 6 1 2 8 9 11 12 13 10 -33686019||1:-13:-9 2:-12:0 3:-13:9 4:39:0||NOR de 3 entradas 4025 (3 por chip)
TRANS2|Trans2~|219 4 9|336|88 0 0 0 1 0 0 0|0|10TO1|-16 -32 19 -24|T1|-6 -42 8 -34||||%D %1 %2 %3 %4 %S|alias:XTRANS {RATIO=0.1}||T|=1 2 3 4;0||1:-18:-11 2:-18:11 3:18:-19 4:18:19||Transformador de 2 devanados (10:1)
TRANS3|Trans3~|219 5 11|336|88 0 0 0 1 0 0 0|0|5TO1CT|-20 -32 22 -24|T1|-6 -42 8 -34||||%D %1 %2 %3 %4 %5 %S|alias:XTRANSCT {RATIO=.2}||T|=1 2 3 4 5;0||1:-18:-11 2:-18:11 3:22:-19 4:22:0 5:22:19||Transformador con toma central (5:1)
TRIODE|Triode~|219 3 64|336|88 0 0 0 1 0 0 0|7 Triode~|12AX7|13 17 48 25|Q1|26 6 40 14||||%D %1 %2 %3 %S|||Q|=1 2 3;-33686019||1:0:-26 2:-26:0 3:-11:23||Triodo de vacio 12AX7
74LS168|74LS168|8 14 29|12528|65 0 0 512 1 1 0 0|0|74LS168A|-28 -60 28 -52|U3|-7 -70 7 -62|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i %7i %8i %9i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=7 10 2 6 5 4 3 9 1 15 11 12 13 14;-33686019||1:-38:-36 2:-38:-27 3:-32:-18 4:-32:9 5:-32:18 6:-32:27 7:-32:36 8:38:-36 9:32:-27 10:38:0 11:32:9 12:32:18 13:32:27 14:32:36||Contador decada ascendente/descendente sincrono
SCR|SCR~|219 3 7|832|88 0 0 256 1 1 0 0|4 SCR~|2N5064|12 0 54 8|SCR1|19 -10 47 -2||||%D %1 %2 %3 %S||TO-92B|SCR|=1 2 3;-33686019||1:0:-12 2:-13:6 3:0:12||Tiristor SCR 2N5064
74LS173|74LS173|129 14 29|12528|65 0 0 0 1 1 0 0|0|74LS173|-24 -51 25 -43|U5|-7 -61 7 -53|||DVCC=16;DGND=8;|%D [%16bi %8bi %1i %2i %3i %4i %5i %6i %7i %8i %9i %10i]\n+ [%16bo %1o %2o %3o %4o %5o %6o %7o %8o %9o %10o %11o %12o %13o %14o] %M|type:digital|DIP16|U|=15 9 10 7 11 12 13 14 1 2 6 5 4 3;-33686019||1:-32:-27 2:-38:-18 3:-38:-9 4:-32:0 5:-32:9 6:-32:18 7:-32:27 8:-32:36 9:38:-27 10:38:-18 11:32:9 12:32:18 13:32:27 14:32:36||Registro de 4 bits con salidas de 3 estados
TRIACB|Triac:B~|219 3 64|320|88 0 0 0 1 0 0 0|8 Triac:B~|MAC210-6|20 -4 76 4|Q1|41 -14 55 -6||||%D %1 %2 %3 %S||TO-220|Q|=2 3 1;-33686019||1:0:-18 2:-16:10 3:0:18||Triac MAC210-6
VCO|VCO~|221 5 9|592|65 0 0 0 1 0 0 0|0|SQRVCO|20 -2 62 6|V1|35 -1 49 7||||%D %%vd(%1,%2) %%vd(%3,%4) %M|alias:ASQRVCO||V|=1 2 3 4;0|0:13 5:2|1:-27:-24 2:-27:30 3:9:-24 4:9:30||Oscilador controlado por voltaje (onda cuadrada)
TETRODE|Tetrode~|219 4 64|320|88 0 0 0 1 0 0 0|8 Tetrode~|7199P|-1 24 34 32|Q1|9 14 23 22||||%D %1 %2 %3 %4 %S|||Q|=1 2 3 4;-33686019||1:0:-26 2:26:-3 3:-26:3 4:-11:23||Tetrodo de vacio 7199P
NMOSFET3T|N-MOSFET 3T~|219 3 64|848|77 0 0 0 1 0 0 0|12 N-MOSFET 3T~|NMOS|23 -4 51 4|M1|30 -14 44 -6||||%D %1 %2 %3 %3 %M W=40U L=10U|||Q|=1 2 3;-33686019||1:10:-18 2:-10:9 3:10:15||MOSFET canal N generico
CRYSTAL|Crystal~|219 2 64|848|88 0 0 0 0 0 0 0|8 Crystal~|3.5795MHZ|-29 -19 34 -11|XTAL|-12 -30 16 -22||||%D %1 %2 %S|alias:XCRYSTAL {FREQ=3.58E6 RS=160 C=1.8E-11}|HC49|XTAL|=1 2;-33686019||1:-11:0 2:11:0||Cristal de cuarzo
XFMR|xfmr~|219 4 9|4944|88 0 0 0 1 0 0 0|0|DEFAULT|-22 -36 27 -28|T1|-4 -46 10 -38||||%D %1 %2 %3 %4 %S|alias:XXFMR {PRIT=10 SECT=100 FRAC=TRUE}||T|=1 2 3 4;0||1:-24:-18 2:-24:18 3:30:18 4:30:-18||Transformador (subcircuito xfmr)
'''
BUILTIN.update(_mk_learned(LEARNED))

USER_PARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ckt_parts.json')
PARTS = dict(BUILTIN)
if os.path.exists(USER_PARTS): PARTS.update(json.load(open(USER_PARTS)))

def _rt(c):
    """rotacion guardada: CircuitMaker puede sumar 512 como bandera (782 = 270, visto en General.CKT)."""
    return c['flags'][3] % 512

def rot(dx, dy, r):
    r %= 360
    return {0: (dx, dy), 90: (dy, -dx), 180: (-dx, -dy), 270: (-dy, dx)}[r]
def unrot(dx, dy, r): return rot(dx, dy, (360 - r) % 360)
def _side(dx, dy):
    if abs(dx) >= abs(dy): return 'R' if dx > 0 else 'L'
    return 'B' if dy > 0 else 'T'
_DIR = {'L': (-1, 0), 'R': (1, 0), 'T': (0, -1), 'B': (0, 1)}

# ------------------------------------------------------------ constructor
class Pin:
    def __init__(s, comp, name, num, x, y, side): s.comp, s.name, s.num, s.x, s.y, s.side = comp, name, num, x, y, side
    def __repr__(s): return '<%s.%s>' % (s.comp.des or s.comp.kind, s.name)

class Comp:
    def __init__(s, circ, kind, x, y, r, section, des):
        s.c, s.kind, s.x, s.y, s.r, s.section, s.des = circ, kind, x, y, r, section, des
        s.part = PARTS[kind]
    def __getitem__(s, name):
        name = str(name)
        if name.startswith('#') and s.part.get('sections', 1) == 1:  # '#7' = pin fisico 7 del encapsulado
            pm = s.part['tpl']['pm']
            hit = [n for n, v in s.part['pins'].items() if v[0] < len(pm) and str(pm[v[0]]) == name[1:]]
            if hit: name = hit[0]
        if name not in s.part['pins']:
            raise KeyError('%s no tiene pin %r (pines: %s)' % (s.kind, name, ', '.join(s.part['pins'])))
        num, dx0, dy0 = s.part['pins'][name]; dx, dy = rot(dx0, dy0, s.r)
        col = sum(1 for v in s.part['pins'].values() if v[1] == dx0)
        if abs(dx0) >= 20 and col >= 4:  # pin de una columna lateral de CI (p. ej. Q0 del 4040, O8 del Data Seq)
            side = _side(*rot(1 if dx0 > 0 else -1, 0, s.r))
        else: side = _side(dx, dy)
        return Pin(s, name, num, s.x + dx, s.y + dy, side)
    def pins(s): return [s[n] for n in s.part['pins']]

def _isotonic_slots(vals, gaps):
    """posiciones ordenadas con separacion minima gaps[i] entre i e i+1, minimo desplazamiento (PAVA)."""
    cum = [0]
    for g_ in gaps[:len(vals) - 1]: cum.append(cum[-1] + g_)
    s = [v - cum[i] for i, v in enumerate(vals)]; blocks = []
    for v in s:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b = blocks.pop(); blocks[-1][0] += b[0]; blocks[-1][1] += b[1]
    out = []
    for tot, n in blocks: out += [tot / n] * n
    return [int(round(v)) + cum[i] for i, v in enumerate(out)]

class Circuit:
    LABEL_PITCH = 12   # separacion entre etiquetas contiguas
    def __init__(s):
        s.comps, s.wires, s.labels, s.texts, s.cnt, s.pkg = [], [], [], [], {}, {}
    # --- componentes
    def add(s, kind, x, y, rot=0, section=None, chip=None, des=None, value=None):
        """Agrega un componente. Para compuertas/4518: section='A'.. y chip='U7' agrupa en un mismo CI.
        value: valor mostrado/simulado ('10k', '100nF', '12V', modelo '1N4148', o '10k 25%' en potenciometros)."""
        if kind not in PARTS: raise KeyError('Parte desconocida %r. Disponibles: %s' % (kind, ', '.join(PARTS)))
        p = PARTS[kind]; sec = None
        if p.get('sections', 1) > 1:
            sec = 'ABCDEFGH'.index((section or 'A').upper()) + 1
        c = Comp(s, kind, int(x), int(y), rot, sec, des); c.chip = chip; c.value = value
        s.comps.append(c); return c
    def gate(s, kind, x, y, chip, section, rot=0):
        return s.add(kind, x, y, rot, section=section, chip=chip)
    # --- conexiones
    def net(s, pin, name):
        """Conecta pin a una red nombrada mediante etiqueta automatica (o simbolo de tierra si name=='GND')."""
        if any(l[0].comp is pin.comp and l[0].num == pin.num for l in s.labels):
            raise ValueError('%r ya tiene etiqueta' % pin)
        name = str(name).upper() if str(name).upper() == 'GND' else str(name)
        if name != 'GND' and len(name) > 8: raise ValueError('Etiqueta max 8 caracteres: %r' % name)
        s.labels.append((pin, name))
    def nets(s, comp, mapping):
        for p, n in mapping.items(): s.net(comp[p], n)
    def wire(s, a, b, via=None):
        """Cable directo pin a pin. via = lista de puntos intermedios opcional."""
        s.wires.append((a, b, via))
    def text(s, x, y, text, size=13, bold=False, face='Courier New', width=None):
        s.texts.append((x, y, text, size, bold, face, width))
    # --- construccion
    def _lead(s, p, n=6):
        dx, dy = _DIR[p.side]; return (p.x + dx * n, p.y + dy * n)
    def _route(s, a, b, via):
        if via: return [(a.x, a.y)] + [tuple(v) for v in via] + [(b.x, b.y)]
        la, lb = s._lead(a), s._lead(b)
        if a.comp is b.comp and {a.side, b.side} == {'L', 'R'}:
            yb = max(p.y for p in a.comp.pins()) + 12
            return [(a.x, a.y), la, (la[0], yb), (lb[0], yb), lb, (b.x, b.y)]
        if a.side in 'LR': mid = [(lb[0], la[1])]
        else: mid = [(la[0], lb[1])]
        return [(a.x, a.y), la] + mid + [lb, (b.x, b.y)]

    def build(s):
        comps = list(s.comps); cw = []; lab = []
        for a, b, via in s.wires: cw.append((a, b, s._route(a, b, via)))
        # ---- etiquetas: agrupar por (componente, lado) y abrir en abanico
        groups = {}
        for pin, name in s.labels: groups.setdefault((id(pin.comp), pin.side), []).append((pin, name))
        for (_, side), items in groups.items():
            horiz = side in 'LR'
            items.sort(key=lambda t: t[0].y if horiz else t[0].x)
            coord = [(p.y if horiz else p.x) for p, _ in items]
            gaps = [s.LABEL_PITCH + (10 if horiz and n == 'GND' else 0) for _, n in items]
            slots = _isotonic_slots(coord, gaps)
            sg = -1 if side in 'LT' else 1
            ext = (min if sg < 0 else max)([(p.x if horiz else p.y) for p, _ in items])
            ups = sorted([i for i in range(len(items)) if slots[i] < coord[i]], key=lambda i: coord[i])
            dns = sorted([i for i in range(len(items)) if slots[i] > coord[i]], key=lambda i: -coord[i])
            jog = {}
            for lst in (ups, dns):
                for j, i in enumerate(lst): jog[i] = ext + sg * (5 + 3 * j)
            lpos = ext + sg * (10 + 3 * max(len(ups), len(dns)))
            for i, (p, name) in enumerate(items):
                sl = slots[i]
                if horiz:
                    pts = [(p.x, p.y)] + ([(jog[i], p.y), (jog[i], sl)] if i in jog else []) + [(lpos, sl)]
                    end = (lpos, sl)
                else:
                    pts = [(p.x, p.y)] + ([(p.x, jog[i]), (sl, jog[i])] if i in jog else []) + [(sl, lpos)]
                    end = (sl, lpos)
                if name == 'GND':
                    t = s.add('GND', end[0], end[1] + 6); tp = t['1']
                else:
                    kind, r = {'L': ('IN', 0), 'R': ('OUT', 0), 'B': ('IN', 90), 'T': ('IN', 270)}[side]
                    dx, dy = rot(*PARTS[kind]['pins']['1'][1:], r)
                    t = s.add(kind, end[0] - dx, end[1] - dy, r); t.label = name; tp = t['1']
                s.comps.remove(t); lab.append(t)
                cw.append((p, tp, pts))
        allc = comps + lab
        # ---- redes (union-find)
        par = {}
        def f(k):
            while par.setdefault(k, k) != k: k = par[k]
            return k
        def u(a, b): par[f(a)] = f(b)
        key = lambda p: (id(p.comp), p.num)
        for a, b, _ in cw: u(key(a), key(b))
        for c in lab:
            u(key(c['1']), ('NET', getattr(c, 'label', 'GND')))
        for c in allc:
            if c.kind == 'GND': u(key(c['1']), ('NET', 'GND'))
        netid = {f(('NET', 'GND')): 2}; nxt = [3]
        def nid(k):
            r_ = f(k)
            if r_ not in netid: netid[r_] = nxt[0]; nxt[0] += 1
            return netid[r_]
        connected = set(par)
        # ---- designadores y paquetes
        cnt = {}; pk = {}; ids = random.sample(range(1, 10000), len(allc))
        ole = (datetime.datetime.now() - datetime.datetime(1899, 12, 30)).total_seconds() / 86400
        out = []; index = {}
        for i, c in enumerate(allc):
            p = PARTS[c.kind]; t = json.loads(json.dumps(p['tpl'])); index[id(c)] = i + 1
            t['g'][1], t['g'][2] = c.x, c.y; t['flags'][3] = c.r
            if c.kind in ('IN', 'OUT') and c.r % 360 == 270: t['flags'][3] = 782  # como lo guarda CircuitMaker
            fam = MODEL_FAMILY.get(c.kind)
            if getattr(c, 'value', None) is not None: _set_value(t, str(c.value))
            elif fam and t['value'] != MODELS[fam][2]: _set_value(t, MODELS[fam][2])  # el de plantilla no existe
            pre = re.match(r'[A-Za-z]+', t['des']).group(0) if t['des'] else t['prefix']
            if p.get('sections', 1) > 1:
                chipname = c.chip or c.des
                if not chipname:
                    cnt[pre] = cnt.get(pre, 0) + 1; chipname = '%s%d' % (pre, cnt[pre])
                elif chipname not in pk:
                    m = re.match(r'\D*(\d+)', chipname)
                    if m: cnt[pre] = max(cnt.get(pre, 0), int(m.group(1)))
                if chipname not in pk: pk[chipname] = len(pk) + 1
                t['des'] = chipname + 'ABCDEFGH'[c.section - 1]
                t['L8'][5], t['L8'][6] = c.section, pk[chipname]
                n = len(p['pins'])
                if any(t['pm'][1:1 + n]):  # compuerta: cabecera = pines fisicos de la seccion
                    allp = t['pm'][1 + n:1 + n + n * p['sections']]
                    t['pm'][1:1 + n] = allp[n * (c.section - 1):n * c.section]
            elif t['des'] or c.des:  # plantilla sin designador (Hex Key~, Scope...): se deja sin el
                if not t['des']: t['drect'] = [-7, -28, 7, -20]
                if c.des: t['des'] = c.des
                else: cnt[pre] = cnt.get(pre, 0) + 1; t['des'] = '%s%d' % (pre, cnt[pre])
            for num in range(1, p['npins'] + 1):
                k = (id(c), num)
                if num < len(t['arr']): t['arr'][num] = nid(k) if k in connected else None
            if c.kind in ('IN', 'OUT'):
                lbl = c.label.ljust(8)[:8]; t['arr'][10:18] = [ord(ch) for ch in lbl]
            t['id'] = [ids[i], 0, 0]; t['dbl'] = '%g %d' % (ole, len(allc) - 1 - i)
            c.des_final = t['des']; out.append(t)
        for t in out:  # pines sin conexion: red unica (como hace CircuitMaker)
            for j, v in enumerate(t['arr']):
                if v is None: t['arr'][j] = nxt[0]; nxt[0] += 1
        wires = []
        for a, b, pts in cw:
            pts = _clean(pts)
            wires.append([[a.num, b.num, nid(key(a)), 0, 0, 0, 0, index[id(a.comp)], index[id(b.comp)], 0, 0, len(pts)],
                          [list(p) for p in pts]])
        texts = []
        for x, y, txt, size, bold, face, width in s.texts:
            lines = txt.replace('\r\n', '\n').split('\n'); cwid = size * 0.62; lh = size * 1.25
            w = width or int(cwid * max(len(l) for l in lines) + 30); h = int(lh * len(lines) + 28)
            texts.append({'font': '-%d 0 0 0 %d 0 0 0 0 3 2 1 49' % (size, 700 if bold else 400), 'face': face,
                          'col': [0, 0, 0, len(_s(txt).split(b' ', 1)[-1].replace(b'\r\r\n', NL)) if txt else 0],
                          'r1': [x, y, x + w, y + h], 'r2': [x + 8, y + 7, x + w - 9, y + h - 8], 'text': txt})
        s.comps = comps
        return {'hdr': list(HEADER), 'comps': out, 'wires': wires, 'texts': texts, 'tail': TAIL}

    def save(s, path):
        d = s.build(); data = serialize(d); open(path, 'wb').write(data)
        probs = check(parse(data))
        for p in probs: print('AVISO:', p)
        return d

_SI = {'T': 1e12, 'G': 1e9, 'MEG': 1e6, 'K': 1e3, 'M': 1e-3, 'U': 1e-6, 'N': 1e-9, 'P': 1e-12, 'F': 1e-15}
def _num(v):
    m = re.match(r'\s*([\d.]+)\s*(MEG|[TGKMUNPF])?', v.upper())
    return float(m.group(1)) * _SI.get(m.group(2) or '', 1)
def _eng(x):
    for suf, f in (('MEG', 1e6), ('K', 1e3), ('', 1), ('M', 1e-3), ('U', 1e-6), ('N', 1e-9), ('P', 1e-12)):
        if abs(x) >= f: return ('%.4g' % (x / f)) + suf
    return '%g' % x
def _set_value(t, v):
    """cambia el valor del componente; el rotulo se recentra (7 por caracter, medido en General.CKT)."""
    if t['vrect']:
        cx = (t['vrect'][0] + t['vrect'][2]) // 2; w = 7 * len(v)
        t['vrect'] = [cx - w // 2, t['vrect'][1], cx - w // 2 + w, t['vrect'][3]]
    t['value'] = v
    if t['s'][2].startswith('%DA %1 %2'):  # potenciometro: '10k 40%' -> %DA = 4K, %DB = 6K
        m = re.match(r'\s*(\S+)\s+([\d.]+)%', v)
        if not m: raise ValueError('Potenciometro: usa el formato "10k 40%%" (resistencia y posicion del cursor)')
        r_, f = _num(m.group(1)), float(m.group(2)) / 100
        t['s'][2] = '%%DA %%1 %%2 %s\r\n%%DB %%2 %%3 %s' % (_eng(r_ * f), _eng(r_ * (1 - f)))

def _clean(pts):
    pts = [tuple(int(v) for v in p) for p in pts]; o = [pts[0]]
    for p in pts[1:]:
        if p != o[-1]: o.append(p)
    k = 1
    while k < len(o) - 1:  # quitar puntos colineales
        a, b, c = o[k - 1], o[k], o[k + 1]
        if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]): o.pop(k)
        else: k += 1
    if len(o) == 1: o.append(o[0])
    return o

# ------------------------------------------------------------ verificacion
def _kind_of(c):
    for k, p in PARTS.items():
        if p['tpl']['name'] == c['name']: return k
def net_names(d):
    nm = {2: 'GND'}
    for c in d['comps']:
        if c['name'] in ('Input~', 'Output~'):
            nm[c['arr'][1]] = ''.join(chr(v) for v in c['arr'][10:18]).strip()
    return nm
def bbox(c):
    """rectangulo aproximado (x1,y1,x2,y2) del simbolo, en coordenadas absolutas."""
    x, y, r = c['g'][1], c['g'][2], _rt(c); k = _kind_of(c)
    if c['name'] in ('Input~', 'Output~'):
        a, b = ((-34, -6), (28, 6)) if c['name'] == 'Input~' else ((-35, -6), (27, 6))  # medido en CircuitMaker
    elif k == 'HEX': a, b = (-12, -18), (12, 18)
    elif k == 'ASCII': a, b = (-58, -40), (62, 40)
    elif k == 'GND': a, b = (-6, -2), (6, 6)
    elif k == 'PULSER': a, b = (-16, -14), (18, 14)
    elif k and PARTS[k].get('bbox'): a, b = tuple(PARTS[k]['bbox'][:2]), tuple(PARTS[k]['bbox'][2:])
    elif k and PARTS[k]['pins']:
        pp = [(v[1], v[2]) for v in PARTS[k]['pins'].values()]
        a = (min(p[0] for p in pp) + 6, min(p[1] for p in pp) - 9); b = (max(p[0] for p in pp) - 6, max(p[1] for p in pp) + 9)
        if a[0] >= b[0]: a, b = (-12, a[1]), (12, b[1])
    else: a, b = (-15, -15), (15, 15)
    a, b = rot(*a, r), rot(*b, r)
    return (x + min(a[0], b[0]), y + min(a[1], b[1]), x + max(a[0], b[0]), y + max(a[1], b[1]))

def check(d, overlaps=True):
    probs = []; C = d['comps']
    if overlaps:
        bb = [bbox(c) for c in C]
        for i in range(len(C)):
            for j in range(i + 1, len(C)):
                a, b = bb[i], bb[j]
                if min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1:
                    probs.append('solapamiento visual: %s y %s' % (C[i]['des'], C[j]['des']))
        for t in d['texts']:
            r1 = t['r1']
            for i, a in enumerate(bb):
                if min(a[2], r1[2]) > max(a[0], r1[0]) and min(a[3], r1[3]) > max(a[1], r1[1]):
                    probs.append('texto %r tapa a %s' % (t['text'][:20], C[i]['des']))
    for i, (h, pts) in enumerate(d['wires'], 1):
        for j in range(len(pts) - 1):
            if pts[j][0] != pts[j + 1][0] and pts[j][1] != pts[j + 1][1]: probs.append('cable %d con tramo diagonal' % i)
        for comp, pin, pt in ((h[7], h[0], pts[0]), (h[8], h[1], pts[-1])):
            if not comp: continue
            c = C[comp - 1]
            if pin < len(c['arr']) and c['arr'][pin] != h[2]: probs.append('cable %d: red %d != red del pin %s.%d (%d)' % (i, h[2], c['des'], pin, c['arr'][pin]))
            k = _kind_of(c)
            if k:
                exp = [(c['g'][1] + rot(dx, dy, _rt(c))[0], c['g'][2] + rot(dx, dy, _rt(c))[1])
                       for n, dx, dy in PARTS[k]['pins'].values() if n == pin]
                if exp and all(abs(e[0] - pt[0]) + abs(e[1] - pt[1]) > 3 for e in exp):
                    probs.append('cable %d no llega al pin %s.%d (%s vs %s)' % (i, c['des'], pin, pt, exp[0]))
    seen = {}
    for c in C:
        if c['des'] and c['des'] in seen and c['prefix'] != 'GND': probs.append('designador repetido ' + c['des'])
        seen[c['des']] = 1
    for c in C:
        fam = MODEL_FAMILY.get(_kind_of(c))
        if fam and c['value'] not in known_models(fam):
            probs.append('modelo %r de %s fuera de la lista verificada de %s (usa uno de la lista o confirmalo '
                         'con "ckt.py models")' % (c['value'], c['des'], MODELS[fam][0]))
    return probs

def info(path):
    d = parse(path); nm = net_names(d)
    print('%d componentes, %d cables, %d textos' % (len(d['comps']), len(d['wires']), len(d['texts'])))
    for c in d['comps']:
        k = _kind_of(c); pins = ''
        if k:
            inv = {v[0]: n for n, v in PARTS[k]['pins'].items()}
            pins = ' '.join('%s=%s' % (inv.get(n, n), nm.get(c['arr'][n], c['arr'][n]) if n < len(c['arr']) else '?')
                            for n in sorted(inv))
        lbl = ''.join(chr(v) for v in c['arr'][10:18]).strip() if c['name'] in ('Input~', 'Output~') else ''
        print('  %-7s %-14s (%4d,%4d) r%-3d %s %s' % (c['des'], c['name'], c['g'][1], c['g'][2], _rt(c), lbl, pins))
    probs = check(d); print('Verificacion:', 'OK' if not probs else '')
    for p in probs: print('  -', p)

# ----------------------------------------------------- aprender partes nuevas
def learn(*paths):
    """Aprende de uno o varios .CKT las partes que el skill aun no conoce (o completa las ya aprendidas):
    plantilla exacta y posicion de cada pin que tenga un cable. Con varios archivos vota la posicion mas
    repetida, descarta las copias espejadas (bandera 512) y marca 'aprox' los pines con un solo apoyo fuera
    de un archivo 5.6 (en los ejemplos antiguos ~6% de los extremos quedan corridos 2-3 unidades)."""
    user = json.load(open(USER_PARTS)) if os.path.exists(USER_PARTS) else {}
    by_name = {p['tpl']['name']: k for k, p in PARTS.items()}
    by_name.update({p['tpl']['name']: k for k, p in user.items()})
    tpl, obs, nwires, mirrored, src = {}, {}, 0, 0, {}
    for path in paths:
        try: d = parse(path)
        except Exception as e: print('No se pudo leer %s: %s' % (path, e)); continue
        v56 = d['hdr'][1] == '5.6'; nwires += len(d['wires'])
        for c in d['comps']:
            src.setdefault(c['name'], set()).add(os.path.basename(path))
            if c['flags'][3] < 512 and (c['name'] not in tpl or (v56 and not tpl[c['name']][1])):
                tpl[c['name']] = (c, v56)
        for h, pts in d['wires']:
            for comp, pin, pt in ((h[7], h[0], pts[0]), (h[8], h[1], pts[-1])):
                if not comp: continue
                c = d['comps'][comp - 1]
                if c['flags'][3] >= 512: mirrored += 1; continue
                o = unrot(pt[0] - c['g'][1], pt[1] - c['g'][2], _rt(c))
                e = obs.setdefault(c['name'], {}).setdefault(pin, {}).setdefault(o, [0, False])
                e[0] += 1; e[1] = e[1] or v56
    if not nwires: print('AVISO: no hay cables, asi que no se revela donde esta cada pin.')
    if mirrored: print('(%d extremos de copias espejadas descartados)' % mirrored)
    def vote(pin_obs):
        o, (n, v56) = max(pin_obs.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        return o, (n >= 2 or v56)
    pend = []; nuevos = 0
    for nm_, (c, _) in tpl.items():
        key = by_name.get(nm_)
        if key in BUILTIN and not BUILTIN[key].get('missing'): continue
        names = PIN_NAMES.get(nm_, {}); hid = HIDDEN_PINS.get(nm_, ())
        secs = c['L8'][4] if c['L8'][0] == 65 and c['L8'][5] else 1
        np_ = (len(c['pm']) - 2) // 2 if secs == 1 else 0
        o = {pin: vote(po) for pin, po in obs.get(nm_, {}).items()}
        if key and key in user:  # ya aprendida: completar pines que faltaban
            e = user[key]; add = []; fix = []
            for n, ((dx, dy), firm) in sorted(o.items()):
                nm2 = names.get(n, 'P%d' % n)
                if nm2 not in e['pins']:
                    e['pins'][nm2] = [n, dx, dy]; add.append(nm2)
                    if not firm: e.setdefault('aprox', []).append(nm2)
                elif firm and nm2 in e.get('aprox', []):  # evidencia firme: corrige y confirma
                    if e['pins'][nm2][1:] != [dx, dy]: fix.append('%s %s->%s' % (nm2, e['pins'][nm2][1:], [dx, dy]))
                    e['pins'][nm2] = [n, dx, dy]; e['aprox'].remove(nm2)
            if 'aprox' in e and not e['aprox']: e.pop('aprox')
            if not e['tpl']['des'] and c['des']:  # plantilla sin designador: tomar la que lo tiene
                for f in ('des', 'drect'): e['tpl'][f] = c[f]
            if fix: print('Corregido  %-14s (%s): %s' % (key, nm_, ', '.join(fix)))
            if add or fix: e['bbox'] = auto_bbox(e['tpl'], e['pins'])
            e['missing'] = [m for m in e.get('missing', []) if names.get(m, 'P%d' % m) not in e['pins']]
            if not e['missing']: e.pop('missing')
            if add: print('Completado %-14s (%s): nuevos pines %s' % (key, nm_, ' '.join(add)))
            if e.get('missing'): pend.append((nm_, e['missing']))
            continue
        if not o:
            pend.append((nm_, list(range(1, np_ + 1)))); continue
        key = re.sub(r'[^A-Za-z0-9]', '', nm_).upper() or 'PART'
        while key in PARTS or key in user: key += '_'
        t = json.loads(json.dumps(c)); t['g'][1] = t['g'][2] = 0; t['flags'][3] = 0; t['id'] = [0, 0, 0]
        if secs > 1: t['L8'][5] = 1
        pins = {names.get(n, 'P%d' % n): [n, dx, dy] for n, ((dx, dy), _) in sorted(o.items())}
        aprox = [names.get(n, 'P%d' % n) for n, (_, firm) in sorted(o.items()) if not firm]
        np_ = max([n for n in o] + [np_])
        miss = [n for n in range(1, np_ + 1) if n not in o and n not in hid]
        user[key] = {'tpl': t, 'pins': pins, 'sections': secs, 'npins': np_,
                     'desc': ('aprendido de ' + ', '.join(sorted(src[nm_])))[:70],
                     'bbox': auto_bbox(t, pins)}
        if miss: user[key]['missing'] = miss; pend.append((nm_, miss))
        if aprox: user[key]['aprox'] = aprox
        by_name[nm_] = key; nuevos += 1
        print('Aprendido %-14s (%s): pines %s%s' % (key, nm_, ' '.join(pins), '  [aprox: %s]' % ' '.join(aprox) if aprox else ''))
    json.dump(user, open(USER_PARTS, 'w'), indent=1)
    if pend:
        print('Sin geometria (cablea estos pines en CircuitMaker y vuelve a ejecutar learn):')
        for nm_, ms in pend: print('  %-16s pines %s' % (nm_, ' '.join(map(str, ms))))
    print('%d partes nuevas. Guardado en %s' % (nuevos, USER_PARTS))

def _row(k, p, desc=None):
    """fila de LEARNED para una parte aprendida (None si no se puede representar exacta)."""
    t = p['tpl']; r = lambda v: ' '.join(map(str, v)) if v else ''
    if '|' in ''.join([x or '' for x in t['s']] + [t['A'], t['value'], t['name']]) or t.get('xarr') or t.get('extra'):
        return None
    n = p['npins']; pm = t['pm']; h = (len(pm) - 2) // 2
    pms = ('=%s;%d' % (r(pm[1:1 + h]), pm[-1])) if len(pm) % 2 == 0 and pm[1:1 + h] == pm[1 + h:1 + 2 * h] and h else r(pm)
    st = ' '.join('%d:%d' % (i, v) for i, v in enumerate(t['arr']) if v and not 1 <= i <= n)
    pins = ' '.join(('%d:%d:%d' % tuple(v)) if nm == 'P%d' % v[0] else '%s:%d:%d:%d' % (nm, v[0], v[1], v[2])
                    for nm, v in sorted(p['pins'].items(), key=lambda kv: kv[1][0]))
    row = '|'.join([k, t['name'], '%d %d %d' % (t['g'][0], t['g'][4], t['g'][5]), str(t['flags'][2]), r(t['L8']), t['A'],
                    t['value'], r(t['vrect']), t['des'], r(t['drect']), t['s'][0], r(t.get('srect')), t['s'][1],
                    t['s'][2].replace('\r\n', '\\n'), t['s'][4], t['s'][5], t['prefix'], pms, st, pins,
                    r(p.get('hidden')), desc or p.get('desc', '')])
    b = _mk_learned(row)[k]; a = json.loads(json.dumps(t)); a['g'][1:4] = [0, 0, 0]; a['flags'][3] = 0
    for i in range(1, min(n + 1, len(a['arr']))): a['arr'][i] = 0
    a['dbl'] = '0 0'; a['id'] = [0, 0, 0]; a['end'] = '0'
    ok = a == b['tpl'] and b['pins'] == p['pins'] and b['sections'] == p.get('sections', 1)
    return row if ok else None

def export_builtin(out):
    """Escribe las partes aprendidas (sin pines pendientes) listas para pegar en el skill: filas para LEARNED
    y, para las que no encajan en ese formato, un JSON para agregar a BUILTIN."""
    user = json.load(open(USER_PARTS)) if os.path.exists(USER_PARTS) else {}
    rows, js = [], {}
    for k, p in user.items():
        if p.get('missing'): continue
        row = _row(k, p)
        if row: rows.append(row)
        else: js[k] = p
    with open(out, 'w') as f:
        f.write('# Filas para LEARNED\n' + '\n'.join(rows) + '\n')
        if js: f.write('# JSON para agregar a BUILTIN\n' + json.dumps(js, separators=(',', ':'), ensure_ascii=False) + '\n')
    print('Escrito', out, '(%d filas, %d en JSON)' % (len(rows), len(js)))

# ------------------------------------------------------------ modelos SPICE
def read_models(folder):
    """lee la carpeta MODELS de CircuitMaker: {familia: set(valores validos)}"""
    files = {f.lower(): os.path.join(folder, f) for f in os.listdir(folder)}; out = {}
    for fam, (fn, pre, _, _) in MODELS.items():
        p = files.get(fn.lower())
        if p:
            t = open(p, 'rb').read().decode('latin-1')
            out[fam] = {n[1:].rstrip('~') for n in re.findall(r'^\.(?:PARAM|MODEL|SUBCKT)\s+(\S+)', t, re.M | re.I)
                        if n[0].upper() == pre}
    return out

def models_cmd(folder, arg=None):
    """sin arg: modelos por familia; con un .CKT: valida sus valores; con texto: busca modelos que lo contengan."""
    allm = read_models(folder)
    if not arg:
        for fam, st in allm.items(): print('%-9s %-14s %4d modelos' % (fam, MODELS[fam][0], len(st)))
    elif arg.lower().endswith('.ckt'):
        bad = 0
        for c in parse(arg)['comps']:
            fam = MODEL_FAMILY.get(_kind_of(c))
            if fam in allm:
                ok = c['value'] in allm[fam]; bad += not ok
                print('  %-6s %-9s %-12s %s' % (c['des'], fam, c['value'], 'OK' if ok else 'NO EXISTE en ' + MODELS[fam][0]))
        print('Modelos:', 'todos existen' if not bad else '%d no existen' % bad)
    else:
        for fam, st in allm.items():
            hit = sorted(v for v in st if arg.upper() in v.upper())
            if hit: print('%-9s %s' % (fam, ' '.join(hit[:40]) + (' ...' if len(hit) > 40 else '')))

# ------------------------------------------------------------ vista previa
def render(path, out, scale=2):
    from PIL import Image, ImageDraw, ImageFont
    d = parse(path) if isinstance(path, str) else path
    xs, ys = [], []
    for c in d['comps']: xs.append(c['g'][1]); ys.append(c['g'][2])
    for h, pts in d['wires']:
        for p in pts: xs.append(p[0]); ys.append(p[1])
    for t in d['texts']: xs += [t['r1'][0], t['r1'][2]]; ys += [t['r1'][1], t['r1'][3]]
    x0, y0 = min(xs) - 60, min(ys) - 60; W, H = max(xs) - x0 + 60, max(ys) - y0 + 60
    im = Image.new('RGB', (int(W * scale), int(H * scale)), 'white'); g = ImageDraw.Draw(im)
    try: F = ImageFont.truetype('DejaVuSansMono.ttf', int(7 * scale)); FS = ImageFont.truetype('DejaVuSansMono.ttf', int(5 * scale))
    except Exception: F = FS = ImageFont.load_default()
    P = lambda x, y: ((x - x0) * scale, (y - y0) * scale)
    blue, red = (40, 40, 170), (200, 30, 30)
    for c in d['comps']:
        x, y, r = c['g'][1], c['g'][2], _rt(c); k = _kind_of(c)
        B = bbox(c)
        if c['name'] in ('Input~', 'Output~'):
            g.rectangle([P(B[0], B[1]), P(B[2], B[3])], outline=blue)
            lbl = ''.join(chr(v) for v in c['arr'][10:18]).strip()
            if r in (90, 270):
                for n_, ch in enumerate(lbl): g.text(P(B[0] + 3, B[1] + 2 + 6 * n_), ch, fill=blue, font=FS)
            else: g.text(P(B[0] + 2, B[1] + 1), lbl, fill=blue, font=F)
            continue
        if k and PARTS[k]['pins']:
            if k == 'GND': g.polygon([P(x - 6, y), P(x + 6, y), P(x, y + 6)], outline=blue); continue
            g.rectangle([P(B[0], B[1]), P(B[2], B[3])], outline=blue)
            if k == 'HEX': g.text(P(x - 4, y - 8), '8', fill=red, font=F)
            for n, (num, dx, dy) in PARTS[k]['pins'].items():
                rx, ry = rot(dx, dy, r)
                if k not in ('HEX', 'GND'): g.text(P(x + rx * 0.72 - 6, y + ry - 3), n, fill=(90, 90, 90), font=FS)
        else:
            g.rectangle([P(B[0], B[1]), P(B[2], B[3])], outline=red)
        g.text(P(B[0], B[1] - 8), c['des'] + (' ' + c['value'] if c['value'] and c['value'] != '1MEG' else ''), fill=(0, 0, 0), font=FS)
    for h, pts in d['wires']:
        g.line([P(*p) for p in pts], fill=blue, width=max(1, scale // 2))
        for p in (pts[0], pts[-1]): g.ellipse([P(p[0] - .8, p[1] - .8), P(p[0] + .8, p[1] + .8)], fill=red)
    for t in d['texts']:
        g.rectangle([P(t['r1'][0], t['r1'][1]), P(t['r1'][2], t['r1'][3])], outline=(200, 200, 200))
        g.multiline_text(P(t['r2'][0], t['r2'][1]), t['text'].replace('\r\n', '\n'), fill=(0, 0, 0), font=F, spacing=int(3 * scale))
    im.save(out); return out

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__)
    elif a[0] == 'parts':
        for k, p in PARTS.items():
            dip = p['tpl']['s'][5].startswith(('DIP', 'SIP')) and p.get('sections', 1) == 1  # pin fisico = pm[num]
            pins = ' '.join(n + ('(%s)' % p['tpl']['pm'][v[0]] if dip and v[0] < len(p['tpl']['pm']) else '')
                            for n, v in p['pins'].items())
            print('%-8s %-16s secciones=%d  pines: %s\n         %s%s' % (k, p['tpl']['name'], p.get('sections', 1), pins,
                  p.get('desc', ''), '  [aprox: %s]' % ' '.join(p['aprox']) if p.get('aprox') else ''))
    elif a[0] == 'info': info(a[1])
    elif a[0] == 'render': print(render(a[1], a[2] if len(a) > 2 else a[1] + '.png'))
    elif a[0] == 'learn': learn(*a[1:])
    elif a[0] == 'export': export_builtin(a[1] if len(a) > 1 else 'nuevas.txt')
    elif a[0] == 'models': models_cmd(a[1], a[2] if len(a) > 2 else None)
    elif a[0] == 'roundtrip':
        b = open(a[1], 'rb').read(); ok = serialize(parse(b)) == b
        print('identico' if ok else 'DIFERENTE (normal si el archivo tiene texto UTF-8 dañado)')

