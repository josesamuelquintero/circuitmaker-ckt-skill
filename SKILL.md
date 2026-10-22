---
name: "circuitmaker-ckt"
description: "Genera, lee, verifica y previsualiza archivos .CKT de CircuitMaker 2000 con Python: CI digitales, partes analógicas, fuentes e instrumentos listos para simular."
---

# CircuitMaker 2000 · generador de archivos .CKT

Este skill produce archivos `.CKT` (formato "CircuitMaker Text 5.6") que se abren y simulan directamente en CircuitMaker 2000. El formato se decodificó por ingeniería inversa de tres archivos reales de José:

- **p1**: contador ASCII 0-127 con 74LS93.
- **p2**: contador de 16 bits con 4040/CD4520/4518.
- **General.CKT**: 37 símbolos analógicos y de instrumentación, con cada pin cableado a una etiqueta. José abrió en CircuitMaker un catálogo generado con las 36 partes nuevas y todos los cables llegaron a su pin.

- **Ejemplos de CircuitMaker** (82 archivos, versiones 4 a 5.6): de ellos salieron 83 partes más (tabla `LEARNED`). José abrió dos catálogos generados con todas, con una etiqueta en cada pin, y todos los cables llegaron a su pin.

Los modelos SPICE salen de la carpeta `MODELS` de su CircuitMaker 2000 (448 archivos).

El lector reescribe p1 y General.CKT byte por byte idénticos. En General.CKT los 92 extremos de cable caen exactos en el pin de su etiqueta, así que la geometría de pines aprendida es exacta.

## Flujo de trabajo

1. El script vive en `scripts/ckt.py`, dentro de la carpeta de este skill. **No lo reescribas ni lo resumas**: la tabla de partes JSON y las tablas `ANALOG` y `LEARNED` son exactas. Úsalo directamente desde esa ruta (o cópialo tal cual al directorio de trabajo). Si el usuario adjunta su propio `ckt.py`, úsalo. Requiere Python 3; `Pillow` solo hace falta para `render`.
2. Escribe un script de construcción (`from ckt import Circuit`, con `scripts/` en `sys.path`) que coloque componentes, conexiones y texto.
3. `c.save('nombre.CKT')` escribe el archivo y ejecuta la verificación automática. **Corrige todos los `AVISO:`** (solapamientos, cables que no llegan al pin) moviendo componentes antes de entregar.
4. Genera la vista previa con `python ckt.py render nombre.CKT prev.png`, mira la imagen y ajusta la distribución si se ve apretada.
5. Si el circuito se va a simular, revisa que no haya avisos de `modelo` (ver Modelos SPICE).
6. Entrega el `.CKT` (y opcionalmente el PNG). Aclara que la vista previa es aproximada y que la prueba final es abrirlo en CircuitMaker.
7. Si en la sesión se aprendieron partes nuevas (`learn`), propone actualizar el skill:
   - ejecuta `python ckt.py export nuevas.txt`;
   - añade sus filas al final de `LEARNED` en `scripts/ckt.py`;
   - si hay JSON, agrégalo a `BUILTIN`.

   Sin este paso, lo aprendido se pierde al terminar la conversación.

Para inspeccionar un .CKT existente usa `python ckt.py info archivo.CKT`, que lista componentes, pines→redes y problemas. `python ckt.py parts` lista las partes disponibles.

## API

```python
from ckt import Circuit
c = Circuit()
v  = c.add('PULSER', 80, 60)                 # add(tipo, x, y, rot=0, section=None, chip=None, des=None, value=None)
c.net(v['Q1'], 'CLK')                        # etiqueta de red automática (max 8 caracteres)
u  = c.add('74LS93', 300, 160)
c.wire(u['Q0'], u['CP1'])                    # cable directo pin a pin (enrutado ortogonal automático)
c.wire(u['MR1'], u['MR2'])
c.net(u['MR1'], 'GND')                       # 'GND' coloca un símbolo de tierra (red 2)
c.nets(u, {'CP0': 'CLK', 'Q0': 'B0', 'Q1': 'B1', 'Q2': 'B2', 'Q3': 'B3'})
g1 = c.gate('4081', 420, 430, 'U6', 'A')     # compuertas: mismo chip='U6' => mismo CI (U6A, U6B...)
g2 = c.gate('4081', 420, 560, 'U6', 'B')
d  = c.add('HEX', 500, 150)                  # display hex: pin '1' = LSB ... '4' = MSB
r  = c.add('RESISTOR', 300, 400, value='4.7k')
q  = c.add('NPNTRANSB', 450, 460, value='2N3904');  c.nets(q, {'B': 'BASE', 'C': 'COL', 'E': 'GND'})
c.text(40, 20, 'Titulo', size=16, bold=True) # bloque de texto (Courier New); '\n' para saltos
c.save('salida.CKT')
```

