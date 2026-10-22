# circuitmaker-ckt

Skill de Claude para generar, leer, verificar y previsualizar archivos `.CKT` de **CircuitMaker 2000** con Python: circuitos integrados digitales, partes analógicas, fuentes e instrumentos listos para simular.

El formato ("CircuitMaker Text 5.6") se decodificó por ingeniería inversa a partir de archivos reales, y las partes generadas se validaron abriéndolas en CircuitMaker.

## Contenido

- `SKILL.md`: instrucciones del skill (flujo de trabajo, API, tablas de partes, modelos SPICE, formato).
- `scripts/ckt.py`: lector, generador, verificador y vista previa de `.CKT` (Python 3; Pillow solo para `render`).

## Uso

Copia `SKILL.md` y la carpeta `scripts/` en una carpeta `circuitmaker-ckt/` dentro de tu directorio de skills de Claude y pídele a Claude que genere un circuito en formato `.CKT`.

## Autor

José Quintero ([@josesamuelquintero](https://github.com/josesamuelquintero))

## Licencia

MIT. Ver `LICENSE`.
