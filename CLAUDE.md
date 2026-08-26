# Gestión de información de equipos

Sistema web de inventario, mantenimiento y localización de equipo médico del
Hospital Galenia. Flask + pyodbc + SQL Server, plantillas Jinja2.

**Este repo es el entorno de PRUEBAS.** Producción corre sobre Apache, con su
propia copia del proyecto y una base de datos más actualizada.

## Reglas duras

1. **No modificar `app.py`, `config.py` ni `database/db.py`.** Producción tiene
   sus propias versiones con mejores prácticas ya aplicadas; copiar las de aquí
   rompe el despliegue. Todo cambio se diseña para caber en `routes/`, `models/`
   y `templates/`, que sí son portables. Si algo solo se arregla en esos tres
   archivos, no lo hagas: documéntalo como pendiente.
   Y si aun así hay que tocar `app.py`, **avísalo de forma destacada**, no
   enterrado en una lista.

2. **Los templates se editan solo con Edit/Write.** Son UTF-8 sin BOM con
   acentos y cajas `═══`; un round-trip `Get-Content | Set-Content` en
   PowerShell 5.1 los deja doble-codificados en silencio.

3. **El control de acceso va en el decorador `@requiere_rol(...)` de cada ruta**,
   nunca en un `if` dentro del cuerpo. Así la matriz completa se audita
   recorriendo `app.url_map`, y una ruta nueva sin decorador aparece marcada.

4. **Correr siempre con el venv:** `../env/Scripts/python.exe`. El Python del
   PATH tiene otras versiones de las librerías (WeasyPrint 68.1 vs 52.5) y
   engaña al medir.

## Mapa

```
app.py                  factory + blueprints + CSRF + APScheduler   [NO TOCAR]
config.py, database/db.py                                           [NO TOCAR]
routes/       5 blueprints: admin, equipos, ble, mantenimientos, auth
models/       clases con @classmethod que reciben `db`
models/entities/decorators.py   roles y @requiere_rol — fuente única de verdad
templates/    base.html (sistema visual + nav) · Admin/ UserC/ ble/ auth/
database/sql/ scripts de esquema fechados
```

## Roles

`Usuario` (1, solo consulta) → `Biomedico` (2, todo lo operativo) →
`Administrador` (3, usuarios y acciones destructivas). Jerárquico. Se guardan en
BD **sin acento** y se muestran con acento vía `etiqueta_rol()`. Un `Permiso`
desconocido da nivel 0: se deniega todo (fail-closed, intencional).

En plantillas: `{% if puede(ROL_BIOMEDICO) %}`.

**Excepción:** `/Catalogo/*` y `/mantenimientos/<numero_inventario>` son
**públicas por diseño** — son las URL que abre un chip NFC al escanearse. Ahí una
ruta sin decorador queda expuesta sin que nada lo señale. Ver `rutas-publicas-nfc`.

## Ejecutar y verificar

Desarrollo en el **puerto 300** con `debug=True` — recarga sola al editar, no
hace falta reiniciarla.

No puedo iniciar sesión, así que las rutas protegidas se prueban con el test
client de Flask inyectando `s['_user_id']`. El procedimiento completo está en la
skill `verificar-cambio`.

## Dónde está el resto del contexto

Las skills del proyecto viven en `.claude/skills/` (que es un **junction** a
`../../Claude work/skills/` — los archivos reales están ahí):

| Skill | Cuándo |
|---|---|
| `nueva-pantalla` | agregar una vista, ruta o endpoint |
| `editar-templates` | tocar cualquier cosa en `templates/` |
| `datos-y-sql` | consultas, esquema, importaciones |
| `pdf-reportes` | actas y PDF con WeasyPrint |
| `verificar-cambio` | antes de dar cualquier cosa por terminada |
| `ble-iot` | localización BLE, ESP32, beacons, posicionamiento |
| `rutas-publicas-nfc` | lo accesible sin login (flujo NFC) |

Documentos largos de referencia en `../../Claude work/contexto/`:
`arquitectura.md`, `modulos.md`, `CAMBIOS-BLE.md`. Cada uno abre con un índice de
rangos de línea — lee solo la sección que necesites, no el archivo completo.

## Trabajo en curso: Fase 2 — módulo de reportes

Se está digitalizando la papelería del departamento (preventivo, correctivo,
entrada/salida, tecnovigilancia, baja). **Fases 2.0 a 2.5 terminadas** — todo
lo que tenía especificación. Lo que falta (baja de equipo, bitácora de
carrito rojo) está **bloqueado por falta de especificación**, no por trabajo
de código: no se puede empezar sin que el usuario defina los formatos.

**Al retomar, lee primero `../../Claude work/contexto/RETOMAR-FASE-2.md`** — es
corto y dice qué está hecho, qué sigue y qué trampas ya se pisaron. El plan
completo está al lado, en `FASE-2-REPORTES.md`, con su índice de rangos.

Tres cosas que conviene saber aunque no toques ese módulo:

- **La base de pruebas no arranca limpia.** Es donde se ensaya antes de
  actualizar producción, así que acumula capturas de prueba entre sesiones.
  No escribas pruebas que asuman un conteo fijo: las suites toman una línea
  base al arrancar y comprueban que dejan el sistema como lo encontraron.
  Producción es otra base, y está más actualizada que esta.
- El motor de PDF ya **no** vive en `admin_routes.py`: está en
  `services/reporte_pdf.py` y lo comparten todos los tipos de reporte.
- `app.py` cachea `static/` 30 días, así que un arreglo de CSS o JS no le llega
  a quien ya visitó el sitio. Usa `{{ estatico('Js/x.js') }}` en vez de
  `url_for('static', ...)`; el helper está registrado como context processor
  desde `routes/reportes_routes.py`.