- **Conexiones**: la forma robusta (la que usa José) es con etiquetas de red: todos los pines con el mismo nombre quedan en la misma red.
  - `c.net()` agrupa las etiquetas por lado del componente y las abre en abanico (separación 12) sin cruces.
  - Los pines de una columna lateral de CI (4 o más pines con la misma x) siempre reciben la etiqueta al costado.
  - Usa `c.wire()` solo para lazos cortos en el mismo chip (Q0→CP1, MR1↔MR2) o entre chips vecinos. Admite `via=[(x,y),...]` para una ruta manual (solo tramos horizontales y verticales).
- **Pin físico:** en CI de una sección (DIP/SIP) `u['#7']` es el pin 7 del encapsulado. Úsalo con la hoja de datos cuando los pines se llaman `P1..Pn` (74LS47: `u['#7']` = entrada A, `u['#13']` = segmento a). `python ckt.py parts` muestra cada `Pn(físico)`.
- Un pin puede tener un cable y además una etiqueta (queda bien). No pongas dos etiquetas en el mismo pin.
- Los pines sin conexión se dejan así. CircuitMaker les asigna una red propia y el generador lo imita.
- Coordenadas en unidades de CircuitMaker (y crece hacia abajo). Rejilla de pines de 9 en los CI.
- `rot` admite 0/90/180/270, pero prefiere 0 para las partes. Las etiquetas arriba y abajo se escriben como las guarda CircuitMaker (90, y 782 = 270 + bandera 512).
- `value=` cambia el valor del componente:
  - `'10k'`, `'100nF'`, `'12V'`, etc.
  - En partes con modelo (diodos, LED, transistores, puente, diodos dobles), el valor es el nombre del modelo SPICE. Sin `value=`, el generador pone el modelo por defecto válido de la familia (ver Modelos SPICE).
  - En potenciómetros usa `'10k 25%'`: el netlist se recalcula (2.5K y 7.5K).
  - El rótulo se recentra a 7 unidades por carácter.
  - No sirve para el Signal Gen, porque su forma de onda vive en otro bloque; se configura en CircuitMaker.

## Partes disponibles (pines)

Digitales (p1, p2):

| Tipo | Símbolo CM | Pines |
|---|---|---|
| PULSER | Pulser~ | Q1 (salida de reloj) |
| HEX | Hex Display~ | 1 2 3 4 (1 = LSB). Para un bit: pin 1 = bit, pin 2 = GND, 3-4 libres |
| ASCII | Ascii Display~ | 1..7 (1 = bit0) y CP (reloj/strobe) |
| 74LS93 | 74LS93 | MR1 MR2 CP0 CP1 Q0 Q1 Q2 Q3 |
| 4071 / 4081 | OR / AND 2 entradas, 4 secciones (A-D) | A B Y |
| 4040 | contador binario 12 bits | CP MR Q0..Q11 |
| CD4520 | doble contador binario | CP0A CP1A MRA Q0A..Q3A, CP0B CP1B MRB Q0B..Q3B |
| 4518 | contador BCD, 2 secciones (A-B) | CP0 CP1 MR Q0 Q1 Q2 Q3 |
| IN / OUT / GND | Input~ / Output~ / Ground~ | los coloca `c.net()` automáticamente |

En 4518/CD4520, CP0 es el reloj por flanco de subida (con CP1 en alto) y CP1 el reloj por flanco de bajada (con CP0 a GND). Así cuenta el p2.

Analógicas e instrumentos (General.CKT, tabla `ANALOG`). Los offsets son respecto al origen de la parte, con rotación 0:

| Tipo | Símbolo CM | Pines (offset) |
|---|---|---|
| RESISTOR, RESISTORA | Resistor~, Resistor:A~ (valor `1k`) | 1 (-18,0) · 2 (18,0) |
| SEMIRESISTOR, SEMIRESISTORA | SemiResistor~, SemiResistorA~ (modelo `RESISTOR`) | 1 (-18,0) · 2 (18,0) |
| VARRESISTOR, VARRESISTORA | potenciómetro (`10k 40%`) | 1 (-18,0) · W cursor (-2,-12) · 3 (18,0) |
| CAPACITOR, SEMICAPACITOR | Capacitor~, SemiCapacitor~ | 1 (-9,0) · 2 (9,0) |
| POLARCAP | Polar Cap~ | + (-11,0) · - (6,0) |
| VARCAPACITOR | Var Capacitor~ | 1 (-14,0) · 2 (14,0) |
| INDUCTOR, VARINDUCTOR | Inductor~, Var Inductor~ | 1 (-18,0) · 2 (18,0) |
| COIL3T / COIL5T | Coil 3T~ / Coil 5T~ | 1 (-20,0) · 2 (20,0) / 1 (-26,0) · 2 (26,0) |
| DIODE, ZENERDIODE | Diode~, Zener Diode~ | A (-10,0) · K (10,0) |
| SCHOTTKY, VARACTOR, VARACTORA | Schottky~, Varactor~, Varactor:A~ | A (-11,0) · K (12,0) |
| LED | LED~ (modelo `LED1`) | A (0,-10) arriba · K (0,10) abajo |
| DIODEAKA | Diode AKA~ (cátodo común) | A1 (-31,-3) · K (0,12) · A2 (31,-3) |
| DIODEKAK | Diode KAK~ (ánodo común) | K1 (-31,-3) · A (0,12) · K2 (31,-3) |
| DIODEACK | Diode ACK~ (dos en serie) | A (-31,-3) · C punto medio (0,12) · K (31,-3) |
| ZENERAKA | Zener AKA~ (cátodo común) | A1 (-31,0) · K (0,15) · A2 (31,0) |
| FWBRIDGE | FW Bridge~ (puente) | - (-30,-4) izq · AC1 (2,-36) arriba · + (34,-4) der · AC2 (2,28) abajo. Confirmado con el subcircuito `BRIDGE` (pin 1 ánodos, pin 3 cátodos); el comentario "AC1 AC2 V+ V-" de FWBRIDGE.SUB está mal |
| NPNTRANSB, NPNTRANSC, PNPTRANSB, PNPTRANSC | transistores (`NPN` / `PNP`) | C (5,-18) · B (-18,0) · E (5,18) |
| BATTERY | Battery~ (`10V`) | + (0,-13) · - (0,11) |
| V | +V (fuente a tierra, `10V`) | V (0,9) |
| VSOURCE, ISOURCE | V Source~, I Source~ | + (0,-21) · - (0,21) |
| SIGNALGEN | Signal Gen~ (seno 1 kHz, ±1 V) | + (31,-5) · - (31,5) |
| MULTIMETER | Multimeter~ (designador MM) | + (-25,23) · - (25,23); los pines 2-3 del netlist no tienen terminal |
| DATASEQ | Data Seq~ (fuente digital) | salidas `8`..`1` como las rotula el símbolo, de arriba (32,-27) abajo (32,36), de 9 en 9 · CP1 (-32,27) · CP2 (-38,36, invertida) |

Notas sobre estas partes:

- **Nombres de pin:** A/K, C/B/E, +/- y W salen del netlist SPICE de cada símbolo (D ánodo cátodo, Q colector base emisor, V n+ n-, potenciómetro R 1-2 y 2-3). Los del capacitor polarizado, el puente, los diodos dobles, el multímetro y el Data Seq se confirmaron viendo los símbolos en CircuitMaker.
- **Diode~:** su plantilla trae el mapa de pines `-54 -44` y el encapsulado `DOIODE0.4`, tal como lo guarda el CircuitMaker de José.
- **LED~:** guarda una sola red en su arreglo aunque tenga 2 pines. Es normal.

Partes de los ejemplos de CircuitMaker (tabla `LEARNED`), todas verificadas en un catálogo. Pines `P1..Pn` en el orden del símbolo; en los CI usa el pin físico (`u['#n']`) con la hoja de datos:

| Grupo | Tipos |
|---|---|
| Compuertas (secciones A-D, pines P1.. entradas y la última salida) | 2INAND (74LS08), 2INOR (74LS32), 2INNAND (74LS00), 2INNOR y 2INNORDM (74LS02), 3INNAND (74LS10), 3INNOR (4025), 4INOR (4072), INVERTER (4069), 4011, 4093 (Schmitt). 74112 (JK, 2 secciones) tiene 7 pines: mira su mapa físico con `parts` |
| CI digitales de una sección | 74LS47 y 74LS48 (BCD a 7 segmentos, ánodo/cátodo común), 74LS75 (latches), 74LS85 (comparador), 74LS139 (decodificador 2 a 4), 74LS164 (registro serie-paralelo), 74LS168 (contador década up/down), 74LS173 (registro 3 estados), 4017 (contador Johnson), QUADDFLOP, 555TIMER, ADC0800, ADC8, DAC8 |
| Entradas y salidas digitales | LOGICSWITCH, LOGICDISPLAY, HEXKEY, ASCIIKEY, 4X4SWITCH, CA7SEG y CC7SEG (7 segmentos; P9 = común arriba) |
| Analógicas activas | OPAMP5 (UA741), OPAMP7 (LM301A), NPNTRANS (2N2222A), NJFET, NEMOS3TA, PEMOS3TA, NMOSFET3T, SCR, TRIACB, OPTOISOLATOR, REGULATOR3, TRIODE, TETRODE, MC1496, PLL, VCO, FVSOURCE |
| Fuentes controladas y funciones | IVSOURCE (H), VISOURCE (G), NLISOURCE, NLVSOURCE, VMATH1, VMATH2 |
| Electromecánicas y pasivas | SPSTSWITCH, SPDTSWITCH, NOPUSHBUTTON, SPDTRELAY, RELAYCOILA, CONTACTSD, CONTACTSE, SOLENOID, LAMP, DCMOTOR, SPEAKER, PIEZOBUZZER, FUSE, CRYSTAL, TRANS2, TRANS3, XFMR, COAX, TWISTEDPAIR, LOSSLESSLINE, SIP2, TERMINAL, STOPLIGHT |
| Directivas y sondas | DOTIC (.IC, valor = voltaje inicial), NODESET (.NODESET), SCOPE (punto de sonda) |

- **74LS74:** la de los ejemplos es solo un dibujo, sin línea de simulación ni designador. Para un flip-flop D que simule usa QUADDFLOP o pide a José un 74LS74 de su biblioteca cableado.
- **CONTACTSD / CONTACTSE:** un pin no se dibuja (el enlace con la bobina; no está en su línea SPICE). Solo se conectan P1 y P3 (D) o P1 y P2 (E).
- **Valores:** cada parte trae el valor de su ejemplo (2N2222A, UA741, IRFP240…). Si cambias un modelo, confírmalo con `models`.

## Modelos SPICE

El valor de una parte con modelo es su nombre SPICE. CircuitMaker busca `<prefijo><valor>` en el archivo de la familia: `D` diodos, `Q` transistores, `X` subcircuitos (diodos dobles, puente), `R`, `C`. La `~` del archivo marca el modelo por defecto (`QNPN~` → valor `NPN`). Si no existe, falla al simular con "MODEL DSCHOTTKY is not in the selected model file". Así pasó con el valor `SCHOTTKY` que traía la plantilla.

| Familia (partes) | Archivo | Por defecto | Otros verificados en la instalación de José |
|---|---|---|---|
| DIODE | Diode.mod (572) | `DIODE` | 1N4148 1N914 1N4448 1N4001 1N4002 1N4004 1N4007 1N5400 1N5408 1N34 |
| SCHOTTKY | SCHOTTKY.MOD (185) | `SKYDIODE` | 11DQ03 11DQ04 11DQ06 10BQ040 30BQ040 MBR1045 1N5828 |
| ZENERDIODE | ZENER.MOD (76) | `ZENER` (10 V) | 1N746 1N750 1N751 1N752 1N758 1N759 (500 mW) · 1N4728 (3.3 V) … 1N4733 (5.1 V) … 1N4742 (12 V) 1N4744 1N4747 (1 W) |
| VARACTOR, VARACTORA | VARACTOR.MOD (28) | `FMMV109` (no trae defecto; elegido por el skill) | BBY31 BBY40 FMMV105G FMMV2101 FMMV2105 FMMV2109 ZC830A ZC836A |
| LED | LED.MOD (4) | `LED1` rojo 1.7 V | LED0 infrarrojo · LED2 rojo/verde/amarillo 2.1 V · LED3 azul 3.4 V |
| NPN* | NPN.MOD (449) | `NPN` | 2N3904 2N2222 2N2222A 2N4401 2N5551 BC547A/B/C BC548A/B/C BC337-25 2N3055 MPSA42 |
| PNP* | PNP.MOD (366) | `PNP` | 2N3906 2N2907 2N2907A 2N4403 2N5401 BC557 BC557B BC327 BC328 |
| SEMIRESISTOR, SEMICAPACITOR | RESISTOR.MOD, CAP.MOD | `RESISTOR`, `CAP` | |
| DIODEAKA / DIODEKAK / DIODEACK | Diodeaka.sub (215) / Diodekak.sub (5) / Diodeack.sub (8) | `BAV70` / `BAW56` / `BAV99` (no traen defecto) | BAV74 BAV170 MMBD6100 / BAW156 MMBD2835 / BAV199 MMBD7000 |
| ZENERAKA | Zeneraka.sub (74) | `DZ23C2V7` | DZ23C3V3 DZ23C5V1 DZ23C6V2 DZ23C10 DZ23C12 DZ23C15 |
| FWBRIDGE | FWBRIDGE.SUB (53) | `BRIDGE` | MDA2500 DF005 DF01 DF02 DF04 DF06 DF08 DF10 |

