# Limpieza y organización del proyecto

Fecha: 16 de octubre de 2026.

## Resultado

La raíz pasó de **82 a 67 archivos** y de **65 a 60 módulos Python**. Se
trasladaron herramientas, scripts SQL, documentos y resultados sin reorganizar
los módulos que sostienen la aplicación. Solo se creó una carpeta funcional
nueva: `sql/`. No se modificaron registros de SQL Server, modelos, imágenes,
embeddings, configuración facial ni el entorno virtual.

El análisis desde `main.py` identificó 58 módulos locales alcanzables antes
de la limpieza y 57 después de integrar el adaptador de LEDs en el agente.
Se revisaron imports dentro de funciones, callbacks, registros de herramientas,
rutas por string, configuración y llamadas dinámicas. El grafo es conservador:
incluye ramas opcionales, sin afirmar que todas se ejecutan al arrancar.

## Estructura anterior

```text
proyecto/
├── main.py, ui/interfaz.py, core/database.py y módulos de aplicación
├── jarvis_leds.py y cargar_datos_inventario.py
├── qa_imagen_ui.py, verificar_interfaz_visual.py, retirar_acceso_sql.py
├── 6 scripts SQL
├── 2 resultados JSON junto a las 3 configuraciones activas
├── README.md, INFORME_CRISP_DM_IMPLEMENTACION.md y un documento Word
├── archivo_acceso_retirado/, archivo_cargas_anteriores/
├── aws/, tests_aws/, hardware/ y NVIDIA Corporation/
├── herramientas/, pruebas/, verificacion_ui/, migrations/, docs/
├── modelos/, modelos_voz/, Clasificacion/, rostros/, arduino/
└── backups/, respaldos_inventario/, outputs/, cachés y .venv/
```

## Estructura actual

```text
proyecto/
├── main.py, ui/interfaz.py, core/database.py y módulos activos
├── jarvis/api_jarvis.py y entradas de compatibilidad conservadas
├── config_sistema.json, intenciones_jarvis.json
├── reconocimiento_facial_config.json
├── README.md, requirements.txt, .gitignore y .env
├── sql/                     # Esquema, registros y operaciones SQL manuales
├── migrations/              # Migraciones existentes, sin ejecutar
├── herramientas/            # Inspección, mantenimiento y generación manual
├── pruebas/                 # Comprobaciones automatizadas
├── verificacion_ui/         # Verificadores de pantallas y capturas
├── docs/                    # Documentación e inventarios estructurales
│   └── entregables/         # Documentos Word
├── outputs/validaciones/    # Resultados de carga y verificaciones
├── backups/                 # Respaldos e historial retirado
├── respaldos_inventario/    # Conservada incluso estando vacía
├── arduino/                 # Sketch existente
├── modelos/, modelos_voz/, Clasificacion/, rostros/
├── evaluacion_facial/       # Evidencias y métricas existentes
├── cache_voz/, rostros_temp/ # Cachés funcionales conservadas
└── .venv/, .vscode/, .git/   # Entorno y metadatos conservados
```

## Archivos y carpetas trasladados

| Origen | Destino |
|---|---|
| `Base de Datos.sql` | `sql/Base de Datos.sql` |
| `registros_inventario.sql` | `sql/registros_inventario.sql` |
| `normalizar_historial_inventario.sql` | `sql/normalizar_historial_inventario.sql` |
| `reorganizar_estantes.sql` | `sql/reorganizar_estantes.sql` |
| `verificar_estantes.sql` | `sql/verificar_estantes.sql` |
| `verificar_historial_inventario.sql` | `sql/verificar_historial_inventario.sql` |
| `qa_imagen_ui.py` | `tools/verificacion_ui/qa_imagen_ui.py` |
| `verificar_interfaz_visual.py` | `tools/verificacion_ui/verificar_interfaz_visual.py` |
| `retirar_acceso_sql.py` | `tools/retirar_acceso_sql.py` |
| `INFORME_CRISP_DM_IMPLEMENTACION.md` | `docs/INFORME_CRISP_DM_IMPLEMENTACION.md` |
| `Segundo Entregable corregido.docx` | `docs/entregables/Segundo Entregable corregido.docx` |
| `resultado_carga_inventario.json` | `outputs/validaciones/resultado_carga_inventario.json` |
| `resultado_validacion_inventario.json` | `outputs/validaciones/resultado_validacion_inventario.json` |
| `archivo_acceso_retirado/` | `backups/archivo_acceso_retirado/` |
| `archivo_cargas_anteriores/` | `backups/archivo_cargas_anteriores/` |
| `herramientas/aplicar_limpieza.ps1` | `backups/limpieza/aplicar_limpieza_anterior.ps1.retirado` |
| `docs/plan_limpieza.json` | `backups/limpieza/plan_limpieza_anterior.json` |