- **Sin `value=`:** el generador pone el modelo por defecto de la tabla (Schottky, varactores y diodos dobles traían valores que no existen).
- **Avisos:** `check` avisa si un valor no está en la tabla. Puede existir igual en el archivo; antes de usarlo, confírmalo.
- **Comando `models`:** si la carpeta MODELS está disponible (por ejemplo, desde Claude Code en la computadora de José, en `C:\Program Files\CircuitMaker 2000\MODELS`):
  - `python ckt.py models CARPETA` lista las familias;
  - `python ckt.py models CARPETA 3904` busca un modelo;
  - `python ckt.py models CARPETA archivo.CKT` valida todos los valores de un circuito.
- **Ausentes en esta instalación:** no inventes modelos "conocidos" sin confirmarlos. Estos no están: 1N5817/1N5818/1N5819, BAT54, BAT85, TIP31/TIP32, TIP120, BD139/BD140, BC547 y BC548 sin letra (usa BC547B, BC548B), 1N4733A y 1N4742A (usa 1N4733, 1N4742).

## Partes nuevas

1. Pide al usuario un .CKT guardado en CircuitMaker con la parte y **cada pin con un cable**. Basta un cable corto de cada pin a una etiqueta o a tierra; no importa que el circuito no tenga sentido eléctrico.
2. Ejecuta `python ckt.py learn archivo.CKT [otro.CKT ...]`. Lee archivos de las versiones 4 a 5.6 (77 de los 82 ejemplos se reescriben idénticos). El comando:
   - copia la plantilla exacta y la geometría a `ckt_parts.json`;
   - aplica los nombres de `PIN_NAMES` (si no hay, quedan `P1..Pn`);
   - lista los pines que siguieron sin cable. Un segundo archivo con esos pines los completa;
   - con varios archivos vota la posición más repetida de cada pin. En los ejemplos antiguos (versión ≤ 5.5) ~6% de los extremos de cable quedan corridos 2-3 unidades, así que un pin visto una sola vez fuera de un archivo 5.6 queda marcado `aprox`; un archivo 5.6 posterior lo confirma;
   - descarta las copias con la bandera 512 en la rotación: en partes asimétricas es un espejo horizontal (en las etiquetas, 782 es solo su forma de guardar 270).
   Antes de incorporar partes al skill, genera un catálogo con una etiqueta en cada pin y pide al usuario que confirme en CircuitMaker que todos los cables llegan.
3. La clave de la parte es el nombre del símbolo sin signos (`Resistor~` → `RESISTOR`). `python ckt.py parts` las muestra.

Nunca inventes plantillas ni posiciones de pines que no hayas visto en un archivo real. Una parte sin ningún cable no sirve: CircuitMaker guarda su arreglo de redes truncado y no revela dónde están los pines.

## Guía de distribución (evita los AVISOS)

- CI de 74LS93/4518: deja ~120 de separación vertical entre chips y ~90 libres a cada lado para las etiquetas.
- Displays HEX con los 4 pines etiquetados: separación horizontal ≥ 60 (con 1-2 pines, ≥ 55). Las etiquetas quedan ~50 debajo del display.
- ASCII: ocupa ~120×80; sus etiquetas quedan ~70 a la izquierda.
- Etiquetas: el cuerpo mide ~62 × 12 (medido en CircuitMaker). Cada etiqueta ocupa ~78 hacia fuera desde el pin: 10 de cable, 6 de punta y 62 de cuerpo.
- Partes analógicas con etiquetas en todos los pines: una rejilla de 240 × 240 no da avisos y se ve limpia en CircuitMaker (probado con las 36). Con 190 × 170 las etiquetas se montaban.
- Textos: ancho ≈ 8 por carácter (tamaño 13), alto ≈ 16 por línea + 28. Colócalos fuera del área del circuito (p. ej. a la derecha, como en p1).
- Prefiere texto sin tildes (como p1). Si las usas, se codifican en cp1252, que CircuitMaker muestra bien.