Los dos últimos archivos describían una limpieza anterior. Se archivaron juntos
para evitar ejecutar un plan desactualizado. Se conservó todo su contenido.
Los seis SQL trasladados se compararon byte por byte con el respaldo previo:
no se alteraron sus sentencias ni se ejecutaron.

## Consolidaciones y eliminaciones

- `jarvis_leds.py`: sus dos funciones se integraron en `jarvis/agente_inventario.py`
  como `_acciones_led_ubicacion` y `_procesar_leds`. Se conservaron la resolución
  de productos, las aclaraciones pendientes, las negaciones y el mismo servicio
  de iluminación. El archivo separado se retiró después de comprobar el reemplazo.
- `cargar_datos_inventario.py`: únicamente importaba y ejecutaba el `main` del
  importador existente. Se retiró ese lanzador duplicado; la entrada vigente es
  `python -m tools.actualizar_desde_exportacion_sql --help`.
- Se eliminaron **139 archivos de bytecode** en **7 carpetas de caché**.
- `aws/`, `tests_aws/` y `hardware/` únicamente contenían bytecode anterior;
  no se encontraron imports activos hacia esos paquetes. Se retiraron tras
  limpiar sus cachés. `NVIDIA Corporation/` no contenía archivos y también se retiró.

No se eliminaron respaldos. La revisión por tamaño y SHA-256 no encontró grupos
de archivos idénticos entre los respaldos conservados. No se recorrieron ni
limpiaron los paquetes de `.venv/` ni de `node_modules/`.

## Imports y rutas corregidos

- Los tres verificadores que utilizaban `qa_imagen_ui` importan ahora
  `verificacion_ui.qa_imagen_ui`.
- El verificador visual trasladado agrega la raíz al ejecutar su archivo y
  mantiene sus salidas dentro de `verificacion_ui/`.
- La herramienta de retirada de acceso agrega la raíz para importar
  `core/database.py` y localiza las migraciones desde esa raíz. No se ejecutó.
- Generadores, normalizadores, reorganizadores y verificadores SQL utilizan
  ahora `sql/`. La generación de registros ya no vuelve a llenar la raíz.
- La verificación del inventario escribe su informe en `outputs/validaciones/`
  independientemente del directorio desde el que se lance.
- Las comprobaciones de LEDs apuntan al servicio utilizado por el agente,
  tras consolidar el adaptador.
- Se actualizaron las instrucciones y rutas del README principal.

`.gitignore` mantiene exclusiones para `.venv/`, `.env`, `__pycache__/`,
`*.pyc`, `cache_voz/`, `rostros_temp/` y `outputs/`; se agregaron las
dependencias auxiliares `node_modules/` y los respaldos locales de inventario.
Python puede regenerar bytecode al abrir la aplicación; seguirá ignorado por Git.

## Archivos conservados por seguridad

**Reconocimiento facial.** `ai/facial/diagnostico_cnn.py` y
`ai/facial/diagnostico_facial_basico.py` se invocan desde la interfaz; sus nombres no los
convierten en herramientas prescindibles. Se conservaron en la raíz.
`ai/facial/cnn_dataset.py` prepara y revisa datos, `ai/facial/cnn_dataset_actual.py` implementa el
modo provisional, `ai/facial/sesiones_cnn.py` organiza capturas documentadas y
`ai/facial/seguridad_cnn.py` controla evidencia temporal. No son implementaciones
intercambiables. Los motores CNN y SFace, sus modelos y la captura conservan
sus rutas. Reunirlos en un nuevo paquete habría requerido cambios extensos sin
reducir funcionalidad duplicada demostrada.

**JARVIS.** Se mantuvieron separados el agente, NLP/intenciones, personalidad,
voz, herramientas de consulta, API y adaptador LLM. La ruta de compatibilidad
del agente sigue siendo un fallback activo; no se eliminó por su extensión.
La arquitectura de Vosk, TTS y cancelación permanece intacta.

**Interfaz.** Los módulos específicos de inventario, predicción, reportes,
estado y configuración se utilizan desde `ui/interfaz.py`. Los componentes,
tema, trabajos en segundo plano y ventanas de cámara tienen responsabilidades
distintas. No se volvieron a concentrar en un único archivo.

**Recursos.** Los tres JSON que permanecen en la raíz son configuración activa,
no informes. También se conservaron las entradas independientes
`jarvis/api_jarvis.py`, `ai/facial/reconocimiento_facial.py` y `ai/facial/pipeline_facial_basico.py`,
los datasets, los modelos y las migraciones. Su ausencia del recorrido directo
de una sesión de escritorio no demuestra que sobren.

## Clasificación e inventario

`docs/inventario_archivos.json` clasifica individualmente los archivos propios
como PRODUCCION, SOPORTE, DESARROLLO, TEMPORAL, OBSOLETO, DUPLICADO,
DOCUMENTACION o RESULTADO. Cada entrada incluye su motivo. Los duplicados
confirmados se documentan como consolidados y ya no figuran como archivos
presentes. Los elementos OBSOLETO se mantienen archivados; TEMPORAL no implica
eliminación automática de cachés funcionales.

Los directorios administrados externamente, como `.venv/` y `node_modules/`,
se registran como unidades sin listar sus dependencias internas. PRODUCCION
describe el papel de un archivo en la ejecución, sin afirmar que el proyecto
esté desplegado en un entorno operativo definitivo.

`docs/dependencias_proyecto.json` contiene el grafo local desde `main.py`,
las dependencias de las herramientas, las llamadas dinámicas identificadas y
los recursos de configuración conservados. El informe antes/después y los
traslados están en `outputs/validaciones/limpieza_proyecto.json`.

## Verificación realizada

- **121 comprobaciones automatizadas aprobadas:** conversación, NLP, voz,
  integración de LEDs, reglas físicas, configuración, tablas, reportes e historial.
- Arranque real por `main.py` y recorrido de **15 pantallas** en **1366×768** y
  **1920×1080**, sin errores de callbacks durante ese recorrido.
- Lecturas reales a SQL Server para presentar las pantallas; las escrituras de
  hallazgos se desactivaron en el verificador. No se ejecutaron cargas,
  migraciones, reentrenamientos ni operaciones de hardware.
- Sintaxis revisada mediante AST en los archivos Python propios del análisis.
- Los **44 archivos protegidos de SFace** conservaron sus hashes.
- Los SQL movidos conservaron exactamente el contenido respaldado.
- La entrada del importador existente respondió correctamente a `--help`.

Las capturas del recorrido están en `verificacion_ui/densidad/`. El recorrido
de pantallas no sustituye una evaluación de precisión facial, una medición de
voz en vivo ni una comprobación eléctrica de Arduino; esas operaciones no se
realizaron como parte de esta limpieza.

## Respaldo y revisiones posteriores

Antes de editar se creó y verificó `backups/limpieza/organizacion_20261016.zip`
con **142 archivos** de código, SQL y documentación de control. Las versiones
previas de los inventarios están dentro de ese respaldo. Los archivos Word,
datasets y modelos se conservaron en sus destinos sin editar su contenido.

Quedan para una revisión posterior las entradas faciales de compatibilidad,
las rutas de fallback conversacional y las evidencias históricas de
`verificacion_ui/`. Su retirada requeriría comprobar usos externos o su valor
documental. No se borraron por parecer antiguos ni se introdujo una
refactorización general de paquetes.