## Especificación del formato (referencia)

- **Codificación:** archivo de texto ANSI (cp1252) con fin de línea `CRLF`.
  - Las cadenas son `N texto`, con N = longitud en bytes; `0` = cadena vacía.
  - Un salto dentro de una cadena cuenta como 2 bytes (`\r\n`) y se escribe en disco como `\r\r\n`.
- **Versiones:** la 5.6 trae `Probes: N` en la línea 3 (y N×3 líneas de sondas). Las versiones 4-5.5 no; su cabecera termina 6 líneas después de la línea `\d{6,} \d+`. Números con decimales (`0.1`, `1e+06`) se conservan como texto.
- **Estructura general:** cabecera de 29 líneas (versión, ajustes de simulación, zoom, BOM) → número de componentes → bloques de componentes → número de cables → cables → número de textos → textos → cola fija de ajustes de análisis.
- **Bloque de componente**, en orden:
  1. `nombre`
  2. `devid x y 0 n m`
  3. arreglo de n+1 enteros, 10 por línea: `[0|10, red_pin1, red_pin2, …, estado…]`. En Input~/Output~ las posiciones 10-17 son el texto de la etiqueta en ASCII rellenado con 32; en Multimeter~ dicen `NO DATA`. En el Data Seq el símbolo rotula cada salida con su pin físico del SIP10, así que el pin 1 del netlist es el rotulado `8`.
  4. bloques extra: un conteo k seguido de k enteros, repetido hasta un `0`. Casi siempre es solo `0`; Signal Gen~ trae 20 parámetros de la onda.
  5. `0 0 flags rotación`. La rotación puede llevar la bandera 512 (782 = 270).
  6. valor (+ rect) y designador (+ rect)
  7. 6 cadenas: ?, pinout `DVCC=…`, netlist SPICE, ?, `type:digital` o `type:source …`, encapsulado
  8. N · línea vacía · mapa de pines (N+1 enteros)
  9. `L8 0 0 x nsecc secc paquete 0` (L8 = 65 en CI digitales; en analógicas, una letra ASCII de tipo: 82 R, 67 C, 76 L, 68 D, 100 d zener, 88 X subcircuito, 81 Q npn, 113 q pnp, 86 V, 73 I; x = 512 en partes conectadas)
  10. prefijo (`U`, `T`, `DISP`, `GND`, `V`, `R`, `C`, `L`, `D`, `Q`, `Vs`, `Is`, `DS`)
  11. `id 0 0` · `2` · `dobles` · `0`
  12. líneas propias de algunos símbolos (Data Seq~ añade una línea con su patrón de datos).
- **Partes sin conexión:** CircuitMaker guarda un arreglo de redes truncado (`n` = 1, `0 0`); con conexiones el arreglo tiene una red por pin (salvo LED~, que guarda una).
- **Redes:** 2 = GND; el resto desde 3. Las etiquetas con el mismo texto comparten red. Cada pin guarda su número de red, y cada cable también. CircuitMaker recalcula las redes al abrir: General.CKT trae todos los cables y etiquetas con red 0 y abre bien. Aun así, el generador escribe redes coherentes.
- **Cable:** `pinA pinB red 0 0 flags 0 compA compB cableA cableB npuntos` + puntos.
  - Los índices de componente y cable empiezan en 1. comp=0 y cable≠0 indica una unión en T sobre otro cable.
  - El primer punto es el pin exacto de compA y el último el de compB. Solo hay tramos ortogonales; los tramos de longitud 0 son válidos.
- **Texto:** LOGFONT (`-13 0 0 0 400 0 0 0 0 3 2 1 49`), fuente, `0 0 0 longitud`, rect exterior, rect interior, cadena.

## Código

El script completo está en `scripts/ckt.py` (no se incluye aquí para no gastar contexto). Comandos del CLI: `parts`, `info`, `render`, `learn`, `export`, `models`, `roundtrip`.
