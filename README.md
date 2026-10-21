# Sistema Inteligente de Inventario

## Conteo físico en tres pasos — 17/10/2026

La pantalla se reorganizó en **seleccionar ubicación**, **registrar conteo** y
**revisar/aplicar ajustes**. Ubicación y responsable se eligen antes de cargar el
inventario real. La tabla muestra código, producto, posición, stock del sistema,
conteo físico, diferencia y estado. Los lotes se distinguen junto al producto;
cada registro de lote requiere su propia confirmación.

Seleccionar una fila o hacer doble clic muestra un editor compacto. **Guardar
conteo** confirma la cantidad, incluso cero o un valor igual al stock. La carga
inicial nunca da una fila por contada. La diferencia se calcula como físico menos
sistema y se muestra como CORRECTO, FALTANTE o SOBRANTE, con texto y colores suaves.
Cantidades y diferencias se presentan con dos decimales; el servicio conserva su
precisión existente. El editor conserva cualquier tercer decimal registrado para
evitar redondearlo al confirmar. Los totales se agrupan por unidad de medida.

Cada edición programa el guardado del progreso tras 400 ms, fuera del hilo Tk.
Se actualiza el **mismo borrador**, sin crear uno por cada cantidad. Se conserva
**Guardar borrador** como respaldo y se informa si el guardado falla. Borradores
aparece solo cuando hay registros pendientes, identificados por ubicación, fecha
y responsable, sin IDs SQL visibles. **Continuar borrador** recupera cantidades,
responsable y avance. Cambiar ubicación con trabajo sin guardar se bloquea para
evitar perderlo; una vez guardado puede iniciarse otro conteo.

Al completar las filas se habilita **Revisar y aplicar ajustes**. Su ventana
muestra sistema, físico, diferencia y movimiento previsto por producto/lote.
**Confirmar ajustes** llama al servicio existente: faltante genera Ajuste salida,
sobrante genera Ajuste entrada y una coincidencia no genera movimiento. **Cancelar**
conserva el borrador y no aplica ajustes. El resumen final muestra cantidades de
ajustes/sin cambios, fecha y responsable; el conteo queda APPLICADO y no admite
otra edición ni aplicación. Las observaciones identifican el origen como conteo.

Se conservaron las reglas de cantidad, empleados/ubicaciones activos, lotes,
stock no negativo y ajuste transaccional. Si el stock cambia desde la carga, se
rechaza toda la operación. También se compara la instantánea revisada con el
borrador guardado antes de confirmar. No se reescribe el stock de referencia de
un borrador para ocultar cambios posteriores.

`migrations/009_progreso_conteo.sql` ya se aplicó: agrega solamente
`detalle_conteos.contado` (BIT nullable), sin alterar cantidades ni movimientos.
No crea tablas. El indicador permite persistir avances incompletos y rechazarlos
en el servicio de aplicación, no solo deshabilitando un botón. Los borradores
anteriores con indicador NULL requieren confirmar sus filas; sus cantidades
guardadas se conservan. El servicio permite actualizar únicamente BORRADOR.

Se modificaron `ui/inventario_ui.py` y `inventory/conteo_inventario.py`. Se agregaron la
migración 009, `tests/probar_conteo_gui.py`, `tests/probar_conteo_servicio.py`
y `tools/verificacion_ui/validar_conteo.py`. No se agregaron dependencias.
Las operaciones SQL de verificación se revierten al terminar. Las capturas de
`verificacion_ui/conteo/` usan lectura SQL con guardado/aplicación sustituidos;
las cantidades físicas introducidas verifican la interfaz y no acreditan un
conteo realizado en el almacén.

## Reportes, resumen IA y notificaciones centrales — 17/10/2026

**Reportes** abre Inventario actual y carga automáticamente la vista previa.
Las selecciones actualizan al elegir; los campos escritos esperan 400 ms.
Los resultados atrasados de filtros anteriores se descartan. Se muestran carga,
error y ausencia de registros; PDF y Excel se habilitan cuando termina la consulta.
El botón «Generar vista previa» se retiró. Los exportadores reciben una copia de
la instantánea visible, con sus filtros, sin consultar SQL nuevamente. Las acciones
de exportación quedan arriba para no tener que bajar por toda la tabla.
Se conservaron los reportes existentes y se incorporaron Movimientos y
Vigilancia / Intrusiones. Las cantidades de inventario se resumen por unidad;
no se suman litros, unidades y cajas como si fueran una misma magnitud.

**Análisis IA** resume resultados del motor de Predicción y anomalías guardadas,
con enlaces a sus módulos. Actualiza al entrar; no ejecuta detección de anomalías
ni duplica sus tablas. La última predicción se identifica como cálculo de esta
sesión. El número de movimientos analizados se muestra solo si se ejecutó un
análisis en esta sesión; no se deduce del número de hallazgos almacenados.
Predicción conserva comparación, consumo, cobertura, riesgo y gráfica histórica;
sus consultas trabajan en segundo plano y no generan alertas al abrirlas.
Anomalías conserva análisis, explicación y revisión. «Filtrar» lee lo guardado;
«Analizar» ejecuta y guarda hallazgos mediante el detector existente.

**Alertas** conserva los indicadores, con una columna de mensaje más compacta y
el detalle completo al seleccionar. Las fechas de las tablas muestran día, mes,
año y segundos, sin alterar la precisión de los valores internos.

**Telegram** se administra en Configuración → Telegram: habilitación global,
categorías Inventario / Anomalías / Vigilancia / Reconocimiento facial / Sistema,
nivel mínimo, estado de token/chat, prueba de conexión, entregas y reintento de
errores. Las credenciales siguen exclusivamente en `.env`; no se muestran.
Vigilancia conserva además su casilla de envío por cámara. Para enviar se necesitan
habilitación global, categoría y nivel permitidos, y credenciales válidas.

`integrations/telegram/telegram_service.py` centraliza HTTP, formato, política, deduplicación y estado.
`notificar_evento` admite tipo, título, mensaje, nivel, datos, imagen/video y una
referencia estable obligatoria. El observador inicia con los IDs actuales de
alertas, anomalías y movimientos: no recorre pendientes antiguas para enviarlas.
Consulta cada cinco segundos, sin recalcular todos los modelos periódicamente.
Una referencia única y una toma transaccional impiden enviar simultáneamente la
misma notificación. La alerta SQL y su hallazgo asociado se consolidan para evitar
avisos duplicados del mismo movimiento inusual.

Se notifican nuevas alertas SQL de stock bajo, agotados, próximo agotamiento,
persona no reconocida y sistema, nuevos hallazgos y las capturas/clips de
intrusión. Los errores importantes se notifican cuando existe una alerta válida
del sistema o un emisor usa el servicio central; no se envían excepciones crudas.
Los fallos de Telegram no revierten el inventario ni la alerta original.

Solo cuando aparecen movimientos nuevos que cambian stock global se vuelve a
consultar el motor de riesgo para los productos afectados. Las transferencias
se excluyen. Se reutiliza la creación de alertas existente y se conserva el último
riesgo observado para notificar cambios a ALTO/CRÍTICO. La primera observación
establece una línea base: no afirma que haya ocurrido una transición que no se
observó. Abrir Predicción, Análisis IA o Reportes no emite avisos de riesgo.

`migrations/008_notificaciones_telegram.sql` ya se aplicó: agrega
`notificaciones_telegram` y `telegram_estado_riesgo`, sin copiar registros antiguos
ni cambiar el inventario. La primera guarda referencia, estado, intentos y fecha
de envío; la segunda solo conserva el estado necesario para controlar avisos.
Estados: PENDIENTE, ENVIANDO, ENVIADA, ERROR, OMITIDA e INCIERTO.
«Reintentar errores» habilita explícitamente los ERROR para el worker; no repite
ENVIADA. Una entrega sin confirmación o interrumpida queda INCIERTO para revisar
el chat antes de otro envío. No se puede garantizar entrega exactamente una vez
si la red se corta después de que Telegram recibe un mensaje. No hay reenvío
automático de errores o pendientes de sesiones anteriores. Los eventos observados
con envíos deshabilitados quedan OMITIDA y no se despachan al habilitar después.

Archivos nuevos: `ui/analisis_ui.py`, `migrations/008_notificaciones_telegram.sql` y
`tests/probar_experiencia_modulos.py`. Se ajustaron `integrations/reporting/reportes_ui.py`, `integrations/reporting/reportes.py`,
`ui/prediccion_ui.py`, `ui/anomalias_ui.py`, `ui/interfaz.py`, `integrations/telegram/telegram_service.py`,
`ui/configuracion_ui.py`, `core/config_manager.py`, `ui/tareas_ui.py`, `core/formato_numerico.py`
y el recorrido visual `tools/verificacion_ui/validar_densidad_visual.py`.
No se agregaron dependencias ni se cambiaron los algoritmos de SFace, CNN, YOLO,
predicción o anomalías, ni el mapa, Arduino o JARVIS.
Validación: 227 comprobaciones de regresión aprobadas, consulta de los 17
reportes contra SQL y recorrido de las 16 pantallas en ambas resoluciones.
Las capturas están en `verificacion_ui/densidad/`. La verificación transaccional
de entrega usó HTTP sustituido y rollback; no se enviaron mensajes reales.

## Vigilancia de personas y zonas restringidas — 17/10/2026

Se agregó **Vigilancia** a la navegación. Su responsabilidad es detectar
personas y entradas a una zona de cámara. Reutiliza YuNet / SFace para aportar
identidad cuando hay evidencia suficiente; no modifica CNN, inventario,
movimientos ni JARVIS.
La vigilancia permanece inactiva al arrancar, incluso si se guardó habilitada.

Modelo: **YOLOv8n**, con Ultralytics 8.3.228 y ByteTrack, ejecutado en CPU.
Se filtra `classes=[0]` (person). Los pesos siguen siendo el modelo COCO
preentrenado; el filtrado no equivale a haber entrenado un detector nuevo de
una sola clase. Ruta local: `modelos/vigilancia/yolov8n.pt`.
El modelo se carga una vez por sesión de vigilancia, fuera de Tkinter.

### Uso

1. Abra **Vigilancia** y configure la cámara: índice USB o URL RTSP/HTTP sin
   credenciales. Asigne nombres de cámara y zona, confianza y cooldown.
2. Pulse **Configurar zona**. La vista previa utiliza el mismo bloqueo de cámara
   que reconocimiento facial y captura; cierre primero cualquier otra sesión.
3. Use **Limpiar** y marque entre 3 y 20 vértices en orden sobre la imagen.
   **Guardar zona** conserva coordenadas normalizadas; **Cancelar** no las guarda.
   Se rechazan cruces, puntos repetidos y áreas vacías. Cambiar la fuente de
   cámara requiere volver a definir su zona.
4. Pulse **Iniciar vigilancia**. El vídeo muestra la zona semitransparente,
   cajas, `person`, track y score. El rojo destaca las personas dentro.
5. **Detener** libera la cámara y termina los clips pendientes como parciales.
   Los eventos se consultan en la tabla; doble clic abre su detalle y permite
   abrir la carpeta de evidencia.

### Entrada y prevención de spam

Se utiliza el punto inferior central de cada caja y los estados FUERA,
ENTRANDO, DENTRO y SALIENDO. Una entrada requiere observaciones estables fuera
y después dentro, con tres detecciones de confirmación por defecto. Una persona
que ya estaba dentro al iniciar no se presenta como una entrada observada.
Cada track mantiene cooldown de 45 segundos por defecto. Permanecer dentro no
genera alertas en cada fotograma. Una pérdida prolongada del track reinicia su
evidencia espacial; el identificador no se considera identidad de una persona.
ByteTrack puede cambiar IDs ante oclusiones; no garantiza seguimiento perfecto.

### Evidencia, SQL y Telegram

Los eventos se guardan en `outputs/intrusiones/YYYY-MM-DD/`, con UUID,
fecha/hora de Guatemala, cámara, zona, track, score, caja y estado de cada
operación. Se conserva captura completa, recorte y, si hay fotogramas
suficientes, MP4 con buffer previo y seguimiento posterior. Los valores
predeterminados son 3 segundos previos y 5 posteriores; el informe registra los
tiempos y FPS realmente disponibles, sin inventar material anterior al arranque.
Los clips se muestrean hasta 8 FPS y 640 píxeles de ancho para acotar memoria.
El códec utilizado es `mp4v`; la reproducción final en Telegram depende del
soporte del cliente y de que el envío sea aceptado.

Las colas de disco y red tienen capacidad limitada; no se acumulan fotogramas
de cámara. Ante saturación se conserva el registro local y se informa la
evidencia incompleta. El guardado y los envíos se ejecutan en workers.

`migrations/006_intrusion_yolo.sql` agrega únicamente el tipo **Intrusión
detectada** al catálogo existente. No crea tablas ni eventos. Cada entrada
confirmada se registra con nivel Alta, estado pendiente, fecha y cámara/zona
en `alertas`. El UUID y un bloqueo transaccional impiden repetir el mismo evento
al registrarlo de nuevo. Las evidencias ampliadas quedan enlazadas por ese UUID
en el JSON local. Si SQL falla, el evento queda pendiente localmente; no se
afirma que ya exista en SQL. No se implementó reenvío automático de pendientes.

Telegram envía captura y datos, y posteriormente el clip cuando esté disponible.
Se verifica HTTP 200 y la confirmación `ok` de Bot API. Errores HTTP, credenciales
ausentes y falta de red no detienen vigilancia. Los mensajes distinguen empleado
reconocido, empleado inactivo, rostro válido no reconocido e identidad no
disponible. La entrada a zona confirma la intrusión aunque no se vea el rostro.

### Identidad compartida con Empleados

`surveillance/identidad_vigilancia.py` adapta las ROI de YOLO a `PipelineFacial.procesar`, el
mismo pipeline YuNet / SFace del escáner. Ambos pasan por
`procesar_frame_empleados`. No se creó otra galería ni se recalibraron modelos.
`reconocer_empleado_en_frame` recibe BGR sin convertir colores ni ampliar las
caras; limita la ROI al frame y devuelve la caja facial en coordenadas originales.

Un worker facial consume una cola de un lote, de hasta dos personas. Cada track
no confirmado se intenta como máximo cada 0,30 segundos; la frecuencia efectiva
depende de la carga y del número de personas. Cada track tiene su propio consenso
facial y comparte detector, reconocedor, galería, configuración y política
vigente. No hay otra cámara ni otro `VideoCapture`.

Las ROI pequeñas y los cruces ambiguos no se identifican. En los cruces se
descarta el consenso pendiente; los resultados tardíos de un track perdido no
se asignan a otro. Al confirmar se conserva la identidad durante ese track y
se deja de ejecutar SFace para él. Las relaciones SQL se revisan cada cinco
segundos mientras llegan frames; los inactivos se etiquetan explícitamente.
La comparación biométrica de inactivos conserva las reglas de SFace y no supone
autorización ni altera la relación SQL o el comportamiento del escáner.

`migrations/007_identidad_intrusion.sql` agrega la columna nullable
`alertas.detalle_vigilancia` (`NVARCHAR(MAX)`). Ya se aplicó en la base local sin
cambiar cantidades de productos, movimientos o alertas. Guarda JSON con estado,
subject, empleado, código, nombre, cargo y similitud; `id_empleado` reutiliza la
referencia existente. El mismo UUID permite actualizar la misma alerta y el JSON
local si la identidad llega después. Se conserva el estado de atención de la alerta.
No hay un segundo envío Telegram por cambios faciales. Si el envío inicial ya
salió sin identidad, conserva su contenido original; el clip usa los datos
disponibles cuando se envía. Un fallo facial nunca impide guardar la intrusión.

Comprobación de rendimiento: 35 inferencias sobre una imagen pública repetida
con tres personas dieron **8,58 FPS sin worker facial y 7,65 FPS con él**
(aproximadamente 11 % menos). Es una referencia local, sin cámara y con rostros
insuficientes; no mide precisión ni garantiza FPS con caras válidas, varias
personas o una cámara real. Informe: `outputs/validaciones/vigilancia_sface_rendimiento.json`.
No se enviaron mensajes reales ni se crearon alertas operativas durante estas
verificaciones. No se agregaron dependencias.

Archivos de integración: `surveillance/identidad_vigilancia.py`, `ai/facial/reconocimiento_embeddings.py`
(solo delegación de frames), `surveillance/vigilancia_yolo.py`, `surveillance/vigilancia_ui.py`,
`integrations/telegram/telegram_service.py`, `inventory/alertas.py` y la migración 007. Las regresiones están en
`tests/probar_identidad_vigilancia.py` y `tests/probar_vigilancia.py`.
Se completaron 195 comprobaciones automatizadas entre vigilancia, identidad,
pipeline facial y regresiones de los módulos existentes. La ventana y el editor
se comprobaron a 1366×768 y 1920×1080 con captura sustituida. La identidad real
en una entrada a zona y la entrega a un destinatario Telegram siguen pendientes
de comprobar con la cámara y las credenciales del entorno.

En `.env` se agregaron las claves, sin valores incrustados en código:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Para una cámara privada se admite opcionalmente `VIGILANCIA_VIDEO_SOURCE` en
el entorno o `.env`; su URL no se guarda en el JSON de configuración.
Marque **Enviar eventos a Telegram** y guarde ajustes para habilitar envíos.
**Probar Telegram** solo envía «Prueba de conexión - Sistema Inteligente de
Inventario» y requiere credenciales válidas. No se ejecuta automáticamente.
No se imprimen tokens ni excepciones HTTP que puedan contenerlos.
Sin token/chat, la aplicación muestra **Telegram no configurado**.

### Instalación y compatibilidad

Se revisó el entorno Python 3.9: NumPy 2.0.2 y opencv-contrib-python 4.14.0.94.
No se instala otro paquete OpenCV que compita por `cv2`. La preparación usa
PyTorch 2.5.1+cpu, Torchvision 0.20.1+cpu, Ultralytics 8.3.228, lap 0.5.12 y
dependencias auxiliares. La lista YOLO opcional está en
`herramientas/requirements_vigilancia.txt`; no debe instalarse con resolución
automática que agregue `opencv-python` sobre `opencv-contrib-python`.

```powershell
.venv\Scripts\python.exe -m tools.preparar_vigilancia --instalar
```

El preparador está fijado para Windows x64/Python 3.9. Descarga ruedas desde
PyTorch y PyPI, verifica sus hashes oficiales y usa `--no-deps` para conservar
NumPy, OpenCV y TensorFlow. Descarga los pesos desde los archivos oficiales de
Ultralytics. El informe de instalación queda en `outputs/instalacion_vigilancia/`.
No descarga ni instala componentes al abrir la aplicación o pulsar iniciar.

### Archivos y comprobaciones

Código agregado: `surveillance/vigilancia_yolo.py`, `integrations/telegram/telegram_service.py`, `surveillance/vigilancia_ui.py`.
Se reutilizan `surveillance/camara_utils.py`, el bloqueo compartido existente, `inventory/alertas.py`,
`inventory/tipos_alerta.py`, `core/database.py`, `core/config_manager.py` y los componentes visuales.
La configuración se centraliza en la sección `vigilancia` del gestor y se
persiste al guardar, sin reescribir los ajustes faciales durante la preparación.
`ui/configuracion_ui.py` conserva los cambios guardados desde otros módulos.

Se agregaron `tests/probar_vigilancia.py` y
`tools/verificacion_ui/validar_vigilancia.py`. Se comprobaron geometría, debounce,
cooldown, oclusiones, exclusión de cámara, evidencia, buffer, registro SQL
idempotente mediante sustitutos y errores de Telegram sin envíos reales.
El editor se verificó con cámara sustituida y configuración aislada; las
capturas están en `verificacion_ui/vigilancia/`. El recorrido completo abrió
las 16 pantallas en 1366×768 y 1920×1080 con vigilancia inactiva.
No se generaron intrusiones reales ni se enviaron mensajes durante esas
comprobaciones. El catálogo SQL se amplió sin cambiar productos, movimientos
ni alertas existentes. `listar_eventos` permite futuras consultas de JARVIS;
no se modificó su motor conversacional para esta etapa.

Medición real del detector instalado: **aproximadamente 16 FPS en CPU**, con
640 píxeles de entrada y ByteTrack, sobre la imagen pública `bus.jpg` de
Ultralytics repetida. Se descartaron dos calentamientos y se midieron ocho
inferencias; se obtuvieron tres tracks de persona. Esto no mide el FPS de una
cámara real ni la precisión de entradas en el almacén. El detalle está en
`outputs/validaciones/vigilancia_yolo_cpu.json`. La instalación conservó las
versiones de NumPy, OpenCV y TensorFlow; su informe registra los hashes y paquetes.
El flujo completo en su worker, con dibujo de zona, cajas y buffer, obtuvo
**aproximadamente 8 FPS** sobre esa misma imagen repetida. Su medición está en
`outputs/validaciones/vigilancia_flujo.json`; no se utilizó una cámara real.
Pasaron **140 comprobaciones automatizadas**. También se ejecutaron la CNN
guardada y YOLO en el mismo proceso para verificar compatibilidad entre
TensorFlow 2.20.0 y PyTorch 2.5.1+cpu; no se modificaron sus pesos.

Documentación de referencia: [tracking Ultralytics](https://docs.ultralytics.com/modes/track/),
[YOLOv8](https://docs.ultralytics.com/models/yolov8/),
[Telegram Bot API](https://core.telegram.org/bots/api).

## Organización de archivos — 16/10/2026

El arranque sigue siendo `python main.py`. Los módulos usados por la aplicación
conservan su ubicación para mantener imports, modelos y rutas de recursos.
Los SQL independientes están en `sql/`, las migraciones en `migrations/`,
las herramientas de mantenimiento en `herramientas/` y las verificaciones de
pantallas en `verificacion_ui/`. Los resultados de carga y validación se
encuentran en `outputs/validaciones/`, y los documentos en `docs/`.

Las órdenes de iluminación de JARVIS se integraron en `jarvis/agente_inventario.py`;
`integrations/arduino/led_service.py` mantiene el transporte y `integrations/arduino/arduino_ui.py` los controles. El
antiguo lanzador de carga se sustituyó por la ejecución directa del importador
existente: `python -m tools.actualizar_desde_exportacion_sql --help`.
Los módulos `ai/facial/diagnostico_cnn.py` y `ai/facial/diagnostico_facial_basico.py` permanecen en
la raíz porque los utilizan callbacks reales de la interfaz.

El detalle de movimientos, clasificación, dependencias, respaldo y verificaciones
está en [docs/LIMPIEZA_PROYECTO.md](docs/LIMPIEZA_PROYECTO.md).
Las secciones anteriores de desarrollo conservan su contexto histórico; el
inventario vigente de archivos es `docs/inventario_archivos.json`.

## Arduino UNO y 24 LEDs — 16/10/2026

El modo inicial es **simulación**. No se abre ningún puerto al arrancar ni al
consultar el estado. El LED pertenece a la posición física, no al producto:
se reutiliza `numero_led` de `inventory/organizacion_fisica.py` con la correspondencia
`((estante - 1) * 4) + ((nivel - 1) * 2) + posición`.
Estante 1 ocupa 01–04 y Estante 6 ocupa 21–24; E4/N1/P2 corresponde al LED 14.

**Servicio central:** `integrations/arduino/led_service.py` resuelve productos a partir de las
existencias y ubicaciones vigentes de SQL. No agrega tablas, catálogos de
productos ni registros. Admite varias posiciones por producto y conserva las
asignaciones con stock cero. Rechaza posiciones ausentes, LEDs fuera de 1–24
y ubicaciones distintas que resuelvan a una misma dirección dentro del
resultado. `validar_mapeo()` comprueba las 24 direcciones sin duplicados.
El servicio ofrece conexión, desconexión, reconexión, comprobación, consulta
de estados, encendido individual o múltiple, apagado y pulso de verificación.

**Mapa:** seleccione una tarjeta de posición y pulse **Encender LED** en la
barra superior. Solo esa posición recibe fondo ámbar y la indicación **ON**.
El estado informa explícitamente la simulación. **Apagar todos los LEDs**
restaura los estilos; una búsqueda nueva requiere seleccionar otra vez una
posición. No se escriben estados de iluminación en SQL.

**JARVIS:** ubicación ofrece **Ver en mapa** y **Encender LED XX**, sin encender
por consultar. Las órdenes explícitas «Enciende la luz del Tornillo M8»,
«Enciende la luz», «Apaga la luz» y «Apaga todas las luces» usan el mismo
servicio. Texto, Vosk y la API existente utilizan el mismo procesador y memoria.
Las respuestas ambiguas requieren seleccionar un producto antes de actuar.
Los botones vuelven a resolver las posiciones SQL al pulsarlos, evitando
guardar una relación producto–LED fija. El transporte y la síntesis de voz
conservan su arquitectura anterior.

**Configuración → Arduino / LEDs:** permite habilitar hardware, elegir modo,
detectar o escribir puerto, definir baudrate y timeout, conectar, desconectar,
reconectar, comprobar conexión, verificar un LED y apagar todos. Guarde los
valores antes de conectar. Los valores iniciales se incorporan desde
`core/config_manager.py`: habilitado `false`, modo `simulacion`, puerto vacío,
9600 baudios y timeout de 2 segundos. Se persisten junto con las demás opciones
al guardar; no se reescribió el JSON facial durante esta implementación.
La tarjeta **Arduino** en Estado muestra simulación, falta de configuración,
desconexión, conexión o error, sin consultar continuamente el puerto.

**Protocolo serial:** ASCII terminado en LF. Comandos `LED:14:ON`,
`LED:14:OFF`, `ALL:OFF`, `PING` y `STATUS`. Respuestas `OK`, `READY`, `PONG`
y `ERROR:motivo`. `STATUS:000000000000000000000000` contiene exactamente 24
bits, del LED 01 al 24. En hardware, un envío no basta: los cambios requieren
`OK`, y la conexión requiere `PONG`. Un error o timeout cierra el enlace y
marca los estados como no confirmados; nunca se convierte silenciosamente en
simulación ni se presenta como un apagado físico confirmado. La comunicación
se realiza en workers; el mapa consume instantáneas sin esperar el bloqueo
serial. Los logs `[ARDUINO]` se emiten por operaciones, sin sondeo repetitivo.

**Firmware preparado:** `arduino/inventario_leds.ino` implementa el analizador
del protocolo para UNO a 9600 baudios, con búfer acotado y validación de números.
No asigna 24 pines. La función `aplicarSalidas` es la única capa pendiente de
implementar cuando se decida la electrónica. Mientras no esté configurada,
los comandos de salida responden `ERROR:OUTPUT_NOT_CONFIGURED`; `PING` funciona.
Por ello todavía no se puede controlar un circuito real cambiando solo el modo:
primero debe completarse esa capa y cargarse el sketch. Después, Python no
necesitará conocer si se usan registros de desplazamiento o multiplexación.
El sketch no se compiló ni se cargó en una placa durante esta etapa.

**Dependencia opcional de hardware:** se agregó `pyserial>=3.5,<4` a
`requirements.txt`. No está instalada en el entorno verificado; la simulación
funcionó sin ella. Para utilizar puertos físicos:

```powershell
.venv\Scripts\python.exe -m pip install "pyserial>=3.5,<4"
```

Archivos creados: `integrations/arduino/led_service.py`, `integrations/arduino/arduino_ui.py`,
`arduino/inventario_leds.ino`, `tests/probar_led_service.py` y
`tools/verificacion_ui/validar_arduino_simulacion.py`.
Archivos modificados: `core/config_manager.py`, `ui/configuracion_ui.py`,
`core/estado_sistema.py`, `ui/estado_ui.py`, `inventory/mapa_almacen.py`, `jarvis/agente_inventario.py`,
`ui/interfaz.py`, `requirements.txt`, este README y la comprobación previa
`tools/verificacion_ui/validar_productos_jarvis_mapa.py` para admitir el nuevo botón.

Validación: recorrido de Mapa y Configuración en 1366×768 y 1920×1080;
consulta SQL de las 24 posiciones; Tornillo M8 resuelto realmente a E4/N1/P2,
LED 14; encendido y apagado por botón y contexto conversacional sin hardware.
Capturas e informe en `verificacion_ui/arduino/`. La aplicación completa
conservó las acciones de Productos y la navegación opcional de JARVIS.
Pasaron 121 verificaciones automatizadas. La suite cubre ACK, rechazo de comandos, timeout, reconexión, ausencia de
pyserial, falta de configuración, mapeo, ambigüedad y regresiones de voz,
conversación, tablas y reportes. No se alteraron datos SQL ni modelos faciales;
los 44 archivos del manifiesto SFace conservaron sus hashes.

## Refinamiento visual compacto — 15/10/2026

Se conserva la paleta azul y la estructura del escritorio. Los componentes
compartidos usan márgenes de página de 24 px horizontales y 18 px verticales,
inputs de altura uniforme, tarjetas y KPIs más bajos, botones con jerarquía
consistente y filas de tabla de 36 px. El encabezado reúne BD, JARVIS y cámara
en una fila, junto al acceso a JARVIS. La navegación conserva los grupos
ALMACÉN, INTELIGENCIA, PERSONAL y SISTEMA, con menos separación desperdiciada.

Productos conserva sus tres acciones principales y sus menús. Historial usa
dos filas de filtros y nueve columnas principales; código, motivo, referencia
y observación se consultan en Detalle, doble clic o Enter. Los valores de todas
las columnas se conservan. Alertas reúne Atender y Actualizar a la izquierda y
separa Eliminar a la derecha. Los detalles de filas se muestran en una ventana
de lectura con scroll, sin forzar columnas desproporcionadas.

El mapa tiene tarjetas uniformes de dos líneas por producto, nombres abreviados
con detalle completo disponible al seleccionar, y tres estantes por fila cuando
el ancho lo permite. El detalle ocupa 320 px en pantallas anchas y una tarjeta
inferior compacta en las pequeñas. Su tabla principal muestra producto, cantidad
y posición; código y unidad siguen disponibles en el detalle de fila. Las
asignaciones físicas, la búsqueda, los colores y el resaltado no cambian.

Análisis IA presenta tarjetas claramente rotuladas Predicción y Anomalías.
Predicción conserva sus cinco KPIs en una fila compacta. Anomalías deja fechas,
producto y nivel visibles; Tipo y Movimiento están en Filtros avanzados, cuyos
valores se conservan al cerrar el bloque. Los tres botones de estado se reúnen
en Cambiar estado. Motivo y tipo detallado permanecen en el detalle existente.

Reportes reúne tipo y Generar vista previa en una fila, filtros debajo y un
resumen reducido antes de la tabla. PDF y Excel conservan sus exportadores;
Exportar predeterminado está en Más opciones. Si un reporte tiene más de ocho
columnas, la vista principal muestra ocho y el detalle de fila mantiene el resto;
la exportación conserva todas. Las herramientas faciales secundarias y las
acciones destructivas de Empleados se agrupan en menús que invocan los mismos
botones y respetan sus estados habilitados/deshabilitados.

Se reutilizaron crear_pagina, crear_panel, crear_kpi, Navegacion, la fábrica de
tablas y los callbacks existentes. ui_components centraliza el ajuste de ancho
de columnas, el menú de acciones agrupadas y el detalle de fila. No se cambió
SQL, cálculos, modelos, memoria de JARVIS ni lógica de movimientos.

Archivos de presentación modificados: ui/ui_theme.py, ui/ui_components.py, ui/interfaz.py,
ui/inventario_ui.py, inventory/mapa_almacen.py, ui/anomalias_ui.py, ui/prediccion_ui.py y integrations/reporting/reportes_ui.py.
La revisión en tools/verificacion_ui/validar_densidad_visual.py recorre 15 módulos en
1366×768 y 1920×1080 y guarda capturas y medidas en verificacion_ui/densidad/.
Pasaron 94 verificaciones de tablas, reportes, consultas, conversación y voz.
Las consultas de la revisión visual fueron de lectura; no se ejecutaron las
operaciones de los botones destructivos ni se modificaron registros.

## Ubicaciones de JARVIS y pantalla Productos — 15/10/2026

Las consultas «¿Dónde está?», «¿En qué estante está?» y «¿Cuál es su ubicación?»
responden en el chat con los datos de SQL y ofrecen **Ver en mapa** debajo del
mensaje. No cambian de pantalla. El botón conserva el producto de esa respuesta,
sin pedir su nombre de nuevo ni reiniciar el contexto. Si hay varias ubicaciones,
se enumeran; las posiciones con cantidad cero se conservan y se explica el
agotamiento. Se muestran estante, nivel y posición cuando esos datos existen,
con el código como referencia secundaria.

Solo una petición expresa como «Muéstramelo en el mapa», «Abrir mapa», «Ver
ubicación en mapa», «Llévame al mapa», «Enséñame dónde está» o «Muéstramelo»
después de una consulta de ubicación abre el mapa. Si el producto es ambiguo,
se pide elegir antes de navegar. Las respuestas estructuradas distinguen
`acciones_ui` (órdenes expresas) de `acciones_opcionales` (botones sin ejecución
automática). Texto y voz conservan el punto de entrada y memoria compartidos;
no se modificó reconocimiento ni síntesis de voz.

Productos muestra **+ Nuevo producto**, **Editar**, **Ver ubicación** y
**Más acciones ▼**. Este último contiene Ficha del producto, Desactivar /
reactivar y Análisis de rotación. **Catálogos ▼**, separado debajo de la tabla,
reúne Categorías, Unidades, Ubicaciones y Motivos. Limpiar filtros está en el
panel de búsqueda. La búsqueda conserva el debounce de 300 ms y se ejecuta
inmediatamente con Enter, cancelando la búsqueda programada pendiente.

Editar, Ver ubicación, Ficha y Desactivar / reactivar se habilitan al seleccionar
un producto. Hay menú contextual con clic derecho y doble clic para abrir la
ficha. Ver ubicación abre primero un detalle con posiciones y cantidades; su
botón **Ver en mapa** realiza la navegación y el resaltado existentes. No se
perdieron funciones ni se cambió el cálculo de stock, la lógica de movimientos,
la estructura o los registros de la base de datos.

Archivos: jarvis/agente_inventario.py, jarvis/nlp_jarvis.py, jarvis/jarvis_personality.py, ui/interfaz.py,
ui/ui_theme.py, ui/inventario_ui.py, este README y las verificaciones de conversación,
voz e interfaz. Las comprobaciones de la interfaz utilizaron consultas SQL de
solo lectura, sin ejecutar operaciones de creación, edición ni desactivación.

## CNN: modo Dataset actual — 15/10/2026

El modo seleccionado por defecto para CNN es **Dataset actual**. En Empleados /
Reconocimiento facial: seleccione CNN, conserve Dataset actual, pulse Entrenar
CNN o Reconocer con cámara. El modelo provisional ya está entrenado. No requiere
empleados, relaciones biométricas, consultas SQL ni cuatro sesiones para entrenar
o reconocer. El resto del inventario conserva su conexión SQL habitual.
**Validación estricta** sigue disponible y mantiene sus comprobaciones de sesiones.

Resultados del entrenamiento ejecutado con semilla 42:

| Medida | Resultado |
|---|---:|
| Clases | subject01–subject15 y subject19 (16) |
| Imágenes válidas | 182 |
| Entrenamiento / validación estratificada | 145 / 37 |
| Accuracy entrenamiento del modelo guardado | 100% |
| Accuracy validación | 97,2973% (36/37) |
| Mejor época por val_loss / épocas ejecutadas | 38 / 46 |
| Threshold provisional | 0,6406927705 |
| Margen provisional | 0,4571013749 |
| Identidades incorrectas aceptadas en esa validación | 0 |
| Imágenes de validación rechazadas | 1 |

La única confusión fue subject08→subject03, con score 0,292377 y margen
0,000429; se rechazó. Esto no demuestra una tasa de falsos positivos frente
a personas desconocidas: no se evaluaron desconocidos independientes. Las
imágenes no están separadas por sesiones y la misma validación seleccionó
pesos y umbrales; los resultados son **provisionales y pueden ser optimistas**.
La confianza mostrada es el score softmax, no una probabilidad de identidad
validada en producción. No se evaluó accuracy con personas en cámara durante
esta revisión.

Se conservaron las 182 imágenes válidas existentes, usando fuentes originales
canónicas en lugar de sumar sus copias reducidas. Las capturas nuevas no forman
parte de este modo. subject16–subject18 quedaron excluidos por calidad. El
dataset y la cámara usan YuNet, alignCrop por landmarks, BGR→gris, 100×100×1,
float32 entre 0 y 1 y la misma transformación central. Las imágenes de inscripción
ya alineadas conservan esa alineación documentada; no se alinean dos veces al
preparar el entrenamiento. No se calcularon ni regeneraron embeddings SFace.

El entrenador reutiliza la arquitectura CNN propia existente, crea pesos nuevos,
aplica giros pequeños, zoom, traslación, brillo moderado y flip horizontal solo
en entrenamiento. EarlyStopping y ModelCheckpoint conservan el mejor modelo
por val_loss; ReduceLROnPlateau reduce la tasa de aprendizaje si se estanca.
La cámara carga el modelo una vez, procesa cada tres a cinco frames, usa colas
de un frame y exige score, margen y cuatro coincidencias dentro de cinco
predicciones. Devuelve subjectXX directamente, sin resolver empleados y sin
escribir alertas SQL. La ventana muestra subject, confianza y estado.

Los artefactos se guardan separados de la CNN estricta en
`modelos/cnn_dataset_actual/entrenamientos/<id>/`: modelo.keras,
class_indices.json (índice→subject explícito), politica.json, metricas.json,
particiones.json y matriz_confusion.png. El archivo vigente.json señala la
versión completa publicada y comprueba hashes. El modelo estricto y los 44
archivos protegidos de SFace conservaron sus hashes.

Diagnóstico y matriz: **Ver diagnóstico**. Informes en
`evaluacion_facial/cnn/dataset_actual.json` y
`evaluacion_facial/cnn/entrenamiento_dataset_actual.json`.
Se puede utilizar el módulo sin iniciar el inventario ni conectar SQL:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ai.facial.cnn_dataset_actual entrenar
.\.venv\Scripts\python.exe -X utf8 -m ai.facial.cnn_dataset_actual camara
.\.venv\Scripts\python.exe -X utf8 -m ai.facial.cnn_dataset_actual diagnostico
```

Pasaron 73 comprobaciones y ambos recorridos de interfaz, incluyendo el bloqueo
del modo estricto y el recorrido provisional sin consultas SQL de empleados.
La cámara disponible mostró aproximadamente 29 FPS, sin guardar imágenes ni
consultar SQL. No hubo un rostro válido en esa comprobación, por lo que no
acredita reconocimiento en vivo. No se añadieron dependencias ni se modificó
la base de datos. Los estados anteriores que siguen a continuación documentan
etapas previas y el modo estricto, no el estado del modelo provisional actual.

## Captura guiada de sesiones CNN — 15/10/2026

En **Empleados**, seleccione una persona y pulse **Capturar sesión CNN**. El plan
muestra nombre, subject, sesiones completas y próxima sesión; exige confirmar
la persona antes de **Iniciar captura**. Las condiciones se asignan en orden:
frontal, lateral, distancia y variación independiente. Las personas vinculadas
a las tres confusiones históricas reciben un aviso de prioridad. No se crean
etiquetas ni relaciones SQL nuevas desde esta herramienta.

Cada foto requiere pulsar **Capturar imagen**. Se comprueban detección de un
único rostro, tamaño, nitidez, iluminación y orientación con el pipeline actual.
Las fotos rechazadas no se guardan. Hay una separación mínima de un segundo
entre fotos aceptadas y se compara contenido alineado mediante dHash y RMSE,
tanto dentro de la sesión como con las muestras anteriores del mismo subject.
No se generan embeddings. La captura permite **Completar sesión** desde cuatro
imágenes; termina al llegar a cinco. Cancelar conserva el material parcial,
marcado como incompleto y excluido del cómputo de sesiones.

Estructura: `modelos/cnn_muestras/<subject>/<session_id UUID>/`, con originales
PNG, `registro.json` y `sesion.json`. Se guardan subject, session_id, fecha_hora
con zona horaria, grupo, condición y número de sesión. Cada foto tiene su hora
real de captura. No se asignan sesiones nuevas a los archivos antiguos. La
inscripción ya documentada de subject19 se conserva como una sesión; no se le
inventa una fecha o condición histórica.

Después de capturar se revalida el dataset en segundo plano y se actualiza la
tabla de empleados. **Validar dataset** permite repetirlo. Una sesión necesita
al menos cuatro imágenes válidas no duplicadas tras esa revisión. El resumen
muestra sesiones completas, clases incompletas y solapamientos entre sesiones.
Solo se habilita **Entrenar CNN** cuando todas las clases activas reúnen los
mínimos, cuatro grupos independientes y no se detectan solapamientos. Capturar
o completar sesiones nunca inicia entrenamiento.

Estado comprobado: **1/64 sesiones completas**, 16 clases activas incompletas,
182 imágenes válidas. subject01–subject15 necesitan cuatro sesiones cada uno;
subject19 necesita tres. Cero solapamientos detectados entre las sesiones
disponibles no significa que exista ya una evaluación independiente completa.
No se hicieron nuevas capturas de personas durante esta revisión.

Se creó y verificó por SHA-256 el respaldo de **312 archivos** de imágenes y
metadatos en `backups/cnn/imagenes_71b7da7163779c49177b.zip`; incluye originales
canónicos y las copias históricas, sin contarlos como muestras adicionales.
La herramienta vuelve a respaldar las fuentes antes de una nueva captura.
El resultado está en `evaluacion_facial/cnn/respaldo_imagenes.json`.

Archivos de esta mejora: `ai/facial/sesiones_cnn.py`, `ai/facial/captura_rostros.py`, `ui/interfaz.py`,
`ai/facial/cnn_dataset.py`, `ai/facial/diagnostico_cnn.py`, las verificaciones de captura e interfaz
y este documento. Sin dependencias nuevas, sin cambio de pesos CNN ni de los
44 archivos protegidos de SFace. Pasaron 67 comprobaciones automáticas y la
verificación del plan y los controles en la interfaz real. Las comprobaciones utilizan imágenes generadas
en memoria para verificar controles; no se incorporan al dataset ni acreditan
resultados de reconocimiento. La cámara con personas sigue pendiente de uso.

## Estado vigente de CNN: sesiones documentadas

Esta revisión se limita a CNN. Los 44 archivos protegidos de SFace conservaron
sus SHA-256; tampoco cambiaron los pesos CNN ni los registros de SQL Server.
**No se entrenó ni se activó CNN.**

La auditoría completa está en `evaluacion_facial/cnn/inventario_imagenes.csv`
y `evaluacion_facial/cnn/diagnostico_sesiones.txt`. Se revisaron 19 etiquetas:
las 16 activas tienen 182 imágenes válidas. subject01–subject15 no tienen sesiones
documentadas (0/4); subject19 tiene una captura documentada con 28 imágenes (1/4).
Las distintas condiciones de los GIF históricos no acreditan sesiones distintas.
Se excluyeron nueve duplicadas y dos imágenes con iluminación deficiente entre
las clases activas. subject16–subject18 están inactivos; sus 90 imágenes no pasan
el pipeline actual (87 rostros pequeños y tres sin detección).

El protocolo exige ocho imágenes válidas, cuatro sesiones documentadas y cuatro
grupos independientes por clase. Las imágenes históricas sin sesión no se usan
en las particiones. Una misma sesión y los grupos unidos por contenido casi
duplicado nunca se reparten entre conjuntos. Se reserva un grupo completo para
validación, otro para calibración y otro para evaluación final; los restantes son
entrenamiento. Con el mínimo de cuatro sesiones hay una por conjunto. Todas las
clases activas deben estar presentes en los cuatro conjuntos. El conjunto final
no selecciona pesos ni ajusta los umbrales.

En Empleados, seleccione CNN y registre sesiones con condiciones distintas:
frontal, ángulos, distancia e iluminación/momento. Cada captura guarda cinco
imágenes y registra subject, session_id, fecha con zona horaria, grupo y condición
en `modelos/cnn_muestras/<subject>/<session_id>/`. Los registros incompletos no
habilitan entrenamiento. Un identificador diferente no garantiza por sí solo
independencia real: la condición debe corresponder a la captura realizada.

Pulse **Validar dataset** para actualizar la revisión y **Ver diagnóstico** para
consultar el detalle. La pantalla principal muestra un resumen y la tabla de
empleados indica las sesiones faltantes y las confusiones históricas. Entrenar
queda deshabilitado mientras el informe no cumpla los mínimos; el entrenador
repite todas las comprobaciones antes de cualquier ajuste de pesos.

El entrenamiento futuro parte de una CNN nueva y usa EarlyStopping,
ModelCheckpoint y ReduceLROnPlateau, conservando el mejor modelo por val_loss.
La cámara, las capturas y el dataset comparten YuNet, alineación por landmarks,
gris 100×100 y normalización float32 entre 0 y 1. El mapping persistido tiene
16 salidas, índices consecutivos y etiquetas únicas que coinciden con SQL.
Los umbrales se derivarán del conjunto de calibración y se comprobarán en el
conjunto final; la aceptación exige score, margen y evidencia temporal.

Las confusiones 02→09, 04→03 y 06→10 **siguen pendientes**. No se encontraron
duplicados de contenido entre las clases revisadas, pero eso no confirma la
identidad humana ni descarta etiquetas equivocadas. No se cambiaron etiquetas.
No hay accuracy final nueva, medición final de falsos positivos, threshold ni
margin aprobados, ni matriz final nueva. Tampoco se acreditó un conjunto de
personas desconocidas; las clases inactivas no se consideran desconocidos
automáticamente. Las cifras de evaluaciones anteriores que aparecen más abajo
son antecedentes y no acreditan el protocolo de sesiones vigente.

Para repetir únicamente la auditoría:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.revisar_cnn dataset
```

Pasaron 60 comprobaciones automáticas y la revisión de la interfaz real:
resumen breve, detalle, estados 0/4 y 1/4 y bloqueo del entrenamiento. No se
ejecutó captura con personas, entrenamiento ni una evaluación independiente nueva.

<a id="inicio"></a>

Documentación unificada del proyecto. Instalación, funcionamiento, arquitectura,
mantenimiento e informes se reúnen aquí. Los registros de entregas anteriores
se conservan como antecedentes y pueden contener cifras o estados ya superados.

Aplicación de escritorio para un almacén de taller de mecánica: SQL Server,
Tkinter/ttkbootstrap, JARVIS por texto y voz, reconocimiento facial y análisis
de stock. El inicio es directo, sin cuentas de acceso de aplicación.

## Instalación y ejecución

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

`main.py` es el punto de entrada de escritorio. La conexión se configura en
`core/database.py`: `MSI\SQLSERVER`, `InventarioIA2`, ODBC Driver 17 y autenticación
de Windows. La limpieza no modifica datos de SQL Server.

## Base de datos

### Historial operativo vigente: migración 007

El diagnóstico previo encontró 360 movimientos conciliados, del 08/10/2025 al
02/10/2026. Todos estaban fuera del horario habitual y ningún producto alcanzaba
cinco días de consumo reciente. El problema era la distribución operativa del
historial preparado para la demostración, no una discrepancia del stock.

Se regeneró el historial de manera controlada, con respaldo nativo verificado y
copias fechadas de movimientos, detalles, alertas, existencias y hallazgos anteriores.
La versión `007_normalizacion_historial` es independiente de la reorganización 006.
No representa operaciones históricas verificadas de un taller real: son los registros
preparados para el desarrollo académico, según el alcance confirmado por el equipo.

El resultado de la carga es **500 movimientos**, del **29/06/2026 al 13/10/2026**:

| Tipo | Cantidad |
|---|---:|
| Entrada | 152 |
| Salida | 318 |
| Transferencia | 0 |
| Ajuste entrada | 13 |
| Ajuste salida | 17 |

Predominan las salidas (63.6%); los ajustes son el 6%. Hay 14 operaciones fuera de
horario (2.8%). No se añadieron transferencias porque las 24 posiciones ya están
ocupadas y el modelo vigente mantiene una existencia por producto. Las cantidades
se basan en familia, unidad, stock y frecuencia; las entradas cubren reposiciones
de consumos planificados y cada secuencia termina exactamente en su saldo conservado.
Los empleados son los activos de la base, con mayor frecuencia para cargos operativos.

`stock_anterior` y `stock_nuevo` representan stock **por ubicación**, como en
`inventory/movimientos.py`. Antes de la fecha de reorganización se utilizan los identificadores
anteriores; después, los activos. No se trasladó retroactivamente el pasado a los
estantes nuevos. El saldo al momento de la reorganización coincide con su respaldo.

Las 24 existencias, cantidades, posiciones y productos se conservaron. El stock
total antes y después es **1105.00**. Para cada producto el stock inicial del período
es su saldo conservado, y entradas + ajustes de entrada − salidas − ajustes de salida
tienen balance neto cero. `sql/verificar_historial_inventario.sql` muestra los valores
iniciales, totales y resultado `COINCIDE` para los 24 productos, junto con los errores
de secuencia, cantidades, fechas, ubicaciones y empleados. Todos los contadores de
error quedaron en cero; siguen existiendo 12 niveles y 24 posiciones asignadas.

El motor real de predicción obtuvo historial suficiente para **17 productos**:
filtros de aceite/aire/combustible, bujía, pastillas de freno, banda serpentina,
rodamiento, fusible, los cinco lubricantes/consumibles LUB y los cuatro productos
de tornillería TOR. Los resultados calculados fueron 6 BAJO, 7 MEDIO, 1 ALTO y
3 CRÍTICO; siete herramientas/equipos conservan datos insuficientes. Las cantidades
y riesgos no se insertaron como predicciones almacenadas.

`ai/anomalies/deteccion_anomalias.py` calculó **12 hallazgos** (2.4% del historial), comparando
cada candidato con movimientos anteriores. Los productos fueron perno de media
pulgada, filtros de aceite/aire/combustible, bujía, líquido de frenos, tornillo,
tuerca, arandela, refrigerante, grasa y aceite. No se insertaron scores arbitrarios
ni se atribuyó fraude a personas. El detector actual evalúa cantidades; la existencia
de horarios inusuales no acredita que esté implementada su detección automática.
Las alertas de stock, agotamiento próximo y cantidades inusuales se derivaron de
los datos y de las funciones actuales, sin duplicar tipos ni pendientes equivalentes.
Al verificar esta etapa quedaron 21 alertas: 5 de stock bajo, 1 de producto agotado,
3 de agotamiento próximo y 12 de cantidad inusual. Son resultados derivados de la
carga y pueden cambiar con las operaciones posteriores. Los 16 empleados activos
existentes participaron en el historial; no se añadieron ni modificaron personas.

Se verificaron Dashboard, reportes, la vista de ubicaciones y el botón Predecir.
También se ajustaron dos expresiones de JARVIS que no reconocía: “qué salió esta
semana” y “qué productos se están consumiendo más”. Se reutiliza el servicio de
movimientos y se distingue el número de salidas de la cantidad retirada; los totales
de consumo se comparan por unidad de medida. Texto y voz conservan la misma ruta.

Archivos de esta etapa:

- `sql/normalizar_historial_inventario.sql`: carga completa con respaldo, transacción,
  verificaciones y protección contra una segunda ejecución.
- `sql/verificar_historial_inventario.sql`: consultas de control sin modificar datos.
- `tools/preparar_historial_operativo.py`: prepara la carga según el catálogo
  y saldos revisados; no vuelve a preparar si la versión 007 ya está aplicada.
- `tools/normalizar_historial_inventario.py`: ejecuta SQL y reutiliza los motores
  de predicción, stock y anomalías antes de confirmar una transacción externa.
- `herramientas/plantilla_normalizacion_historial.sql`: plantilla utilizada por el
  preparador; debe ejecutarse el archivo completo preparado, no esta plantilla.
- `outputs/validaciones/diagnostico_historial_operativo.json`,
  `plan_historial_operativo.json` y `normalizacion_historial.json`: diagnóstico,
  planificación, controles, resultados y ruta del respaldo.

La carga ya está aplicada. Para verificar sin sustituir registros:

```powershell
python -m tools.normalizar_historial_inventario
```

El comando con `--aplicar` también comprueba la versión y no duplica los movimientos.
Para ejecutar una carga preparada en una instalación compatible se recomienda este
ejecutor: además de la transacción SQL, calcula las alertas predictivas y los hallazgos
con los motores del proyecto. Ejecutar el SQL desde SSMS aplica el historial y las
alertas de stock; los resultados de IA se calculan posteriormente desde sus módulos.
`sql/registros_inventario.sql` se exporta de la base vigente y conserva sus nuevas filas.
Las cifras de importación y validaciones anteriores que aparecen más abajo son
antecedentes de etapas previas, no el estado posterior a 007.

### Organización física vigente

La estructura activa es **6 estantes × 2 niveles × 2 posiciones = 24 espacios**.
Hay 12 ubicaciones activas, `E01-N01` a `E06-N02`, con `estante` 01–06 y `nivel`
01/02. Las seis ubicaciones de la exportación anterior se conservan inactivas,
con sus mismos códigos e identificadores, para mantener las referencias históricas.
La sección A y el pasillo 01 son generales; el mapa prioriza estante, nivel y posición.

| Ubicación | Posición 1 | Posición 2 | LEDs previstos |
|---|---|---|---|
| E01-N01 | REP-001 · Filtro de aceite · 20.00 | REP-002 · Filtro de aire · 30.00 | 01–02 |
| E01-N02 | REP-003 · Bujia · 53.00 | REP-004 · Pastillas de freno · 0.00 | 03–04 |
| E02-N01 | REP-005 · Banda serpentina · 7.00 | REP-006 · Rodamiento de rueda · 2.00 | 05–06 |
| E02-N02 | REP-007 · Filtro de combustible · 4.00 | REP-008 · Fusible automotriz · 125.00 | 07–08 |
| E03-N01 | LUB-001 · Aceite de motor 1 L · 53.00 | LUB-002 · Refrigerante 1 L · 30.00 | 09–10 |
| E03-N02 | LUB-003 · Liquido de frenos · 11.00 | LUB-004 · Grasa multiproposito · 36.00 | 11–12 |
| E04-N01 | LUB-005 · Limpiador de contactos · 3.00 | TOR-001 · Tornillo M8 · 166.00 | 13–14 |
| E04-N02 | TOR-002 · Tuerca M8 · 221.00 | TOR-003 · Arandela M8 · 220.00 | 15–16 |
| E05-N01 | TOR-004 · Perno de media pulgada · 85.00 | HER-001 · Juego de llaves combinadas · 4.00 | 17–18 |
| E05-N02 | HER-002 · Destornillador plano · 11.00 | HER-003 · Destornillador Phillips · 8.00 | 19–20 |
| E06-N01 | HER-004 · Alicate universal · 6.00 | HER-005 · Llave para filtro · 8.00 | 21–22 |
| E06-N02 | EQP-001 · Gato hidraulico · 1.00 | EQP-002 · Multimetro digital · 1.00 | 23–24 |

Las cantidades de esta tabla corresponden a la reorganización; las pantallas siempre
consultan SQL y reflejan las operaciones posteriores. El stock total antes y después
fue **1105.00**, sin cambios por producto. Los 360 movimientos y las 6 alertas quedaron
sin modificaciones. Un producto agotado conserva su posición y cuenta entre los dos
productos asignados al nivel; ocupación no equivale a unidades almacenadas.

`inventory/organizacion_fisica.py` centraliza las reglas, descripción humana y numeración LED.
`inventory/movimientos.py` valida y bloquea la ubicación dentro de la transacción antes de una
nueva asignación, entrada o transferencia. Si el producto ya está presente, admite
entradas, salidas y ajustes. SQL protege posiciones 1/2, combinaciones estante/nivel,
duplicados producto/ubicación y capacidad mediante índices, CHECK y trigger. La posición
1 se dibuja a la izquierda y la 2 a la derecha. No se implementó conexión de hardware.

`sql/reorganizar_estantes.sql` contiene respaldo nativo, respaldos fechados de ubicaciones
y existencias, redistribución, verificaciones y TRY/CATCH con rollback. Su ejecución
es idempotente mediante `006_organizacion_fisica` en `inventario_migraciones`: repetirla
no vuelve a distribuir las cantidades. Se puede ejecutar desde SSMS o mediante:

```powershell
python -m tools.reorganizar_estantes
```

La reorganización ya está aplicada en esta instalación. `sql/verificar_estantes.sql` es
la consulta de control de ocupación y stock antes/después. El resultado y la ruta del
respaldo nativo están en `outputs/validaciones/reorganizacion_estantes.json`. Los
respaldos SQL `respaldo_ubicaciones_estantes` y `respaldo_existencias_estantes` conservan
el estado anterior; el último incluye destino y posición para conciliar el historial
anterior con la distribución actual sin reescribir movimientos ni atribuirlos a un empleado.

Mapa, ficha, formularios, reportes y consultas de JARVIS utilizan los datos de posición.
El mapa coloca Nivel 2 arriba y Nivel 1 abajo, e incluye los productos agotados. JARVIS
puede describir “Estante 1, Nivel 1, Posición 1”. La API usa los mismos servicios.
El importador de exportaciones anteriores bloquea su aplicación después de esta
migración para evitar que se repongan las ubicaciones antiguas sin posiciones.

Verificación: 13 casos de reglas/capacidad, recorrido de escritorio con 16 tablas,
conciliación de 360 detalles y comprobación del mapa con 6 tarjetas y 24 espacios.
Las operaciones SQL de verificación se revierten; no dejan movimientos guardados.

### Fuente vigente de registros

La resolución de tipos de alerta está centralizada en `inventory/tipos_alerta.py`. La clave
`PROXIMO_AGOTARSE` identifica el concepto y se resuelve contra el catálogo activo
de SQL, normalizando tildes, mayúsculas y espacios. En esta instalación devuelve
el identificador 3, cuyo nombre registrado es `Proximo a agotarse`. No se insertan
tipos nuevos ni se supone que ese identificador sea igual en otra instalación.

La búsqueda exacta anterior en `ai/prediction/prediccion_stock.py` fallaba con la intercalación
`Modern_Spanish_CI_AS`. Ahora el cálculo se completa antes de intentar guardar una
alerta. Si la persistencia falla, se registra un aviso mediante logging y se conserva
el resultado; Análisis IA puede mostrar una advertencia sin cancelar la predicción.
Con datos insuficientes no se crean ni se cierran alertas de predicción. Una cobertura
válida, positiva y de hasta siete días puede generar una alerta; un producto ya agotado
no recibe una alerta de agotamiento futuro. Las alertas pendientes del mismo producto
y tipo se reutilizan, con bloqueo transaccional para evitar inserciones simultáneas.

Alertas de stock, movimientos, vencimientos y desactivación de productos comparten
el resolvedor. La lista de alertas muestra los tipos activos del catálogo y no depende
de una lista de nombres con tildes exactas. Se verificaron 12 casos de resolución,
aislamiento y persistencia, 13 casos de movimientos/estructura y el botón Predecir con
SQL real. El recorrido actual muestra datos insuficientes para el producto seleccionado,
sin el error anterior; se conservaron las seis alertas. Las alertas de los casos
controlados se revirtieron y no alteraron el catálogo ni el historial.

La carga vigente procede de `BD Actualizada con 24 productos y mas movimientos.sql`,
proporcionado por el desarrollador. Se sustituyeron los registros anteriores en
`InventarioIA2`, conservando su esquema y las ampliaciones requeridas por la aplicación.
La importación contiene 24 productos, 360 movimientos, 15 empleados, 6 ubicaciones,
5 categorías y 6 alertas del archivo. El stock total al importar es 1105.00.
Estas cantidades corresponden a la importación; pueden cambiar con nuevas operaciones.

Se verificaron las claves, los saldos de cada movimiento y las existencias finales.
El historial comienza con saldos ya existentes; no debe suponerse un saldo inicial cero.
Sus fechas abarcan del 08/10/2025 al 02/10/2026. No contiene lotes ni conteos; los
registros anteriores de esos módulos y sus hallazgos de anomalías se retiraron con
el historial sustituido. Las tablas se conservan para operaciones posteriores.
Con la ventana de predicción configurada al verificar esta carga, ningún producto
alcanzó el mínimo de días con salidas requerido. Se conservan los mensajes de datos
insuficientes; no se alteraron fechas ni umbrales para producir predicciones.

Antes de actualizar se realizó un respaldo nativo de SQL Server con COPY_ONLY y
CHECKSUM, comprobado mediante RESTORE VERIFYONLY. La ruta y firma SHA-256 de la
fuente se registran en `outputs/validaciones/actualizacion_desde_sql.json`.
La exportación original no se ejecuta completa porque contiene instrucciones para
crear la base, rutas de otra instancia y opciones de otra versión de SQL Server.

Para comparar otra exportación de la misma estructura, sin cambiar datos:

```powershell
python -m tools.actualizar_desde_exportacion_sql "C:\ruta\archivo.sql"
```

Agregar `--aplicar` respalda y sustituye los registros. Esta opción reemplaza el
historial vigente y sus dependencias; no es una carga incremental.
`tools/actualizar_desde_exportacion_sql.py` utiliza ahora este mismo importador y requiere una
exportación explícita. Los catálogos y cargadores anteriores se conservan como
antecedentes en `backups/archivo_cargas_anteriores/version_anterior_20261012/`.
Las secciones históricas del README con referencias INV-ACT/INV-SAL ya no describen
la carga vigente.

`sql/registros_inventario.sql` contiene los INSERT actuales de catálogo,
ubicaciones, empleados, movimientos, lotes y saldos finales. Ejecútalo completo
en SQL Server Management Studio. Omite registros idénticos y revierte la carga
si encuentra diferencias; no debe sumarse el mismo stock nuevamente.

Las migraciones se conservan en `migrations/`. Para una instalación que aún
no tenga aplicadas las ampliaciones:

```powershell
python -m tools.migrar_inventario
python -m tools.migrar_anomalias
```

La migración 003 permite retirar la antigua estructura de acceso; no se ejecuta
automáticamente. **`sql/Base de Datos.sql` es un esquema histórico de InventarioIA1,
no una copia completa del esquema actual de InventarioIA2.** Requiere revisión
antes de preparar una instalación nueva.

Mantenimiento desde la raíz:

```powershell
python -m tools.inspeccionar_esquema
python -m tools.verificar_inventario
python -m tools.generar_registros_sql
```

Las dos primeras escriben en `outputs/validaciones/`. La última actualiza el
archivo de INSERT leyendo SQL Server, sin modificar la base.

## Configuración y recursos

- `core/config_manager.py` administra `config_sistema.json`.
- `reconocimiento_facial_config.json` mantiene compatibilidad del motor facial.
- `intenciones_jarvis.json` contiene el catálogo editable del NLP.
- `modelos/` contiene YuNet, SFace, galería facial, CNN y etiquetas.
- `Clasificacion/rostros/DataSet01/data/` conserva imágenes para entrenamiento y regeneración.
- `modelos_voz/vosk-model-small-es-0.42/` debe contener el modelo Vosk español.
- `cache_voz/` y `evaluacion_facial/` se generan al utilizar esas funciones.

El inicio no descarga modelos. Instalación facial explícita:

```powershell
python -m tools.evaluar_reconocimiento_facial instalar-modelos
```

YuNet + SFace es el motor principal; CNN sigue disponible como alternativa.
La calibración independiente es necesaria para aceptar identidades. La interfaz
conserva **Regenerar base**, que utiliza `ai/facial/diagnostico_facial_basico.py`.

## JARVIS

Texto y voz usan `agente_inventario.procesar_consulta`. **Hablar** captura con
sounddevice y Vosk; el texto reconocido aparece en el chat. Edge TTS y la
alternativa local pyttsx3 reproducen la respuesta. La escucha se suspende
mientras el asistente habla.

El NLP local utiliza scikit-learn, RapidFuzz y spaCy con alternativa ligera.
El modelo español opcional se instala con:

```powershell
python -m spacy download es_core_news_sm
```

Ollama es opcional, configurado por `OLLAMA_MODEL` y `JARVIS_LLM_TIMEOUT`.
Si falla, continúa el NLP local. Las herramientas Python validan entidades
y consultan SQL con parámetros; el modelo no ejecuta SQL.

La API opcional se conserva en `jarvis/api_jarvis.py`:

```powershell
python -m uvicorn jarvis.api_jarvis:app --host 127.0.0.1 --port 8000
```

## Documentación y comprobaciones

- [Arquitectura e integración](#arquitectura).
- [Inventario, lotes y conteos](#inventario).
- [Reconocimiento facial y calibración](#facial).
- [Anomalías, estado y configuración](#operativos).
- [Reportes PDF y Excel](#reportes).
- [Informe funcional](#informe-funcional).

Entregables Word: `docs/entregables/`. Respaldos: `backups/`.
Las exportaciones de usuario conservan su carpeta configurada, inicialmente
`reportes_exportados/`.

Las regresiones reutilizables están en `pruebas/`; las dependencias adicionales
solo se necesitan para mantenimiento:

```powershell
python -m pip install -r pruebas/requirements.txt
python -m unittest discover -s tests -p "probar_*.py" -v
```

Los casos SQL requieren conexión y revierten los registros que crean.
`python -m tests.probar_voz` es una comprobación manual con micrófono y altavoces.



## Índice técnico

- [Motor conversacional JARVIS: memoria, seguimiento y validación](#jarvis-conversacional).
- [Cuestionario de modelado: 53 respuestas verificadas el 11/10/2026](#cuestionario-modelado).
- [Arquitectura e integración](#arquitectura)
- [Inventario, lotes y conteos](#inventario)
- [Reconocimiento facial y calibración](#facial)
- [Reportes PDF y Excel](#reportes)
- [Anomalías, estado y configuración](#operativos)
- [Informe funcional conservado](#informe-funcional)
- [Organización y limpieza del proyecto](#limpieza)
- [Integración de los cuatro módulos](#integracion-historica)
- [Registro de implementación del Dashboard](#dashboard-historico)
- [Registro de rediseño de interfaz](#interfaz-historica)
- [Registro de actualización del inventario](#carga-historica)
- [Registro de diagnóstico facial](#facial-historico)

<a id="arquitectura"></a>

## Arquitectura e integración

`main.py` llama a `interfaz.iniciar_aplicacion`. La interfaz compone páginas y
callbacks de los módulos especializados. `ui/ui_theme.py` centraliza paleta,
tipografía y espaciado; `ui/ui_components.py` distribuye las acciones por ancho.
Trabajadores y colas mantienen audio, cámara y consultas fuera del hilo Tkinter.

Dashboard consulta inventario, empleados, movimientos, alertas, anomalías y
servicios. Un fallo de consulta no se transforma en una cantidad cero confirmada.
Productos y catálogos usan `inventory/productos.py` e `inventory/inventario_service.py`.
`inventory/movimientos.py` mantiene saldos y detalles en transacciones; `inventory/lotes_service.py`
gestiona lotes y `inventory/conteo_inventario.py` registra diferencias mediante ajustes.

### Mapa, JARVIS y predicción

`inventory/mapa_almacen.py` consulta ubicaciones y existencias vigentes. Agrupa almacén,
zona y pasillo, con estantes y niveles registrados. `mostrar_producto_en_mapa`
es el acceso común de Productos y JARVIS. Los movimientos pueden mostrar origen
y destino; una transferencia no cambia el stock global.

El mapa es lógico, sin escala física ni capacidad inventada. Un producto puede
tener múltiples ubicaciones. Los datos ausentes se señalan, sin deducirlos del
código. Selección y búsqueda utilizan texto y color.

Texto y voz pasan por `agente_inventario.procesar_consulta`. La respuesta incluye
texto, versión hablada, datos y acciones de interfaz. Tkinter consume y ejecuta
las acciones visuales. El contexto recuerda el producto para «¿Dónde está?» y
«¿Cuánto tiempo durará?». Los nombres ambiguos requieren aclaración; la
conversación no se persiste en SQL. `jarvis/jarvis_personality.py` centraliza respuestas.

`ai/prediction/prediccion_stock.py` es el motor común de JARVIS, interfaz y reportes.
Calcula consumo diario observado de salidas, incluyendo días sin consumo dentro
del período disponible. Ventanas: 7, 30, 60 y 90 días. Entradas, ajustes y
transferencias no se interpretan como consumo global. Un historial insuficiente
no produce una fecha ni cobertura inventadas.

### Reconocimiento y voz

El motor principal usa YuNet + SFace en `ai/facial/pipeline_facial.py`, con calidad,
tracking y consenso. Registro y reconocimiento comparten landmarks, alineación
BGR y embeddings normalizados. No se mezclan vectores CNN y SFace.
`ai/facial/pipeline_facial_basico.py` sigue siendo una alternativa diagnóstica explícita.

`ai/facial/diagnostico_facial_basico.py` es producción: **Regenerar base** lo importa
para reutilizar fotos y diagnosticar coherencia. `ai/facial/reconocimiento_cnn.py`,
`ai/facial/modelo_cnn.py` y `ai/facial/entrenar_cnn_rostros.py` conservan la alternativa CNN.
El modelo anterior es un respaldo del entrenamiento y se mantiene.

Galería y calibración son recursos distintos. Reprocesar una imagen del registro
no mide generalización. Se requieren sesiones independientes y desconocidos
para calibrar; no se ha demostrado alcance físico en metros. Las relaciones
históricas del dataset deben comprobarse contra las personas representadas.

Instalación, calibración y evaluación quedan en
`tools/evaluar_reconocimiento_facial.py`. Sus resultados se generan en
`evaluacion_facial/`; modelos e imágenes originales conservan sus rutas.
Vosk/sounddevice transcriben; Edge TTS/pyttsx3 sintetizan. La caché de voz
se regenera y se suspende la escucha durante la reproducción.

### Reportes, estado y configuración

`integrations/reporting/reportes.py` prepara una instantánea que presenta `integrations/reporting/reportes_ui.py`.
`integrations/reporting/report_render.py` la exporta a PDF/XLSX sin volver a consultar SQL.
`integrations/reporting/report_theme.py` comparte identidad visual y formatos. Movimientos se cuentan
como operaciones únicas; cantidades de distintas unidades no se suman.

`core/estado_sistema.py` conserva comprobaciones de SQL, modelos y servicios.
`ui/configuracion_ui.py` presenta la configuración y `core/config_manager.py` la valida
y persiste; sus responsabilidades son distintas. El JSON facial se conserva
por compatibilidad con el motor y sus herramientas.

### Organización y revisión manual

Los módulos activos siguen en la raíz para preservar imports y rutas.
`herramientas/` contiene mantenimiento; `pruebas/`, regresiones; `docs/`, guías
y entregables; `backups/`, copias conservadas. La clasificación individual
está en `inventario_archivos.json`.

`sql/Base de Datos.sql` corresponde a InventarioIA1 y no refleja íntegramente
InventarioIA2. En `ai/facial/rostros_empleados.py`, una función antigua de configuración
referencia dos SQL ausentes: `configurar_reconocimiento_facial.sql` y
`migrar_auditoria_soft_delete.sql`. No es llamada por el inicio actual.
Se documenta esa limitación existente sin modificar funcionalidad.

`ai/facial/reconocimiento_facial.py` conserva una API de compatibilidad cubierta por
regresión y un flujo LBPH sin uso visible: requiere revisión antes de retirarlo.
No se encontraron fuentes ni referencias activas de AWS o ESP32; sus carpetas
contenían solo bytecode antiguo.

<a id="inventario"></a>

## Inventario, lotes y conteos

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Implementación sobre SQL Server `InventarioIA2`, reutilizando los datos y servicios existentes. No incluye cuentas, roles, permisos, login ni auditoría de aplicación.

### Análisis previo y compatibilidad

La base tenía once tablas: productos, categorias, ubicaciones, existencias, movimientos, detalle_movimientos, tipos_movimiento, empleados, alertas, tipos_alerta y rostros_empleados.

Los productos ya tenían código, nombre, descripción, categoría, unidad en texto, precio, stock mínimo, estado y fechas. No tenían una columna de stock. El stock estaba correctamente separado por producto/ubicación en `existencias`; los movimientos tenían una cabecera con empleado responsable y detalles con cantidades y origen/destino. Las cantidades eran enteras, las unidades del formulario eran una lista Python y algunas sumas incluían ubicaciones inactivas.

Las categorías y ubicaciones ya eran catálogos SQL con baja lógica. No existía tabla de proveedores ni módulo de exportación de inventario. Se mantienen sus arquitecturas y no se agregan proveedores, lectores de barras/QR, exportación ni acciones de escritura por voz.

`core/database.py` conserva la conexión local de transporte a SQL Server. No existe autenticación de usuarios en la aplicación. El empleado de un movimiento identifica al responsable operativo; no es una cuenta de acceso.

### 1. Tablas modificadas

| Tabla | Cambios |
|---|---|
| productos | FK id_unidad_medida, control_lotes, codigo_barras, codigo_qr, imagen_producto; stock_minimo DECIMAL(18,3), unidad_medida NVARCHAR(80), índices de nombre/categoría y código único global |
| ubicaciones | almacen y zona opcionales |
| existencias | cantidad DECIMAL(18,3), conservando sus filas e índice único producto/ubicación |
| movimientos | id_motivo y referencia opcionales; índice de fecha/tipo |
| detalle_movimientos | cantidades y saldos DECIMAL(18,3), costo_unitario DECIMAL(18,2) opcional e índice de producto/movimiento |
| alertas | relación opcional id_lote |
| tipos_movimiento | catálogo de Ajuste entrada y Ajuste salida, si faltaban |
| tipos_alerta | tipos de lote próximo a vencer y lote vencido, si faltaban |

Categorías, empleados y rostros conservan sus estructuras. No se recrearon productos ni existencias. Las restricciones originales de cantidades se restauran al ampliar los tipos.

`estado` sigue siendo el campo almacenado que representa activo; `precio` sigue siendo el precio almacenado. `activo` y `precio_unitario` son alias de lectura en `vw_inventario`, evitando duplicar esos datos. `id_unidad_medida` es la relación canónica al catálogo; `unidad_medida` se conserva como texto de compatibilidad y se actualiza desde el servicio al cambiar producto o nombre de unidad.

### 2. Tablas nuevas

| Tabla | Finalidad |
|---|---|
| unidades_medida | Nombre, abreviatura y actividad; incluye las unidades existentes y las semillas SQL solicitadas |
| motivos_movimiento | Nombre, tipo de movimiento y actividad |
| lotes | Producto, código de lote único por producto, fecha de ingreso, vencimiento opcional y actividad |
| existencias_lotes | Cantidad de cada lote por ubicación |
| detalle_movimiento_lotes | Relación entre detalles históricos y lotes |
| conteos_inventario | Ubicación, empleado responsable, fecha y estado BORRADOR/APLICADO |
| detalle_conteos | Cantidades del sistema/físicas, producto/lote y movimiento de ajuste generado |
| inventario_migraciones | Versión aplicada del esquema |

Vistas nuevas: `vw_stock_producto` y `vw_inventario`. No se creó otra tabla `producto_ubicacion`: `existencias` ya cumple esa función.

### 3. Migración

[migrations/004_mejoras_inventario.sql](migrations/004_mejoras_inventario.sql) es aditiva, transaccional e idempotente. Se aplica con todos los lotes GO en una misma conexión mediante:

```powershell
.\.venv\Scripts\python.exe -m tools.migrar_inventario
.\.venv\Scripts\python.exe main.py
```

Ya fue aplicada y repetida correctamente en la base actual. Si encuentra códigos históricos duplicados, no los elimina ni renombra: el índice único hace fallar la migración y se revierte para corregir la causa explícitamente.

### 4. Archivos modificados

`inventory/productos.py`: APIs existentes conservadas y conectadas al inventario ampliado; desactivación sin borrar historia y protección contra borrar existencias positivas.

`inventory/movimientos.py`: motor transaccional decimal, lotes, costos, referencias, motivos, ajustes y filtros históricos.

`ui/interfaz.py`: nueva pantalla Productos, ficha, formularios de movimientos, filtros históricos y pantalla Conteo de inventario; las pantallas anteriores permanecen.

`inventory/alertas.py`: stock de ubicaciones activas, actualización del mensaje de alertas existentes y refresco de vencimientos.

`ai/prediction/prediccion_stock.py`: días naturales, suficiencia de información y objetivo de reabastecimiento explícito.

`ai/anomalies/deteccion_anomalias.py`: cantidades decimales sin truncarlas a enteros y corrección del campo de fecha al insertar alertas.

`jarvis/agente_inventario.py`: stock activo coherente y nuevas consultas de ubicaciones, mayor stock, movimiento mensual y orden de agotamiento estimado.

`ui/dashboard.py`, `probar_dashboard.py`, `tools/verificacion_ui/verificar_interfaz_visual.py` y `README.md`: indicadores, secciones nuevas y verificación/documentación actualizadas.

### 5. Archivos nuevos

`inventory/inventario_service.py`, `ui/inventario_ui.py`, `inventory/lotes_service.py`, `inventory/conteo_inventario.py`, `migrar_inventario.py`, `probar_inventario.py`, `migrations/004_mejoras_inventario.sql` y este informe.

### 6. Stock

Fuente de verdad: SUM(existencias.cantidad) de filas vigentes y ubicaciones activas/vigentes. El stock total no se almacena en productos. La vista central es `vw_stock_producto`; `vw_inventario` agrega catálogo, unidad, estado y valor.

Estados: AGOTADO si stock=0; CRÍTICO si 0<stock<=mínimo/2; BAJO hasta el mínimo inclusive; NORMAL por encima; INACTIVO si el producto está desactivado. Se muestran texto y color. Los filtros incluyen todos los activos, con stock, stock bajo, agotados e inactivos, más categoría, almacén, zona y ubicación.

Las búsquedas parametrizadas cubren código, nombre, descripción, categoría y código de ubicación; son insensibles a mayúsculas y acentos. El código puede escribirse o generarse como PRO-000001 y siempre debe ser único.

El valor es stock × precio registrado. El sistema anterior no distinguía costo de venta: se etiqueta así para no presentar una valoración contable de costos que no existe. El costo opcional de compra se guarda en el detalle de entrada y no sobrescribe automáticamente el precio. El stock agregado suma cantidades; al combinar productos con unidades diferentes es un indicador operativo, no una conversión física entre litros, metros y unidades.

### 7. Entradas

Producto activo, empleado, cantidad positiva decimal, destino activo, motivo, observación, referencia opcional y costo unitario opcional. En productos controlados se indica lote y vencimiento opcional. Crear el producto no genera stock inicial: la entrada posterior crea la existencia y el movimiento juntos.

### 8. Salidas

Producto, empleado, cantidad, origen y motivo. No pueden superar el stock de origen ni el saldo del lote elegido. El mensaje incluye el saldo disponible. Para lotes vencidos se requiere confirmación explícita en el formulario; las salidas nunca se ejecutan desde una sugerencia FEFO.

### 9. Transferencias y ajustes

Se resta origen y se suma destino dentro de una transacción; origen y destino deben ser diferentes. La transferencia conserva el total. Los saldos de lote se trasladan conjuntamente, sin alterar la identidad del lote.

Un ajuste compara stock físico con stock registrado: registra únicamente la diferencia como Ajuste entrada/salida, siempre con detalle de movimiento y cantidades positivas. Si no hay diferencia, no inventa un movimiento de cantidad cero.

Las operaciones sobre un mismo producto se serializan mediante bloqueos transaccionales y bloqueo de sus filas. Un fallo en existencias, lote, detalle, alertas o conteo revierte todo el cambio de negocio.

### 10. Lotes, vencimientos, FEFO/FIFO

Son opcionales. Productos existentes siguen sin lotes. Cambiar el control de lotes exige estar sin stock; no se inventan lotes para repartir el stock anterior.

La cantidad de un lote se deriva de sus existencias por ubicación, sin guardar un segundo total en su cabecera. Cada movimiento verifica que la suma de lotes coincida con el saldo del producto en origen y destino.

Se muestra VENCIDO, PRÓXIMO A VENCER dentro de 30 días o VIGENTE, junto a fecha y días restantes. Sin fecha se muestra “No aplica”. FEFO ordena primero los vencimientos próximos; FIFO ordena por ingreso cuando no hay vencimiento. La sugerencia requiere selección explícita y no modifica stock. Un lote vencido sigue identificado como tal para poder gestionarlo con confirmación.

### 11. Conteo físico

Seleccionar ubicación y empleado, cargar productos/saldos de lotes, seleccionar una fila y escribir cantidad física. La tabla presenta sistema, físico y diferencia. Guardar borrador permite recuperarlo después; aplicar ajustes requiere confirmación.

Los borradores son inmutables: para corregir se recarga la ubicación y se guarda otro. La aplicación vuelve a comparar los saldos originales; si alguno cambió desde el conteo, rechaza el proceso y revierte también los ajustes previos del mismo conteo. Un conteo aplicado no se puede ejecutar dos veces.

### 12. Alertas

Cada movimiento actualiza agotamiento y stock bajo dentro de su transacción. No duplica una alerta pendiente del mismo producto/tipo; actualiza mensaje y nivel. Al superar el mínimo resuelve las alertas de stock que ya no corresponden.

Los lotes producen alertas específicas por vencimiento, sin aplicarlas a productos sin control de lotes. Se actualizan después de movimientos y al consultar alertas, para reconocer el paso de los días. Reactivar/desactivar un producto desde el inventario actualiza sus alertas de stock pertinentes.

### 13. JARVIS

Conserva el catálogo y la resolución de productos existente, incluida la aclaración de nombres ambiguos. No registra movimientos por voz: el asistente existente solo tenía consultas.

Consultas añadidas: “¿Qué hay en la ubicación A3?”, “¿Qué productos se movieron más este mes?”, “¿Cuál es el producto con mayor stock?” y “¿Qué producto puede agotarse primero?”. Movimiento mensual suma entradas/salidas reales, sin transferencias. Las respuestas sin registros lo dicen explícitamente.

### 14. Predicción, consumo y dashboard

Se necesitan al menos cinco días con salidas. La serie incluye días sin salida hasta la fecha actual de SQL Server; no se trata cada día con actividad como si fueran días consecutivos. El promedio es consumo total / días naturales observados. La estimación divide stock por consumo promedio; la regresión usa esa misma serie temporal y se identifica como estimación.

Reabastecimiento: stock objetivo = máximo(stock mínimo, consumo promedio × días objetivo). Cantidad sugerida = máximo(objetivo − stock, 0). El horizonte por defecto es 30 días, visible en la ficha y configurable en el servicio. Sin información suficiente no se propone cantidad.

El dashboard incluye valor a precio registrado y movimientos del día, además de indicadores existentes; muestra productos críticos, menor stock, últimas entradas/salidas y gráficos reales. Análisis de rotación permite 7/30/60/90 días, top diez de consumo y productos sin movimientos en el periodo. La rotación contable se muestra como insuficiente porque no existe una serie histórica del inventario promedio a costo.

### 15. Pruebas y datos conservados

70 pruebas aprobadas: 22 nuevas de inventario real en SQL Server y 48 de dashboard, reconocimiento facial, voz y JARVIS. Las fixtures SQL usan transacciones y puntos de restauración; se revierten todas sus filas.

Se probaron categoría, unidad, producto, entrada, salida, transferencia, stock insuficiente, decimales, alertas y resolución, estados, ajuste, conteo físico, conteo obsoleto, reversión de varios ajustes, lotes y transferencia, vencimiento con confirmación, FEFO sin salida automática, búsqueda/filtros, inactivos con historia, ubicación inactiva, costo/referencia/motivo, códigos únicos, JARVIS y predicción con datos reales temporales.

Prueba 100/20/30: A=50, B=30, total=80. Una alerta que falla revierte el movimiento entero. La revisión visual cubrió 27 vistas (nueve pantallas × tres resoluciones), 17 formularios y la cámara, sin errores de callbacks ni botones recortados. Una consulta real de JARVIS respondió el stock existente.

Se verificaron después las filas originales: cuatro productos, cinco categorías, seis ubicaciones, cinco existencias, 16 empleados y 16 relaciones faciales. Stock conservado: motores 15, rodamientos 30, taladros 8, tornillos 100, total 153. Continúan cero movimientos, cero lotes y cero conteos reales hasta que la persona los registre. Los saltos en IDs de SQL Server tras rollback son normales y no equivalen a registros de prueba persistentes.

```powershell
.\.venv\Scripts\python.exe -m unittest probar_inventario probar_dashboard probar_pipeline_facial probar_integracion_voz probar_cobertura_jarvis
.\.venv\Scripts\python.exe -m tools.verificacion_ui.verificar_interfaz_visual
```

No se entrenó ni recalibró el reconocimiento facial, ni se introdujeron datos de consumo artificiales en la base permanente.

<a id="facial"></a>

## Reconocimiento facial y calibración

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


### Estado de la entrega

Se integró un motor local YuNet + SFace al escáner, registro y autenticación existentes.
Los modelos oficiales están instalados y verificados por SHA-256. No se añadieron
paquetes a requirements.txt: se reutiliza OpenCV (FaceDetectorYN/FaceRecognizerSF),
NumPy, Pillow, Tkinter y los servicios SQL actuales.

La galería nueva está vacía. No se migraron automáticamente las fotografías Yale
como identidades de empleados. Hay que registrar muestras supervisadas de empleados
reales y calibrar con conocidos y desconocidos antes de habilitar aceptación.
Hasta entonces, una cara con calidad suficiente se muestra como SIN_CALIBRAR.
La CNN anterior y el modelo LBPH permanecen disponibles explícitamente.

### Arquitectura anterior y limitaciones encontradas

- Cámara solicitada a 640×480; Haar trabajaba sobre un frame reducido al 50%.
- Un único rostro por escena; varias personas impedían reconocimiento.
- Recorte gris con margen del 15%, resize directo a 100×100 y escala [0,1].
- CNN propia: tres bloques Conv/MaxPool, Dense64 y softmax por subject.
- Threshold softmax 0.65, voto de tres coincidencias en cinco predicciones.
- El historial no tenía Track ID; podía mezclar evidencia entre personas.
- Captura de 30 imágenes, mínimo 20, con diferencia de píxeles respecto a la
  fotografía anterior; no comprobaba calidad antes de guardar.
- Split por imagen de entrenamiento/validación/prueba: fotografías de una misma
  sesión pueden estar muy correlacionadas. Accuracy cerrada no mide rechazo de desconocidos.
- LBPH + Haar permanecía como implementación separada de autenticación.
- El dataset contiene Yale Face Database y capturas históricas. Su Readme acredita
  15 sujetos públicos; esos sujetos no deben confundirse automáticamente con empleados reales.

Los contratos SQL, etiquetas subjectXX, funciones de movimientos, alertas, JARVIS,
la ventana de cámara y la captura del último frame son reutilizados.

### Arquitectura nueva

Fuente USB / archivo / IP-RTSP → captura del último frame → cola de tamaño uno →
YuNet → asociación por Track ID y flujo óptico entre detecciones → calidad en
píxeles originales → recorte con margen → alineación con cinco landmarks →
SFace → embedding L2 normalizado → galería con múltiples muestras por empleado →
threshold y margen calibrados → consenso temporal → identidad validada contra SQL.

La vista puede reducirse para mostrarla; los recortes de reconocimiento provienen
del frame original. Se solicita 1920×1080 a webcams; se registra la resolución
real entregada. Las URLs usan FFmpeg con timeouts de apertura y lectura.

Se procesa una vista general acotada a 960 píxeles de lado y un tile nativo de
640 píxeles por ronda, con solape y NMS. Hasta cuatro ROIs de tracks permiten
reobtener caras pequeñas sin recorrer de nuevo todo un frame 4K. Detección cada
tres frames procesados o cada 0.25 s. Entre detecciones se utiliza flujo óptico
sobre landmarks; no se ejecuta SFace en cada frame de video.

La evidencia de un track expira, se borra ante baja calidad, desaparición o
asociación ambigua, y requiere al menos cuatro muestras válidas y 80% de consenso
en una ventana de siete. La puntuación estable usa las cuatro mejores muestras
por calidad. Un candidato distinto o por debajo de la política no hereda la
identidad reconocida. Las decisiones con retraso superior a 0.75 s se descartan.

La captura y la inferencia están separadas. La ventana recibe frames/info bajo
lock; los callbacks faciales de interfaz pasan por una cola consumida por after()
en el hilo Tk. Cierre y cancelación usan el lock y evento de cámara existentes.

### Modelos y comparación técnica

| Aspecto | CNN histórica | YuNet + SFace nuevo |
|---|---|---|
| Detector | Haar reducido | Detector neural YuNet + landmarks |
| Identidad | Clase softmax fija | Embeddings, comparación abierta |
| Empleado nuevo | Reentrenar todas las clases | Registrar muestras y recalibrar política |
| Desconocidos | Softmax puede dar alta puntuación a una clase incorrecta | Umbral, margen entre candidatos y evidencia temporal |
| Entrada | Gris 100×100 sin alineación | BGR alineado 112×112; normalización propia del modelo |
| Varias personas | Se rechazaba la escena | Tracks independientes; autenticación única se rechaza si hay varias caras |

YuNet es una alternativa compacta moderna a SCRFD/RetinaFace, elegida porque ya
está soportada por OpenCV y evita nuevas dependencias binarias. SFace es un
reconocedor por embeddings equivalente en finalidad a ArcFace, no una CNN propia
reentrenada sobre los empleados. Su precisión publicada en otros datasets no se
presenta como precisión de este almacén. Referencia: [tutorial oficial OpenCV](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html).

Modelos locales en modelos/facial_embeddings/:

- face_detection_yunet_2023mar.onnx: 232589 bytes,
  SHA-256 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4.
- face_recognition_sface_2021dec.onnx: 38696353 bytes,
  SHA-256 0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79.

La instalación solo descarga al ejecutar explícitamente instalar-modelos. No
hay descargas durante el inicio normal. Los recursos se verifican antes de cargar.
CPU es el backend predeterminado; CUDA es opcional si OpenCV fue compilado para ello.

### Calidad, tamaño y límites

Se mide tamaño original, varianza Laplaciana, iluminación media, proporción dentro
del frame, posición de landmarks, roll y asimetría horizontal de nariz/ojos como
aproximación de orientación. Estos indicadores son proxies, no una medición
completa de oclusión ni de pose 3D. Una cara demasiado pequeña, borrosa, oscura,
recortada o con ángulo excesivo no genera evidencia de identidad.

El mínimo inicial de 80 px por lado es una barrera provisional de calidad, no un
mínimo validado a distancia. La calibración ensaya mínimos 64, 80, 96 y 112 px con
las imágenes reales etiquetadas. El registro pide al menos 112 px. El experimento
de reducción de una imagen no establece un tamaño universal ni una distancia.

CERCA, MEDIA y LEJOS son bandas del tamaño aparente (≥240, 120–239 y <120 px).
No son metros. La distancia de evaluación es introducida y medida por el operador.

No se usa superresolución generativa: puede introducir detalles inexistentes.
El resize ocurre dentro de la alineación geométrica, no deforma arbitrariamente
el rostro. Se mantiene la normalización esperada por SFace; no se añadió CLAHE
agresivo ni gamma que cambie la distribución sin validación. Mala luz se registra
y se rechaza. Si se cambia el preprocesamiento, se requiere una nueva evaluación.

No hay detector separado de cuerpos/personas, reidentificación de personas cuando
el rostro desaparece, compensación de ángulos extremos ni detección de vida.
La implementación sigue rostros; no garantiza continuidad a través de oclusiones.
Para autenticación sensible, este sistema no valida resistencia a fotografías o pantallas.

### Registrar empleados y conservar compatibilidad

1. Abre Empleados y deja seleccionado embeddings.
2. Selecciona un empleado y pulsa Registrar rostro.
3. Completa las siete instrucciones: frontal, izquierda, derecha, arriba, abajo,
   expresión y distancia. Se piden 28 muestras, cuatro por instrucción, con
   calidad válida; se rechazan embeddings casi idénticos a cualquiera ya guardado.
4. Cambia realmente la pose dentro de las instrucciones; el texto de guía no
   certifica por sí solo que una pose se haya cumplido.
5. Las muestras alineadas, métricas y embeddings se guardan localmente. Se conserva
   el subject existente si ya estaba relacionado con el empleado en SQL.
6. El nuevo registro invalida cualquier calibración anterior por cambio de galería.

Una comprobación de continuidad contra la primera muestra usa 0.363 como referencia
publicada de SFace para detectar cambios grandes durante el registro supervisado.
Ese número NO es el threshold operativo de identificación ni sustituye supervisión.
El criterio 0.995 de similitud para evitar duplicados tampoco autoriza identidades.

Se conservan copias grises para comparar/reentrenar la CNN. Su entrenamiento ahora
usa aumentos moderados solo en entrenamiento: brillo, contraste, ruido, rotación,
desenfoque y degradación de resolución. Las métricas persistidas incluyen el reporte
de clasificación y matriz, pero siguen siendo una prueba cerrada por imagen.
Selecciona cnn explícitamente para comparar el escáner anterior. El fallback LBPH
se conserva como reconocer_empleado(motor="lbph").

La galería vincula subject y id_empleado. La comparación mantiene a todos los
candidatos en el ranking; desactivar al mejor candidato no reasigna al segundo.
Solo relaciones SQL activas con el mismo id permiten identidad. El escáner actualiza
el cache SQL cada cinco segundos y se detiene si esa actualización falla. La
función de autenticación revalida al empleado en SQL antes de devolverlo.
El reconocimiento no genera movimientos de inventario por su cuenta: devuelve
los mismos campos que consumía el resto del sistema.

### Evaluación real y selección del threshold

Comandos desde el proyecto, con .venv activado:

```powershell
python -m tools.evaluar_reconocimiento_facial estado
python -m tools.evaluar_reconocimiento_facial instalar-modelos
```

Registra primero empleados reales. Recoge sesiones diferentes para calibración
y prueba, incluyendo personas no inscritas, variadas condiciones y distancias
medidas de 1, 3, 5, 7 y 10 metros. No uses imágenes de registro como evaluación.

```powershell
python -m tools.evaluar_reconocimiento_facial capturar-pruebas evaluacion_facial/manifest.csv --identidad-real subject16 --distancia-m 3 --subset calibracion --sesion conocido-dia1-3m
python -m tools.evaluar_reconocimiento_facial capturar-pruebas evaluacion_facial/manifest.csv --identidad-real DESCONOCIDO --distancia-m 3 --subset calibracion --sesion desconocido-dia1-3m
python -m tools.evaluar_reconocimiento_facial capturar-pruebas evaluacion_facial/manifest.csv --identidad-real subject16 --distancia-m 3 --subset prueba --sesion conocido-dia2-3m
python -m tools.evaluar_reconocimiento_facial capturar-pruebas evaluacion_facial/manifest.csv --identidad-real DESCONOCIDO --distancia-m 3 --subset prueba --sesion desconocido-dia2-3m
```

subject16 es un ejemplo de argumento: usa el subject real asignado al empleado.
Repite para cada persona y distancia; no se crean datos inventados con estos ejemplos.
CSV requerido: archivo,identidad_real,distancia_m,subset,sesion. El capturador
guarda frames originales y anexa filas; Q termina. Mantén un solo participante
y evita personas secundarias en la imagen etiquetada. Los frames sin detección
se conservan para medir fallos. Comprueba manualmente todas las etiquetas.

```powershell
python -m tools.evaluar_reconocimiento_facial calibrar evaluacion_facial/manifest.csv
python -m tools.evaluar_reconocimiento_facial evaluar evaluacion_facial/manifest.csv --salida evaluacion_facial/evaluacion.csv
python -m tools.evaluar_reconocimiento_facial video --identidad-real subject16 --distancia-m 5 --salida evaluacion_facial/prueba5m.csv
python -m tools.evaluar_reconocimiento_facial video --identidad-real DESCONOCIDO --distancia-m 5 --salida evaluacion_facial/desconocido5m.csv
```

La calibración busca threshold, margen entre candidatos y tamaño mínimo sobre
scores observados. Por defecto exige cero falsas aceptaciones observadas y cero
asignaciones al empleado incorrecto, con recall conocido mínimo del 50%; después
comprueba la política elegida en sesiones de prueba independientes. Si no pasa,
no guarda ni activa una política nueva. Las sesiones no pueden estar en ambos subsets.
Se rechazan archivos repetidos y posibles coincidencias casi exactas con registro.
La política se vincula a hash de galería, modelos/pipeline y configuración; cambios
en galería, fuente, resolución, ROI o criterios de calidad invalidan su uso.

El mínimo técnico es 20 conocidos y 20 desconocidos aptos para el tamaño operativo en cada subset,
con cobertura de todos los subjects. Ese mínimo NO demuestra una FAR baja en la
población. Amplía las muestras a numerosas personas, sesiones y condiciones.
Para cero errores en n pruebas independientes de desconocidos se informa el límite
superior unilateral del 95%: 1 − 0.05^(1/n). Con 20 pruebas sigue siendo ~13.9%.
Con aproximadamente 300 independientes es ~1%. Frames consecutivos no son pruebas
independientes y no permiten esa interpretación estadística por sí solos.

Las salidas incluyen Precision, Recall, F1, accuracy, FAR sobre desconocidos,
FAR entre desconocidos aptos, FRR sobre conocidos, tasa de identidad incorrecta entre conocidos, matriz de
confusión, tiempos de inferencia y resultados agrupados por distancia manual.
También se registran resolución, tamaño original del rostro, calidad, blur,
iluminación, orientación, candidato, similitud y resultado.

La calibración de imágenes mide decisiones por muestra. Usa también video para
verificar consenso temporal, cruces y oclusiones; sus frames correlacionados no
son una estimación independiente de FAR. No actives decisiones automáticas de
inventario basadas solo en el porcentaje de imágenes acertadas.

### Configurar USB/IP/RTSP y depuración

reconocimiento_facial_config.json controla fuente, resolución solicitada, ROI,
backend, presupuesto de detección, calidad y estabilidad temporal.

```powershell
$env:INVENTARIO_VIDEO_SOURCE = "rtsp://servidor/ruta"
$env:INVENTARIO_FACE_ENGINE = "embeddings"
python main.py
```

La fuente también admite índice numérico o archivo. ROI es null o [x,y,ancho,alto]
en coordenadas del frame real. La interfaz muestra tracks, caja en píxeles,
similitud, tamaño aparente, calidad y estado; debug añade FPS de video, resolución,
candidato y threshold. Similitud coseno no es probabilidad porcentual.

### Pruebas realizadas y rendimiento medido

- 42 pruebas automáticas pasaron: calidad, landmarks inválidos, tracking y cruces,
  evidencia alternada, caducidad, rechazo sin calibración, múltiples muestras,
  relación con id SQL, calibración/holdout y regresiones de texto/voz JARVIS.
- Los tests de lógica usan datos sintéticos únicamente como fixtures de prueba;
  no se reportan como precisión del sistema.
- Modelos ONNX reales: detectaron una imagen Yale, alinearon a 112×112 BGR y
  extrajeron un embedding finito de norma L2 uno.
- Benchmark de degradación de subject01.normal.gif: ~10.6–14.5 ms por muestra
  con imágenes pequeñas. Artefacto: evaluacion_facial/benchmark.json. No mide
  identidad abierta, distancia ni video real; no activó calibración.
- Arranque de la aplicación y cierre automático con ventana oculta y consultas
  SQL reales: correcto fuera del entorno restringido. Tkinter/SQL no estaban
  accesibles desde la ejecución restringida; la comprobación normal sí pasó.
- Cámara local real: entregó 1280×720 aunque se solicitó 1920×1080.
- Prueba real de pipeline CPU durante cinco segundos: 43 frames procesados,
  8.6 FPS de procesamiento, 17.97 ms de pipeline en promedio, p95 52.09 ms.
  No hubo rostros detectados ni galería registrada. La media incluye seguimiento
  entre detecciones; NO representa rendimiento de identificación con personas.
  Artefacto: evaluacion_facial/rendimiento_camara_local.json.

No se midió precisión de empleados ni alcance de 1–10 m dentro del almacén.
No se seleccionó aún un threshold operativo validado con tus empleados.

```powershell
python -m unittest -v probar_pipeline_facial.py probar_integracion_voz.py probar_cobertura_jarvis.py
```

### Cámara para pruebas

Primero mide el rostro en el frame, no solo la resolución nominal de cámara.
Como objetivo inicial para ensayos, busca 80–112 px o más por lado en las zonas
que requieren reconocimiento; la política final se valida con tus pruebas.
Prueba una fuente 1080p o 4K real con lente varifocal/ajustable, exposición corta
para personas caminando y luz equilibrada. Reduce el campo de visión si necesitas
más detalle facial a distancia; una cámara panorámica de alta resolución no
asegura suficientes píxeles en cada cara. Evita un ángulo elevado extremo.

El diseño de vigilancia depende de densidad de píxeles, lente y escena, como
explican [Axis: densidad de píxeles](https://whitepapers.axis.com/es-es/pixel-density-based-on-iec-62676-4-2014)
y [Axis: lentes](https://whitepapers.axis.com/en-us/lenses-in-surveillance).
Sus referencias visuales humanas no son thresholds de SFace. La cámara actual
720p puede servir para pruebas cercanas; su alcance a 10 m debe medirse, no asumirse.

### Archivos de esta integración

| Archivo | Cambio |
|---|---|
| ai/facial/pipeline_facial.py | YuNet/SFace, calidad, galería, política y tracking temporal |
| ai/facial/reconocimiento_embeddings.py | Escáner concurrente, registro variado y contrato de identidad |
| evaluar_reconocimiento_facial.py | Instalación verificada, captura, evaluación, calibración y benchmark |
| reconocimiento_facial_config.json | Configuración del nuevo motor y cámara |
| ai/facial/reconocimiento_cnn.py | Fachada compatible, selección explícita del motor CNN anterior |
| ai/facial/reconocimiento_facial.py | Autenticación nueva con revalidación SQL; LBPH conservado |
| ai/facial/captura_rostros.py | Registro por embeddings por defecto; registro CNN explícito conservado |
| surveillance/camara_utils.py | Fuente independiente USB/archivo/IP, resolución alta y timeouts |
| ai/facial/rostros_empleados.py | Etiquetas de galería y CNN disponibles para empleados y JARVIS |
| ui/interfaz.py | Selector de motor, estado de calibración y callbacks por cola Tk |
| ui/ventanas_camara.py | Indicadores de similitud, tamaño, calidad, Track ID y debug |
| ai/facial/entrenar_cnn_rostros.py | Augmentation realista y métricas de comparación persistidas |
| probar_pipeline_facial.py | Regresiones de seguridad y prueba ONNX real |
| .gitignore | Capturas/resultados de evaluación locales |
| README.md | Enlace al procedimiento de reconocimiento facial |
| RECONOCIMIENTO_FACIAL.md | Este informe, medidas, limitaciones y procedimiento |
| modelos/facial_embeddings/*.onnx | Modelos oficiales locales verificados (ya excluidos por .gitignore) |

requirements.txt se conservó tal como estaba: no hizo falta agregar dependencias.
Los cambios previos del proyecto, incluido JARVIS por voz, se conservaron.

<a id="reportes"></a>

## Reportes PDF y Excel

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


### Arquitectura

`integrations/reporting/reportes.py` consulta los servicios existentes y prepara una instantánea filtrada con filas, indicadores, totales, notas y series de gráficos. `integrations/reporting/reportes_ui.py` muestra esa instantánea y la entrega a los exportadores. Cambiar los filtros exige generar nuevamente la vista previa. `integrations/reporting/report_render.py` produce PDF y Excel sin consultar SQL ni recalcular predicciones. `integrations/reporting/report_theme.py` centraliza la paleta del sistema, formatos, anchuras y colores de estado.

### Reportes disponibles

Inventario actual, stock bajo, agotados, entradas, salidas, transferencias, historial de movimientos, inventario por ubicación, productos por categoría, predicción de stock, anomalías, alertas, empleados, reconocimiento facial y resumen general.

Los filtros se habilitan según el reporte: producto, categoría, ubicación, almacén, fechas inclusivas, tipo de movimiento, estado, nivel y riesgo. Las fechas de entrada usan `YYYY-MM-DD`. El resumen ejecutivo utiliza movimientos de los últimos 30 días y hasta cinco registros por sección.

### PDF

Cabecera del sistema, título, fecha, filtros legibles, indicadores, tablas con encabezado repetido, filas alternas, ajuste de texto, estados destacados, totales y gráficos de barras. La orientación se determina por el número de columnas. Todas las páginas incluyen fecha y «Página x de y». No se añade un logotipo ficticio.

### Excel

Los reportes complejos incluyen RESUMEN y DETALLE; el resumen ejecutivo separa sus cinco secciones en hojas. Se conservan números y fechas como valores tipados, con moneda C$, cantidades decimales, tablas con filtros, paneles inmovilizados, formato condicional, ajuste de texto y configuración de impresión A4. Los textos de SQL se almacenan como texto, incluso cuando comienzan con `=`.

Los gráficos representan stock por categoría separado por unidad, operaciones por tipo, productos con mayor movimiento, riesgos, niveles de anomalía y tipos de alerta. No se generan gráficos de cantidades completamente nulas. Sus series también quedan disponibles en celdas del resumen.

### Integridad y límites

- El inventario global cuenta cada producto una vez y presenta todas sus ubicaciones. El filtro de ubicación selecciona productos; el reporte por ubicación muestra cantidades locales.
- Los totales no suman unidades incompatibles. La valoración utiliza el precio registrado y no representa costo contable.
- Los gráficos de movimientos cuentan operaciones únicas, no la suma de unidades diferentes. Las transferencias no son consumo.
- La predicción reutiliza `ai/prediction/prediccion_stock.py`, sin persistir resultados desde Reportes. Sin historia suficiente se informa la limitación y no se inventan fechas.
- Las anomalías son hallazgos ya registrados. La exportación no ejecuta ni guarda análisis; se actualizan desde el módulo Anomalías. El score no representa probabilidad de fraude.
- No existe un historial persistente de reconocimientos faciales; ese reporte lo indica explícitamente. Las fotografías registradas no se presentan como reconocimientos.
- La jerarquía de ubicaciones usa únicamente campos existentes. No se inventan posición ni capacidad.
- Los estados del resumen corresponden a comprobaciones de la sesión, no a monitoreo permanente.
- La vista previa conserva la instantánea exportada, pero la recopilación de varias consultas no constituye una transacción SQL con aislamiento de instantánea.

### Archivos y dependencias

La carpeta predeterminada es `reportes_exportados`, configurable en la configuración existente. Se sugieren nombres descriptivos y se añaden sufijos para evitar sobrescribir archivos, también durante la escritura final. Los archivos de revisión están en `verificacion_ui/reportes` y no son exportaciones de producción.

Se reutilizan ReportLab, openpyxl, Tkinter y ttkbootstrap existentes. No se necesitan migraciones, tablas nuevas ni cambios de autenticación.

### Validación

Ejecutar desde el entorno del proyecto:

```powershell
.\.venv\Scripts\python.exe -m unittest probar_reportes probar_modulos_operativos -v
```

Las pruebas verifican tipos y formatos Excel, tablas, filtros de impresión, gráficos, estados, separación de unidades, ausencia de consultas durante exportación, conservación de la instantánea, nombres sin sobrescritura, reportes vacíos, paginación y compatibilidad con consultas existentes. Las pruebas operativas requieren acceso a SQL Server.

<a id="operativos"></a>

## Anomalías, estado y configuración

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


La aplicación conserva el inicio directo y los módulos existentes. Las nuevas
pantallas se abren desde la navegación lateral: **Anomalías**, **Reportes**,
**Estado** y **Configuración**. El estilo sigue centralizado en `ui/ui_theme.py`.

### Archivos de esta etapa

Creación: `core/config_manager.py`, `config_sistema.json`, `ui/configuracion_ui.py`,
`ui/tareas_ui.py`, `ui/anomalias_ui.py`, `integrations/reporting/reportes.py`, `integrations/reporting/reportes_ui.py`,
`core/estado_sistema.py`, `ui/estado_ui.py`, `migrar_anomalias.py`,
`migrations/005_anomalias_funcionales.sql`, `probar_modulos_operativos.py`,
`requirements-dev.txt` y este documento.

Modificación: `ui/interfaz.py`, `ai/anomalies/deteccion_anomalias.py`, `jarvis/agente_inventario.py`,
`jarvis/asistente_voz.py`, `ai/facial/pipeline_facial.py`, `ai/prediction/prediccion_stock.py`,
`ui/prediccion_ui.py`, `ui/inventario_ui.py`, `ui/ui_theme.py`, `requirements.txt`,
`probar_integracion_voz.py`, `tools/verificacion_ui/verificar_interfaz_visual.py` y `README.md`.
Estos archivos reutilizan los servicios actuales de inventario, movimientos,
empleados, mapa, voz, reconocimiento y predicción.

### Detección de anomalías

El método principal es estadística explicable por **producto y tipo de movimiento**.
Cada candidato se compara exclusivamente con movimientos anteriores del mismo
grupo, dentro del período configurado. Entradas, salidas y transferencias se
analizan por separado. Los ajustes no se interpretan como salidas.

Se exige un mínimo configurable de antecedentes, inicialmente 10. Si existe
variación, el score mide desviaciones estándar sobre el promedio. Si la variación
es nula y el promedio es positivo, mide la razón cantidad/promedio. La explicación
identifica la métrica usada, cantidad, promedio, desviación y número de muestras.
El score **no es una probabilidad ni un porcentaje de certeza**. El límite inicial
es 3 y puede configurarse entre 2 y 6. Los niveles se asignan con límites 3, 4 y 6;
un score detectado menor que 3 corresponde a BAJA.

La tabla permite filtrar fecha, producto, tipo de anomalía, nivel y movimiento.
El detalle muestra origen, destino, referencia histórica y estado. Se puede marcar
PENDIENTE, REVISADA o JUSTIFICADA; justificar requiere una observación.
Reanalizar conserva los estados y no duplica hallazgos. Las salidas nuevas también
se evalúan dentro de su transacción y reutilizan las alertas existentes.

Análisis IA ejecuta este mismo motor en segundo plano. JARVIS puede responder
«¿Hay anomalías?», «¿Hubo movimientos extraños hoy?», «¿Cuál es la anomalía más
grave?» y explicar un movimiento indicando su número. JARVIS, la pantalla y los
reportes comparten la consulta de hallazgos persistidos y sus estados.

Se priorizó la **cantidad inusual** con respaldo histórico. No se añadieron reglas
especulativas sobre horarios autorizados, frecuencia esperada o fraude.
Isolation Forest permanece como función heredada separada y no decide las nuevas
clasificaciones. Cambiar sensibilidad afecta el análisis nuevo; las explicaciones
de hallazgos ya guardados se conservan para su revisión.

### Reportes

Hay 15 opciones: inventario actual, stock bajo, agotados, entradas, salidas,
transferencias, historial de movimientos, inventario por ubicación, productos por
categoría, predicción de stock, anomalías, alertas, empleados, reconocimiento facial
y resumen general.

`obtener_datos_reporte()` genera un conjunto filtrado común. Vista previa, **PDF**
y **Excel XLSX** consumen ese conjunto sin repetir consultas al exportar. Si cambian
los filtros, se exige una nueva vista previa. Cada opción ofrece solo filtros
aplicables. «Exportar predeterminado» usa el formato guardado en Configuración.

PDF incluye nombre del sistema, título, generación, encabezado configurable,
filtros, filas, totales y número de página; repite encabezados en tablas extensas.
Excel conserva cantidades numéricas y fechas, incluye filtros, encabezados fijos,
anchos adecuados y bandas suaves. Los textos de la base se escriben como texto,
incluso cuando empiezan por `=`. Los totales de stock se separan por unidad.
En inventario actual el stock es **total del producto**; para cantidades físicas
por ubicación se utiliza «Inventario por ubicación».

No existe historial facial persistente de reconocimientos en esta arquitectura.
Su reporte lo indica y queda vacío; las fotos y las relaciones de empleados no se
presentan como eventos de reconocimiento.

### Estado del sistema

Se muestran base de datos, cámara, micrófono, JARVIS, reconocimiento facial,
base facial, reconocimiento de voz, TTS, predicción y anomalías. SQL ejecuta una
consulta real y mide latencia; JARVIS verifica su procesador. Predicción y anomalías
comprueban sus motores con el historial disponible.

Cámara y micrófono indican **SIN VERIFICAR** hasta una prueba solicitada. Sus botones
abren y leen el dispositivo real, descartan lo capturado y liberan el recurso.
El audio y la cámara respetan los bloqueos de sus módulos actuales. La prueba de
TTS reproduce una frase y muestra el motor utilizado. Los resultados de pruebas
incluyen fecha/hora y describen una comprobación puntual, no vigilancia continua.

Los botones faciales y de voz cargan los modelos reales; la galería muestra ruta,
identidades y muestras. La disponibilidad de un archivo o paquete instalado no
equivale a haber comprobado el dispositivo. No se añadieron componentes ESP32 o
LED inexistentes. Todas estas operaciones usan workers y una cola consumida por
Tkinter en su hilo principal.

### Configuración

`core/config_manager.py` mantiene un esquema central, validación y escritura atómica
en **`config_sistema.json`**. Si falta el archivo, importa la configuración facial
anterior; si el contenido es inválido utiliza valores seguros para iniciar.
Restaurar valores predeterminados requiere confirmación y conserva el inventario.

Secciones: General, Inventario, Reconocimiento facial, JARVIS, Predicción,
Anomalías y Reportes. Se exponen únicamente opciones implementadas: nombre,
ventana/pantalla inicial, stock mínimo de productos nuevos, formato de fechas,
cámara/resolución/debug/intervalo/mínimo facial, micrófono, volumen, voz, velocidad
de pyttsx3, ruta Vosk, voz al iniciar, activación opcional, períodos, historial
mínimo, cobertura, sensibilidad y carpeta/formato/encabezado de exportación.

Idioma Español y tema flatly corresponden al soporte actual. El umbral facial
continúa ligado a una calibración validada; no se rebaja desde esta pantalla.
La salida de audio usa el dispositivo predeterminado del sistema operativo.
Los cambios de sesión, ventana, cámara o audio se aplican al volver a abrirlos o
reiniciar. Los períodos del motor y la configuración de exportación se consultan
al ejecutar la operación. El stock mínimo predeterminado solo afecta productos
nuevos y no modifica existencias ni mínimos registrados.

No se guardan credenciales de cámaras en el JSON. Una fuente con credenciales
puede seguir usando la variable existente `INVENTARIO_VIDEO_SOURCE`.

### Diseño e integración

Se reutilizan paleta, tipografía, paneles, tabla, botones y navegación de
`ui/ui_theme.py`, con tamaños compartidos, señales semánticas y controles consistentes.
La cabecera recibe los resultados reales del diagnóstico de SQL, cámara y JARVIS.
No se cambiaron los flujos de productos, movimientos, mapa ni las pestañas previas.

### Base de datos y dependencias

La migración **005** ya se aplicó en la instancia local. Agrega únicamente
`dbo.anomalias_inventario`, con referencia al detalle del movimiento, unicidad,
explicación y estado funcional. No elimina ni modifica información de inventario.
Es transaccional e idempotente. Para otra instalación:

```powershell
python -m pip install -r requirements.txt
python -m tools.migrar_anomalias
python main.py
```

Dependencias nuevas de la aplicación: **ReportLab** para PDF y **openpyxl** para
XLSX. `pypdf` pertenece a `requirements-dev.txt` y verifica los PDF en pruebas.
No se agregaron cuentas de aplicación, roles, permisos, login ni auditoría.

### Verificación y límites actuales

Se aprobaron **86 pruebas** de integración y regresión, incluidas estadísticas,
revisión persistente, filtros, configuración inválida, tipado de Excel, texto como
fórmula, paginación y liberación de cámara ante fallo. Los datos SQL de prueba se
revierten al terminar. Se comprobaron 15 pantallas a 1366×768, 1920×1080 y 1100×650,
17 formularios, siete categorías de configuración y vista previa real de reportes,
sin errores de callbacks ni botones recortados. PDF y XLSX se renderizaron y
revisaron visualmente con los datos existentes.

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest probar_inventario probar_dashboard probar_pipeline_facial probar_integracion_voz probar_cobertura_jarvis probar_integracion_central probar_modulos_operativos
python -m tools.verificacion_ui.verificar_interfaz_visual
```

Antes de cargar el [escenario de demostración](#carga-historica), la base carecía de
movimientos suficientes para predicción y anomalías. Ahora hay 244 movimientos
simulados identificables, sin presentarlos como actividad observada. La calibración facial
validada continúa pendiente. Las pruebas automatizadas de dispositivos usan
dobles; el diagnóstico de cámara, micrófono y reproducción debe ejecutarse con
el equipo físico desde Estado. Edge TTS conserva su dependencia de conexión;
pyttsx3 mantiene el fallback local. Las exportaciones grandes y diagnósticos
consultan los servicios existentes en segundo plano; no constituyen un monitor
continuo ni una detección de todas las clases posibles de anomalía.

<a id="informe-funcional"></a>

## Informe funcional conservado

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Fecha del informe: 3 de octubre de 2026.

### Finalidad

El sistema administra las existencias de un almacén, registra operaciones y ayuda
a consultar la información mediante una interfaz gráfica y el asistente JARVIS.
Combina inventario, ubicaciones, empleados, reconocimiento facial y análisis de
movimientos. Utiliza los datos registrados en SQL Server; cuando no hay información
suficiente debe indicarlo en lugar de producir cantidades, ubicaciones o
predicciones ficticias.

### Funciones por módulo

| Módulo | Qué hace |
|---|---|
| Dashboard | Resume productos activos, existencias, stock bajo, agotados, alertas, empleados, movimientos, anomalías y estados. Ofrece accesos rápidos, actividad facial de sesión y gráficos con datos disponibles. |
| Productos | Permite crear, consultar, editar y desactivar productos; manejar códigos, descripción, categoría, unidad, precio y stock mínimo; buscar, filtrar, abrir fichas y consultar ubicaciones. |
| Movimientos | Registra entradas, salidas, transferencias y ajustes con cantidades decimales, empleado responsable, origen/destino y observaciones. Admite motivos, referencias y costos opcionales de entrada. |
| Historial | Consulta las operaciones registradas con filtros y sus detalles. Conserva la relación entre producto, cantidad, fecha, empleado y ubicación. |
| Alertas | Presenta avisos de stock y vencimientos, además de alertas operativas existentes como cantidades inusuales. Permite consultar y atender avisos. |
| Empleados | Administra los datos de empleados y sus relaciones con las muestras faciales. El empleado responsable de un movimiento no representa una cuenta de acceso. |
| Análisis IA | Mantiene consultas y gráficos de consumo, predicción y análisis de anomalías sobre los datos reales. |
| JARVIS | Atiende consultas escritas y por voz, conecta inventario, mapa, empleados, reconocimiento, predicción y anomalías, y utiliza contexto temporal para preguntas de seguimiento. |
| Mapa | Representa las ubicaciones almacenadas en SQL, permite buscar productos, resaltar todas sus ubicaciones y consultar cantidades por ubicación. |
| Predicción | Estima consumo promedio, tendencia, cobertura en días, fecha aproximada de agotamiento y riesgo, cuando el historial lo permite. |
| Conteo de inventario | Compara cantidades físicas con las del sistema por ubicación. Permite conservar borradores y aplicar diferencias mediante movimientos de ajuste. |
| Anomalías | Detecta cantidades inusuales comparándolas con movimientos anteriores del mismo producto y tipo. Muestra razones, score, nivel y estados de revisión. |
| Reportes | Genera vistas previas filtradas y exportaciones PDF y Excel para inventario, movimientos, ubicaciones, predicción, anomalías, alertas, empleados y resumen. |
| Estado | Comprueba SQL y los motores del sistema; ofrece pruebas explícitas de cámara, micrófono, modelos y reproducción de voz, con resultados y fecha de comprobación. |
| Configuración | Mantiene opciones centrales de inventario, cámara, JARVIS, análisis, reportes y presentación, con validación y guardado persistente. |

### Cómo controla las existencias

La existencia se almacena por producto y ubicación. El stock total de un producto
se obtiene sumando las existencias vigentes de ubicaciones activas.

Crear un producto no genera existencias automáticamente: posteriormente se
registra su entrada. Una entrada incrementa cantidades; una salida las reduce;
una transferencia cambia su distribución entre ubicaciones sin representar
consumo global. Las operaciones se procesan con transacciones y validaciones para
evitar cantidades inválidas y salidas superiores a la disponibilidad.

Para productos que requieren control por lote se registran lotes, cantidades por
ubicación y vencimientos opcionales. El conteo físico permite corregir diferencias
mediante ajustes identificados como tales, conservando su relación con el conteo.

### JARVIS como asistente central

Las consultas escritas y la transcripción de voz utilizan el mismo procesador.
Por ejemplo, se puede preguntar cuántas unidades quedan, dónde está un producto,
qué productos tienen poco stock o qué movimientos fueron clasificados como
inusuales. Una consulta de ubicación puede abrir el mapa y resaltar resultados.

El contexto temporal permite continuar con «¿Dónde está?» o «¿Cuánto durará?»
después de identificar un producto. Si hay nombres similares, solicita aclaración.
No registra entradas ni salidas automáticamente por voz.

La voz usa Vosk para reconocimiento, sounddevice para captura y Edge TTS con
fallback local pyttsx3 para síntesis. Push-to-talk es el modo principal, con
activación opcional por «JARVIS». La escucha y reproducción se coordinan para
evitar eco y se ejecutan sin bloquear la interfaz.

### Reconocimiento facial

El motor principal utiliza YuNet para detección y SFace para embeddings, con
alineación y extracción coherentes entre registro y reconocimiento. Evalúa calidad,
seguimiento y evidencia temporal; admite estados de verificación y desconocido.
La CNN heredada permanece como alternativa separada.

Permite múltiples muestras por empleado, regeneración desde imágenes existentes
y fuentes de cámara USB, IP o RTSP. Confirmar identidades requiere una calibración
válida y una relación con un empleado activo. La similitud no representa un
porcentaje de certeza. No se ha validado precisión ni alcance físico en metros.

### Predicción y anomalías

La estimación principal de stock utiliza el promedio diario observado de salidas,
incluyendo días sin consumo dentro de la serie disponible. No considera entradas,
transferencias ni ajustes como consumo. Con historial suficiente calcula cobertura
y fecha aproximada; también puede recomendar cantidades mediante una fórmula de
consumo esperado, cobertura objetivo y stock mínimo. Son estimaciones, no garantías
de demanda futura.

Las anomalías se comparan con antecedentes del mismo producto y tipo de movimiento.
El score expresa desviaciones estándar sobre el promedio o una razón respecto a
este cuando la variación histórica es nula. No es una probabilidad de fraude.
Los hallazgos tienen explicación y estados PENDIENTE, REVISADA o JUSTIFICADA;
justificar requiere una observación. Se comparte la información con JARVIS y reportes.

### Reportes, configuración y presentación

PDF y Excel se generan a partir del mismo conjunto filtrado de la vista previa.
Incluyen identificación, fecha de generación, filtros y datos correspondientes.
PDF pagina las tablas; Excel conserva números y fechas como valores tipados.
Los totales de stock de los reportes se separan por unidad de medida.

La configuración se guarda de forma atómica en `config_sistema.json`. El archivo
`ui/ui_theme.py` concentra la identidad visual, tarjetas, tipografía y estilos. Las
operaciones nuevas de consulta y diagnóstico utilizan tareas en segundo plano y
actualizan Tkinter desde su hilo principal.

### Arquitectura y alcance

La aplicación está desarrollada en Python con Tkinter/ttkbootstrap y utiliza
SQL Server mediante pyodbc. Los módulos reutilizan servicios centrales de datos;
JARVIS consulta los mismos motores que las pantallas. ReportLab genera PDF y
openpyxl genera XLSX. El inicio se realiza ejecutando `python main.py`.

La aplicación abre directamente: no incluye usuarios, roles, permisos, login ni
bitácora de auditoría. Los empleados, movimientos y estados de anomalías son datos
operativos del almacén.

### Limitaciones y validación

- El mapa es una representación lógica, no un plano a escala. Capacidad y posición
  no están registradas en el esquema actual, por lo que no se inventan ocupaciones.
- La calibración facial validada continúa pendiente en la última revisión.
- Sin historial suficiente no se calculan predicciones ni se confirman patrones
  estadísticos. Ahora existe un [escenario de demostración](#carga-historica) con 244
  movimientos simulados; no representan actividad observada del almacén.
- No existe un historial facial persistente de reconocimientos exitosos. La
  actividad de sesión no sustituye un historial SQL; su reporte lo indica.
- Cámara y micrófono requieren comprobación física. Los estados representan
  verificaciones puntuales y no vigilancia continua de dispositivos.
- La detección nueva prioriza cantidades inusuales; no verifica todas las clases
  posibles de comportamiento anómalo.
- Edge TTS requiere conexión; pyttsx3 conserva una alternativa local.

En la última validación se aprobaron 86 pruebas de integración y regresión, además
de 45 comprobaciones de pantallas y 17 formularios. Se revisaron las exportaciones
PDF y Excel. Esto verifica los flujos probados; no acredita precisión facial o
predictiva en condiciones reales del almacén.

<a id="limpieza"></a>

## Organización y limpieza del proyecto

**Estado:** organización aplicada; eliminación masiva pendiente de aprobación.

- Archivos analizados: **8704**, excluyendo `.git`, `.venv` y metadatos del agente.
- Módulos alcanzables desde `main.py`: **46**, conservados en sus rutas.
- Archivos originales movidos: **29**.
- La eliminación general sigue pendiente de aprobación. La consolidación de Markdown está autorizada por separado; sus doce originales se guardan en un ZIP verificado.
- Documentos Markdown consolidados: **13** en `README.md`; los doce archivos separados se retiran después de verificar el respaldo.
- Conciliación extraída de la carga antigua: integrada en `tools/verificar_inventario.py`.

### Respaldo y bloqueo

El respaldo local `backups/limpieza/estructura_20261007_230847.zip` conserva **8.707 archivos**, con SHA-256 verificado individualmente. Incluye los originales anteriores a los movimientos.
La revisión automática rechazó la eliminación porque exige autorización de la lista exacta, pese a la solicitud general y al respaldo. La pregunta de aprobación está pendiente. No se ejecutó Remove-Item.
La lista completa y razones están en [plan_limpieza.json](docs/plan_limpieza.json) y [inventario_archivos.json](docs/inventario_archivos.json).
El ejecutor preparado es `herramientas/aplicar_limpieza.ps1`: comprueba respaldo, límites de ruta y presencia de los módulos activos antes de retirar archivos. Ejecutarlo únicamente después de aprobar la lista.

### Archivos conservados

Se conservaron todos los módulos de producción, la API opcional, configuraciones, requisitos, tres migraciones, `sql/Base de Datos.sql`, `sql/registros_inventario.sql`, modelos YuNet/SFace/CNN/Vosk, galería, etiquetas y fotos del dataset. No se modificó `.venv`.
La clasificación por archivo incluye recursos y respaldos. El árbol de imports está en [dependencias_proyecto.json](docs/dependencias_proyecto.json). Los imports dentro de funciones, callbacks y alternativas se incluyen. No se encontraron ejecuciones Python por importlib/subprocess en los módulos raíz; Estado usa find_spec para detectar paquetes instalados.

### Archivos movidos

| Origen | Destino |
|---|---|
| `probar_agente_avanzado.py` | `tests/probar_agente_avanzado.py` |
| `probar_cobertura_jarvis.py` | `tests/probar_cobertura_jarvis.py` |
| `probar_dashboard.py` | `tests/probar_dashboard.py` |
| `probar_integracion_central.py` | `tests/probar_integracion_central.py` |
| `probar_integracion_voz.py` | `tests/probar_integracion_voz.py` |
| `probar_inventario.py` | `tests/probar_inventario.py` |
| `probar_modulos_operativos.py` | `tests/probar_modulos_operativos.py` |
| `probar_nlp_jarvis.py` | `tests/probar_nlp_jarvis.py` |
| `probar_pipeline_facial.py` | `tests/probar_pipeline_facial.py` |
| `probar_reportes.py` | `tests/probar_reportes.py` |
| `probar_voz.py` | `tests/probar_voz.py` |
| `requirements-dev.txt` | `pruebas/requirements.txt` |
| `evaluar_reconocimiento_facial.py` | `tools/evaluar_reconocimiento_facial.py` |
| `diagnostico_modelo_rostros.py` | `tools/diagnostico_modelo_rostros.py` |
| `generar_registros_sql.py` | `tools/generar_registros_sql.py` |
| `inspeccionar_esquema.py` | `tools/inspeccionar_esquema.py` |
| `migrar_inventario.py` | `tools/migrar_inventario.py` |
| `migrar_anomalias.py` | `tools/migrar_anomalias.py` |
| `verificar_inventario.py` | `tools/verificar_inventario.py` |
| `INVENTARIO.md` | `docs/INVENTARIO.md` |
| `MODULOS_OPERATIVOS.md` | `docs/MODULOS_OPERATIVOS.md` |
| `RECONOCIMIENTO_FACIAL.md` | `docs/RECONOCIMIENTO_FACIAL.md` |
| `REPORTES.md` | `docs/REPORTES.md` |
| `INFORME_FUNCIONAL_SISTEMA.md` | `docs/INFORME_FUNCIONAL_SISTEMA.md` |
| `Primer_Entregable_IA_Actualizado.docx` | `docs/entregables/Primer_Entregable_IA_Actualizado.docx` |
| `Sistema_Inteligente_Inventario_Actualizado.docx` | `docs/entregables/Sistema_Inteligente_Inventario_Actualizado.docx` |
| `respaldos_inventario/inventario_20261006_165527_489415.json` | `backups/inventario/inventario_20261006_165527_489415.json` |
| `respaldos_inventario/inventario_20261006_170002_902192.json` | `backups/inventario/inventario_20261006_170002_902192.json` |
| `Usuario Y Contraseña.txt` | `backups/documentos_privados/Usuario Y Contraseña.txt` |

### Archivos identificados para eliminación

Aún no eliminados. Los recursos de verificación no intervienen en `main.py`, los callbacks ni los modelos. La lista individual completa consta en el inventario JSON; se conserva evidencia en el respaldo.

| Archivo o grupo | Razón |
|---|---|
| `verificacion_ui/` (8184) | Capturas, exportaciones y programas de validación puntual; no referenciados por la aplicación. |
| `backups/archivo_acceso_retirado/` (21) | Código de acceso y auditoría retirado, sin imports ni callbacks activos; se conserva la migración SQL de retirada. |
| `backups/archivo_cargas_anteriores/` (5) | Cargas antiguas reemplazadas por sql/registros_inventario.sql. |
| `aws/` (7) | Solo bytecode de integración abandonada; no existen fuentes ni referencias activas. |
| `tests_aws/` (6) | Solo bytecode de comprobaciones de la integración abandonada. |
| `hardware/` (2) | Solo bytecode antiguo, sin fuentes ni referencias de ESP32/LED en la aplicación. |
| `cache_voz/` (7) | Audio sintetizado regenerable; el asistente conserva su código y vuelve a crear la caché. |
| `evaluacion_facial/` (4) | Resultados de mediciones anteriores; no son calibración operativa, modelos ni imágenes del dataset. |
| `tools/actualizar_desde_exportacion_sql.py` (1) | Carga puntual de normalización ya aplicada; la entrega actual es el archivo SQL. Se conserva la conciliación en la herramienta de verificación. |
| `catalogo_inventario.json` (1) | Lista de IDs usada exclusivamente por la carga retirada; SQL contiene los registros actuales. |
| `tools/retirar_acceso_sql.py` (1) | Ejecutor de una retirada ya aplicada; el SQL equivalente se conserva en migrations/003_retirar_acceso_auditoria.sql. |
| `tools/verificacion_ui/qa_imagen_ui.py` (1) | Captura manual auxiliar utilizada exclusivamente por validaciones puntuales retiradas. |
| `tools/verificacion_ui/verificar_interfaz_visual.py` (1) | Recorrido y capturas de interfaz de una etapa anterior; no es parte de Estado ni de callbacks. |
| `outputs/validaciones/resultado_carga_inventario.json` (1) | Salida antigua de la carga ya aplicada; no leída por módulos activos. |
| `outputs/validaciones/resultado_validacion_inventario.json` (1) | Salida anterior de comprobaciones, regenerable. |
| `DASHBOARD.md` (1) | Informe de etapa consolidado en README y docs/ARQUITECTURA.md. |
| `REDISENO_INTERFAZ.md` (1) | Informe de etapa consolidado en README y docs/ARQUITECTURA.md. |
| `ACTUALIZACION_INVENTARIO.md` (1) | Informe de carga y distribución consolidado en README y docs/ARQUITECTURA.md. |
| `DEPURACION_FACIAL.md` (1) | Informe histórico de corrección; uso y límites vigentes consolidados en docs/ARQUITECTURA.md y documentación facial. |
| `INTEGRACION_JARVIS_MAPA.md` (1) | Documentación de integración consolidada en docs/ARQUITECTURA.md. |
| `__pycache__/ y *.pyc` (85) | Bytecode regenerable, no fuente del sistema. |

### Consolidación e imports

Los cinco informes de etapa se reúnen en README y Arquitectura. Las guías de inventario, reconocimiento, reportes, módulos operativos e informe funcional siguen en docs. Los entregables Word permanecen intactos en docs/entregables.
Las herramientas y comprobaciones agregan la raíz al sys.path para mantener ejecución directa. La evaluación facial se importa desde `herramientas.evaluar_reconocimiento_facial` en la regresión. Se corrigió la ruta al AST de interfaz en las comprobaciones de voz y las rutas de migraciones, exportación y resultados.
En producción solo cambió el mensaje de instalación de modelos en `ai/facial/pipeline_facial.py` para apuntar a la herramienta reubicada. Los imports y algoritmos de la aplicación permanecen.
`requirements.txt` conserva las dependencias utilizadas, incluidas CNN, voz, exportadores y API opcional. El complemento de mantenimiento se movió a `pruebas/requirements.txt`; no se instalaron paquetes.

### .gitignore

Mantiene `.env`, `.venv`, bytecode, caché de voz y capturas regenerables fuera de Git. Agrega backups, outputs, exportaciones, logs y cachés de herramientas. Ya no ignora todo `modelos/`: las etiquetas y configuraciones JSON pueden versionarse. Pesos binarios, galería biométrica local y distribución Vosk siguen excluidos explícitamente, pero deben mantenerse instalados y respaldados.

### Revisión manual

- `sql/Base de Datos.sql`: esquema histórico de InventarioIA1, no instalación completa de InventarioIA2. Se conserva sin cambios.
- `ai/facial/reconocimiento_facial.py`: API de compatibilidad cubierta por regresión, junto con LBPH sin callback visible. Se conserva por duda.
- `backups/documentos_privados/Usuario Y Contraseña.txt`: propósito y vigencia desconocidos; conservado sin leer su contenido, fuera del repositorio.
- `ai/facial/rostros_empleados.py`: función antigua de configuración menciona dos SQL ausentes; no se llama desde el inicio actual. Limitación previa, no corregida en una limpieza de estructura.
- `modelos/modelo_rostros_anterior.keras`: respaldo explícito generado por entrenamiento, conservado.
- `aws/`, `tests_aws/` y `hardware/` solo contienen bytecode sin fuentes ni referencias activas; la retirada sigue pendiente de aprobación.

### Validación

- Inicio real mediante main.py correcto; 15 páginas principales y siete secciones de Configuración recorridas sin errores de callbacks.
- Suite reorganizada: **106 casos, 105 correctos y uno omitido** porque FastAPI no está instalado. La omisión afecta únicamente la API opcional; `.venv` no se modificó.
- Se ajustó la comprobación de ranking para que sus registros transaccionales destaquen sobre el historial existente, sin modificar el ranking de producción.
- La conciliación de los **254 detalles** y lotes pasó; los 15 tipos de reportes y las consultas de Dashboard/JARVIS se validaron con SQL existente.
- No se activaron cámara ni micrófono físicos. Los casos SQL revierten sus registros. No se ejecutaron migraciones ni cargas.

### Estructura organizada

```text
main.py, ui/interfaz.py y módulos activos
requirements.txt, README.md, .gitignore y configuraciones
sql/Base de Datos.sql, sql/registros_inventario.sql
herramientas/       mantenimiento e instalación
pruebas/           regresiones y requisitos de mantenimiento
docs/              guías, inventario y plan de limpieza
  entregables/     documentos Word
backups/           inventario, respaldo de limpieza y documentos privados
outputs/           resultados regenerables
migrations/        historial SQL necesario
modelos/, modelos_voz/, Clasificacion/, rostros/
.venv/, .vscode/
```

Todavía permanecen los archivos y carpetas enumerados para retirada. La raíz no se considera completamente limpia hasta resolver la aprobación. Este informe no es una dependencia de la aplicación.

<a id="integracion-historica"></a>

## Integración de los cuatro módulos

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Texto y voz usan `agente_inventario.procesar_consulta`. Su respuesta estructurada
incluye `respuesta`, `voz`, `datos` y `acciones_ui`. Las acciones del mapa se ejecutan
en el consumidor de eventos de Tkinter, después de consultar los datos. El agente
no afirma que una acción visual haya sucedido antes de ejecutarse.

### Uso

- «¿Cuántos motores quedan?» consulta el producto real y recuerda su identidad.
- «¿Dónde está?» consulta sus existencias y abre el mapa con todas sus ubicaciones.
- «¿Cuánto tiempo durará?» usa el motor de predicción del mismo producto.
- «¿Por qué?» explica la última predicción; si fue insuficiente, explica ese estado.
- «Muéstramelo» abre nuevamente el mapa.
- «¿Qué hay en el estante E03?» consulta ese valor registrado, sin deducirlo del código.
- «¿Qué productos tienen riesgo alto?» usa las predicciones suficientes de 30 días.
- «¿Qué producto puede agotarse primero?» conserva la herramienta del agente existente.
- «Reconocer empleado» solicita abrir el flujo de cámara existente desde JARVIS.

Los nombres similares requieren aclaración. Un nombre nuevo desconocido no se
reemplaza por el producto recordado. «El otro» pide identificar el producto.
El botón para limpiar el chat también limpia el contexto temporal. No se guarda
la conversación en SQL. `jarvis/jarvis_personality.py` centraliza respuestas sociales,
formato numérico, presentación de predicción y versión hablada. La voz utiliza la
jerarquía registrada en vez de leer también los códigos del texto cuando existe
esa jerarquía. Para más de tres ubicaciones resume la cantidad de resultados;
el detalle completo permanece en pantalla.

### Mapa

`inventory/mapa_almacen.py` consulta las ubicaciones activas y las existencias vigentes.
La pestaña Mapa agrupa almacén, zona y pasillo; muestra estante y nivel. Admite
filtros, búsqueda, selección y tabla de productos. `mostrar_producto_en_mapa`
es el acceso común de Productos y JARVIS. Los formularios de movimiento permiten
ver origen y destino con sus códigos, color y texto diferentes, sin registrar
movimientos desde el mapa. La búsqueda reutiliza el resolvedor de productos para
entender plurales y muestra cantidades por ubicación.
«Abrir JARVIS» está disponible en la cabecera de todas las pantallas.

Es un mapa lógico, no un plano físico a escala. No hay posición ni capacidad en
el esquema actual: se indican como no registradas. No se inventan porcentajes de
ocupación ni estados llena/alta. Gris significa vacía, verde disponible, azul
seleccionada y turquesa coincidencia de búsqueda, siempre acompañado de texto.
No se deduce zona o almacén de un código; los valores ausentes se señalan.

### Reconocimiento facial

Se reutilizan **YuNet + SFace de OpenCV**, con imágenes BGR, alineación y
embeddings normalizados de la misma extracción en registro y reconocimiento.
No se cambió el modelo, la galería, los umbrales ni las identidades del dataset.
Se desactivó como valor predeterminado `modo_basico`, que era una herramienta
de diagnóstico con decisiones de un fotograma. El uso normal aplica calidad,
tracking y consenso temporal ya existentes. El diagnóstico incorpora mejor y
segundo candidato, sus similitudes, margen y umbral real. La similitud no es un
porcentaje de probabilidad de identidad.

Se conservan la captura e inferencia independientes con colas de último frame,
fuentes USB/IP/RTSP, muestras guiadas y regeneración de la galería desde las fotos
existentes. Una identidad solo se acepta con calibración válida ligada a la
galería y empleado activo en SQL. Un resultado reconocido puede saludar una vez
al terminar la operación; un candidato o estado verificando no genera saludo.
No se ha medido alcance físico en metros ni precisión con personas en el almacén.
La calibración y la evaluación independiente siguen siendo necesarias.

### Predicción

`ai/prediction/prediccion_stock.py` mantiene el motor y sus campos compatibles. La estimación
principal utiliza **promedio diario observado**, incluyendo días sin salidas
entre la primera salida disponible y la fecha de análisis, dentro de la ventana.
Se permiten 7, 30, 60 y 90 días; el valor predeterminado es 30. Entradas,
transferencias y ajustes no cuentan como consumo. Se excluyen movimientos futuros.
Se requieren cinco fechas con salidas para estimar días y fecha de agotamiento.
Se calcula `stock total / consumo promedio`; la fecha usa días redondeados hacia
arriba. Sin datos suficientes no se producen fechas ni compras recomendadas.

La tendencia compara consumo de las dos mitades de la serie: aumenta/disminuye
si cambia más de 10%; de lo contrario es estable. La regresión existente se
conserva como indicador compatible, no sustituye la estimación principal ni
se presenta como un modelo más preciso sin validación histórica.

El riesgo se centraliza en `calcular_riesgo`: crítico para agotado, stock menor o
igual a la mitad del mínimo positivo o cobertura de hasta tres días; alto para
stock menor o igual al mínimo o hasta siete días; medio hasta treinta días;
bajo para el resto. Sin historial suficiente se muestra SIN DATOS de predicción,
conservando el estado real de stock en Productos. Son reglas operativas explícitas,
no probabilidades estadísticas.

`ui/prediccion_ui.py` agrega la pestaña Predicción con ventana de análisis, tabla
ordenada por riesgo, tarjetas, explicación y gráfica histórica. La línea
discontinua identifica el promedio usado como referencia de estimación. No se
dibujan movimientos futuros ficticios. La cantidad recomendada conserva la fórmula
`máximo(mínimo, promedio × cobertura objetivo) − stock`, limitada a cero.
Sin plazo real de proveedor no se inventa una fecha de pedido.

### Archivos y validación

Creados: `inventory/mapa_almacen.py`, `jarvis/jarvis_personality.py`, `ui/prediccion_ui.py`,
`probar_integracion_central.py` y este documento.

Modificados en esta integración: `jarvis/agente_inventario.py`, `ui/interfaz.py`,
`ui/inventario_ui.py`, `ai/prediction/prediccion_stock.py`, `ai/facial/pipeline_facial.py`,
`ai/facial/reconocimiento_embeddings.py`, `reconocimiento_facial_config.json`,
`probar_integracion_voz.py`, `probar_pipeline_facial.py` y `tools/verificacion_ui/verificar_interfaz_visual.py`.

No se cambió el esquema SQL ni se añadieron dependencias. Se reutilizan Vosk
español local y sounddevice para reconocimiento, Edge TTS para síntesis y pyttsx3
como alternativa local. La escucha se suspende durante TTS; se conserva Detener voz.
El micrófono sigue siendo push-to-talk con activación JARVIS opcional.

Pruebas: 74 casos de inventario, dashboard, facial, voz, herramientas y nuevas
integraciones. Los casos SQL usan transacciones con rollback. La QA visual abre
todas las pestañas en tres resoluciones y los formularios sin guardar registros.
Los datos de prueba y las imágenes sintéticas de tests no alimentan el sistema.

Limitaciones: el historial real actual no basta para predecir agotamiento. La
precisión y distancia facial requieren evaluación con cámara real y calibración;
actualmente falta `modelos/facial_embeddings/calibracion.json`, por lo que el
pipeline de embeddings permanece SIN_CALIBRAR y no confirma identidades.
los tests no constituyen esa medición. El promedio no modela estacionalidad ni
plazos de proveedor. El mapa no contiene geometría física o capacidad inventadas.

<a id="dashboard-historico"></a>

## Registro de implementación del Dashboard

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Pantalla inicial añadida a la navegación existente. Se mantienen Productos, Movimientos, Historial, Alertas, Empleados, Análisis IA y JARVIS. No se modificaron core/database.py, consultas SQL ni modelos de reconocimiento.

### Indicadores y fuentes reales
- Productos, stock, bajos y agotados: listar_productos. Stock bajo excluye agotados, indicándolo en la tarjeta. Stock total agrega las cantidades existentes.
- Alertas activas: listar_alertas, contando únicamente Pendiente. Alertas recientes: las ocho últimas, atendidas o pendientes, con su estado visible.
- Empleados activos: listar_empleados y estado activo.
- Movimientos recientes: buscar_movimientos entre hoy y los 29 días anteriores, treinta fechas de calendario. Se cuentan operaciones únicas por id_movimiento; los detalles no inflan el KPI. La tabla muestra los ocho últimos detalles de ese período.
- Anomalías: analizar_movimientos sobre el histórico de salidas, sin crear alertas. Si el módulo informa historial insuficiente, se muestra Sin datos suficientes y no un cero confirmado.
- Reconocidos recientes: empleados únicos observados como RECONOCIDO en la cámara de esta aplicación, dentro de la sesión y las últimas 24 horas. El contador usa la última observación por código; el listado conserva hasta 200 eventos y evita duplicar frames seguidos en 30 segundos. No existe un historial persistente de éxitos en el sistema actual; no se presenta este contador como un registro histórico SQL.
- Actividad facial: reconocimientos de sesión y alertas reales Empleado no reconocido guardadas en SQL, con sus fechas y origen claramente indicados. No se asigna identidad a personas desconocidas.
- Motor facial y JARVIS: reutilizan sus variables de estado actuales. No cambian los criterios de autorización facial ni el agente.
- Base de datos: conexión real con conectar y SELECT 1. Fuente fallida muestra No disponible, nunca cero inventado; un fallo parcial se identifica junto a la última actualización.

### Visualización y acciones
Paleta y componentes de ui/ui_theme.py. Nueve tarjetas KPI, tres badges de estado, cinco accesos rápidos, cuatro tablas y tres gráficos de barras ligeros dibujados con Tk Canvas. Sin dependencias adicionales.

Accesos: Nuevo producto, Registrar entrada, Registrar salida, Reconocer empleado y Abrir JARVIS. Invocan los callbacks existentes. La nueva actividad facial se observa desde el presentador Tk mediante un callback opcional; no se cambia la inferencia ni se escribe en SQL.

Gráficos: cantidades de Entrada vs Salida, cinco productos con mayor cantidad en entradas/salidas y hasta cinco categorías con mayor stock. Las transferencias no se cuentan como ingreso o salida del almacén. No se interpolan ni inventan series; se muestra Sin datos suficientes cuando no hay cantidades positivas. Son cantidades agregadas del sistema; no representan importes monetarios ni conversiones entre unidades distintas.

Las consultas se ejecutan en un worker y el hilo Tk consume una cola. La carga no bloquea la pantalla. Se actualiza al abrir el dashboard, con el botón Actualizar resumen, después de actualizar_todo y cada 60 segundos mientras está visible. No se permiten cargas simultáneas. El cierre cancela los temporizadores de presentación.

### Resultado real de la verificación
- 4 productos activos y 153 de stock agregado.
- 0 productos con stock bajo y 0 agotados.
- 9 alertas pendientes y 16 empleados activos.
- 0 operaciones en los últimos 30 días.
- Anomalías: Sin datos suficientes.
- Categorías: Tornillería 100, Repuestos 30, Equipos 15, Herramientas 8.
- Reconocimientos de sesión: 0; no se simuló una identificación en los datos mostrados.
- Base conectada, JARVIS listo y motor facial Sin calibrar, conservando su estado anterior.

48 pruebas aprobadas: seis del dashboard y 42 de reconocimiento/voz/intenciones. Cobertura de agregados, fuentes fallidas, insuficiencia del análisis, operaciones con múltiples detalles, transferencias y deduplicación de reconocimiento confirmado.

Verificación de aplicación real: ocho módulos en tres tamaños (24 vistas), trece aperturas de formularios incluyendo accesos rápidos, consulta real de JARVIS, cero errores de callback/geometry y cero botones recortados registrados. Tamaños 1366x768 y 1100x650; solicitado 1920x1080, limitado por Windows a cliente 1920x1061. Se revisaron capturas del dashboard y sus secciones. Los formularios se abrieron sin guardar cambios. No se efectuó una nueva prueba física de identificación; el estado de calibración permanece pendiente.

### Archivos
Nuevos: ui/dashboard.py, probar_dashboard.py y DASHBOARD.md.
Actualizados: ui/interfaz.py, ui/ui_theme.py, ui/ventanas_camara.py, tools/verificacion_ui/verificar_interfaz_visual.py y README.md.

### Ejecutar

    .\.venv\Scripts\python.exe main.py
    .\.venv\Scripts\python.exe -X utf8 -m unittest probar_dashboard probar_pipeline_facial probar_integracion_voz probar_cobertura_jarvis

Capturas locales: verificacion_ui/modulo_0.png, dashboard_secciones.png y dashboard_actividad.png. Resultado: verificacion_ui/resultado.json. El verificador protege la captura comprobando que el área pertenezca a su propia ventana.

<a id="interfaz-historica"></a>

## Registro de rediseño de interfaz

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Implementado en la aplicación Tkinter/ttkbootstrap existente. main.py conserva el punto de entrada. No se modificaron consultas SQL, lógica de inventario, agentes, modelos faciales, predicciones ni base de datos durante este rediseño.

### Archivos
- ui/ui_theme.py: sistema visual central, paleta COLORES, tipografía FONTS y espaciado SPACING; componentes reutilizables.
- ui/interfaz.py: organización y presentación de las siete pantallas, formularios, tablas y chat. Se conservaron callbacks y bindings operativos.
- ui/ventanas_camara.py: presentación adaptable y coherente del escáner y registro facial. Contrato de publicación de frames e información conservado.
- probar_integracion_voz.py: adaptador del nuevo componente de chat y acceso a la paleta en las pruebas aisladas; mismas comprobaciones de coordinación de voz.
- tools/verificacion_ui/verificar_interfaz_visual.py: herramienta reproducible de QA con arranque y SQL reales; abre formularios sin guardar registros y verifica una consulta real de JARVIS.
- .gitignore: excluye capturas y resultados locales de verificacion_ui/.
- README.md y este informe: documentación.

### Identidad compartida
Fondo #F4F7FB; fondo secundario #EAF0F6; tarjetas #FFFFFF; azul principal #16324F; azul secundario #214C73; turquesa #14B8A6; éxito #10B981; peligro #EF4444; advertencia #F59E0B; texto #1F2937; texto secundario #64748B; bordes #D9E2EC.

Segoe UI: título 20, sección 16, texto 10, auxiliar 9 y KPI 26. Padding de página 20, tarjetas 16 y separaciones 12. Sin nuevas fuentes, paquetes de iconos ni imágenes externas. Los botones tienen cursor hand2, hover y estados de foco/deshabilitado. Se usan contraste y bordes suaves; no hay hacks de sombras ni bordes redondeados.

Componentes: crear_panel, crear_kpi, crear_badge, crear_indicador, Navegacion, crear_pagina y ChatConversacion. Los widgets tk con colores explícitos desactivan el autostyle de ttkbootstrap; los estilos ttk se registran mediante el Style de la ventana para conservar sus nombres, colores y tipografía.

### Pantallas
| Módulo | Cambios visuales |
|---|---|
| Productos | Cuatro KPI con cifras grandes y acentos semánticos; búsqueda y acciones en filas separadas; tabla con bandas, encabezados legibles y scroll horizontal cuando hace falta. |
| Movimientos | Tres tarjetas del mismo ancho, iconos discretos, descripción y botón semántico; formularios más compactos con la acción visible. |
| Historial | Tarjeta de filtros en columnas, etiquetas y formato de fecha claros, acciones agrupadas; tabla independiente con scroll. |
| Alertas | KPI en naranja/rojo suave; estados de severidad mediante tags; filtros y acciones dentro de una tarjeta. |
| Empleados | Tarjeta biométrica, cifras grandes, badge dinámico del estado del motor y cámara como acción principal; asignación biométrica en tarjeta independiente; contenido desplazable. |
| Análisis IA | KPI coherentes, tarjetas independientes para predicción y anomalías, búsqueda flexible y botón de análisis visible encima de la tabla. |
| JARVIS | Mensajes del usuario a la derecha y del asistente a la izquierda; estado semántico; compositor amplio, micrófono con estado visual, enviar y reinicio de contexto secundario. |

Header azul con título destacado y chips suaves. Sidebar mantiene un Notebook nativo con tabs ocultas y conserva la navegación entre las mismas pantallas. Las páginas adaptan su anchura; cuando falta altura aparece scroll sin ocultar definitivamente acciones. Tamaño inicial 1366x768 y mínimo 1100x650.

Los diálogos de productos, categorías, ubicaciones, entradas, salidas, transferencias y empleados comparten la paleta, estilos y encabezados. La cámara ajusta el video al espacio disponible conservando su proporción y mantiene Escape/Q y botones de cierre.

### Verificación ejecutada
- Arranque real y cierre normal con SQL Server: correctos.
- 21 vistas: siete módulos en 1366x768, 1100x650 y tamaño solicitado 1920x1080. Windows limitó este último cliente a 1920x1061; no se afirma un área cliente de 1080.
- Diez aperturas de diálogos: nuevo/editar producto, detalle de ubicaciones, categorías, ubicaciones, entrada, salida, transferencia y nuevo/editar empleado. Ningún formulario se guardó.
- Presentación del diálogo de escáner: verificada; esta revisión visual no encendió la cámara ni midió precisión biométrica.
- Tablas cargadas desde SQL: cuatro productos, nueve alertas y dieciséis empleados. Historial y anomalías vacíos según las consultas actuales.
- Cero errores de callback/geometry registrados y cero botones recortados en las comprobaciones automáticas. Capturas revisadas visualmente; los encabezados largos conservan su ancho mínimo y las tablas permiten desplazarse.
- Comparación AST: las 30 llamadas a funciones de negocio son idénticas, incluidos sus argumentos.
- 42 pruebas de pipeline facial, voz e intenciones: aprobadas. El mensaje de dispositivo ocupado pertenece a una prueba de error simulada.
- Consulta real desde el chat: «¿Cuántos motores quedan?» → «Claro. Actualmente hay 15 unidades de Motor eléctrico disponibles.» Se comprobó el producto y la cantidad contra SQL; el saludo puede variar entre consultas. Última respuesta desde la interfaz: «Claro. Actualmente hay 15 unidades de Motor eléctrico disponibles.».

El motor facial conserva su estado anterior SIN CALIBRAR. Este rediseño no habilita identidades sin calibración ni afirma haber resuelto la validación de reconocimiento presencial. El micrófono y TTS se comprobaron con las pruebas de coordinación existentes; no se hizo una nueva prueba presencial de audio.

### Reproducir

    .\.venv\Scripts\python.exe main.py
    .\.venv\Scripts\python.exe -X utf8 -m tools.verificacion_ui.verificar_interfaz_visual
    .\.venv\Scripts\python.exe -X utf8 -m unittest probar_pipeline_facial probar_integracion_voz probar_cobertura_jarvis

El QA abre la aplicación y formularios de manera temporal, consulta SQL y guarda capturas en verificacion_ui/. Depende de la instancia SQL local y de datos de inventario para la consulta de prueba. Resultado estructurado: verificacion_ui/resultado.json. Capturas principales: modulo_0.png a modulo_6.png; conversación real: jarvis_consulta_real.png.

<a id="carga-historica"></a>

## Registro de actualización del inventario

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Fecha de actualización: 6 de octubre de 2026.

### Esquema revisado

Se inspeccionaron los metadatos de SQL Server: columnas, tipos, precisión, columnas obligatorias, identidad, valores predeterminados, claves primarias, restricciones únicas, claves foráneas y restricciones de dominio. Los scripts base y las migraciones 004 y 005 se contrastaron con la base activa `InventarioIA2`. No se añadieron tablas ni se cambió el motor.

Tablas consultadas o utilizadas: productos, categorías, unidades_medida, ubicaciones, empleados, existencias, tipos_movimiento, motivos_movimiento, movimientos, detalle_movimientos, lotes, existencias_lotes, detalle_movimiento_lotes, tipos_alerta, alertas, anomalias_inventario, conteos_inventario, detalle_conteos, rostros_empleados e inventario_migraciones. Se reutilizan las vistas vw_inventario y vw_stock_producto.

### Registros y conservación

| Entidad | Antes | Después | Agregados |
|---|---:|---:|---:|
| Productos | 24 | 24 | 0 |
| Categorías | 9 | 9 | 0 |
| Unidades | 7 | 7 | 0 |
| Ubicaciones | 18 | 18 | 0 |
| Empleados | 16 | 16 | 0 |
| Movimientos | 244 | 253 | 9 |
| Detalles de movimientos | 244 | 254 | 10 |
| Lotes | 6 | 6 | 0 |
| Relaciones faciales | 16 | 16 | 0 |
| Hallazgos de anomalías | 3 | 3 | 0 |

Se actualizaron los códigos y descripciones de 20 productos y 12 ubicaciones, las descripciones de cuatro categorías, los códigos de seis lotes y las referencias y observaciones del historial de esa carga anterior. Todos los identificadores y claves foráneas se conservaron. Las seis ubicaciones originales recibieron almacén y zona donde estaban sin informar. Se conservaron las 16 personas existentes, superando el objetivo de 5–10 para no perder información. Ocho empleados participan en el historial.

Se agregaron cinco operaciones de actividad: una entrada, dos salidas, una transferencia y un ajuste de entrada. Además se documentaron cuatro saldos iniciales de productos que ya tenían existencias pero carecían de historial. Estos cuatro registros no sumaron stock nuevamente: sus detalles documentan las cantidades ya disponibles. Uno abarca dos ubicaciones, por eso hay un detalle adicional. El total supera ligeramente la referencia aproximada de 250 para conservar y conciliar toda la información.

El proceso conserva respaldos locales previos a cada aplicación en `respaldos_inventario`. Los scripts anteriores quedaron preservados como archivos retirados en `archivo_cargas_anteriores`; no son los comandos actuales de carga.

### Catálogo, ubicaciones y lotes

Las nueve categorías reutilizadas son Consumibles, Equipos, Filtros, Herramientas, Lubricantes, Materiales eléctricos, Repuestos, Seguridad y Tornillería. Las unidades disponibles son las siete del catálogo existente. Cada producto conserva su unidad asignada.

Códigos actualizados: TOR-002, TOR-003, TUE-001, ARA-001, FIL-001, FIL-002, ACE-001, ACE-002, GRA-001, BUJ-001, COR-001, ROD-002, HER-001, BRO-001, CAB-001, FUS-001, MOT-002, GUA-001, LIM-001 y SIL-001. Se conservaron MOT-001, TAL-001, ROD-001 y TOR-001. No se crearon productos duplicados.

Las ubicaciones combinan las seis originales con doce ubicaciones de las zonas A, B y C. Los nuevos códigos de presentación usan zona, pasillo, estante y nivel, como A-P01-E01-N01. Se conservan los campos y la distribución de existencias existentes. Hay productos repartidos en varias ubicaciones y ubicaciones compartidas por distintos productos. No se añadieron campos de posición ni capacidad.

Se reutilizan seis lotes de lubricantes y consumibles con estados vigente, próximo a vencer y vencido. La conciliación también verifica saldos por lote, ingreso anterior a su movimiento y ausencia de retiros posteriores al vencimiento en el historial cargado. No se crearon imágenes ni vectores faciales.

### Historial, stock y análisis

Rango de movimientos: del 10/07/2026 al 06/10/2026; los últimos cuatro corresponden al registro de los saldos iniciales existentes en la fecha de actualización.

| Tipo | Operaciones |
|---|---:|
| Entrada | 31 |
| Salida | 213 |
| Transferencia | 7 |
| Ajuste entrada | 1 |
| Ajuste salida | 1 |

La carga reutiliza las primitivas transaccionales de `inventory/movimientos.py`, el bloqueo por producto, la actualización de existencias y la generación de alertas. Reconstruye los 254 detalles por producto y ubicación en orden de fecha y detalle, comparando stock anterior, stock posterior y saldo final. Las transferencias descuentan origen y suman destino; su efecto global es cero. Ningún paso deja existencias negativas. Las filas originales y los nueve registros adicionales quedan dentro del historial conciliado.

Los cuatro saldos iniciales se documentan a partir de existencias ya registradas; no afirman compras previas cuya fecha no está disponible. Los movimientos generados para completar el historial constituyen registros iniciales solicitados: no se contrastaron con facturas u órdenes externas.

Hay 17 productos normales, cuatro con stock bajo, dos críticos y uno agotado. El módulo de stock bajo agrupa los seis bajos/críticos. Las alertas se obtienen de las funciones existentes, sin insertar mensajes de alerta por fuera de ellas.

Con la ventana actual de 30 días, once productos tienen historia suficiente: ACE-001, ACE-002, BRO-001, BUJ-001, CAB-001, FIL-001, FIL-002, FUS-001, TOR-002, TOR-003 y TUE-001. La predicción se calcula con el motor actual; no se insertaron predicciones.

Los tres movimientos inusuales conservados corresponden a 150 tornillos, 25 filtros de aceite y 80 metros de cable. Los scores, niveles y motivos se calculan por el analizador existente. No se introducen scores manuales. Los productos con consumo esporádico continúan indicando historia insuficiente cuando corresponde.

### Distribución visual

Se mantienen paleta, callbacks y módulos. Se centraliza el espaciado en `ui/ui_theme.py`: XS=4, SM=8, MD=12, LG=20, XL=28 y padding de tarjeta de 16 cuando corresponde. Las páginas utilizan margen exterior de 28; las acciones usan `ui_components.organizar_acciones`, que distribuye botones según el ancho y separa acciones destructivas.

- Navegación: sidebar agrupada en Almacén, Inteligencia, Personal y Sistema; selección activa y desplazamiento conservados. Los nombres largos se ajustan en varias líneas.
- Dashboard: espaciado consistente entre estados, accesos, indicadores, gráficos y tablas; cifras legibles sin partir números.
- Productos: búsqueda y filtros conservados; acciones y catálogos adaptables; indicadores completos; formulario con etiquetas encima de los campos.
- Movimientos: cuatro tarjetas en dos columnas para entrada, salida, transferencia y ajuste, con alineación uniforme.
- Historial: separaciones consistentes entre título, filtros, acciones y tabla; controles y consultas conservados.
- Alertas: indicadores, filtro de pendientes, tabla y acciones separados; eliminar queda apartado de las acciones de atención.
- Empleados: selector del motor separado de las acciones; asignación facial con dos campos claramente identificados; acciones destructivas separadas; formulario con etiquetas sobre campos.
- Mapa: detalle lateral y mapa en distribución próxima a 70/30; se apilan con menor ancho. Se mantienen selección, búsqueda y distinción de origen/destino.
- Análisis IA y Predicción: separación entre controles, resultados, indicadores y tablas; métodos de cálculo intactos.
- Anomalías: filtros y barra adaptable sin cambiar estados de revisión ni comandos del analizador.
- Reportes: configuración, resumen, vista previa y exportaciones separados; botones de exportación en el bloque inferior.
- JARVIS: más separación entre mensajes; conversación adaptable; entrada, hablar, enviar y opciones secundarias visibles en 1366×768.
- Estado: tarjetas y acciones con separación uniforme, textos de comprobación consistentes.
- Configuración: secciones internas conservadas y campos con etiqueta superior.
- Formularios: producto, entrada, salida, transferencia, ajuste y empleado conservan los comandos de guardado; ventanas centradas y contenido desplazable cuando corresponde.

### Ejecución y validación

Desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m tools.actualizar_desde_exportacion_sql
.\.venv\Scripts\python.exe -m tools.actualizar_desde_exportacion_sql --aplicar
.\.venv\Scripts\python.exe -m tools.actualizar_desde_exportacion_sql --verificar
.\.venv\Scripts\python.exe verificar_inventario.py
```

El primer comando valida dentro de una transacción que luego revierte. `--aplicar` respalda y confirma una única transacción, o no modifica nada si la carga completa ya existe. Las referencias INV-ACT e INV-SAL identifican operaciones para impedir duplicados. La carga está adaptada a los identificadores revisados de esta instalación, registrados en `catalogo_inventario.json`; no debe ejecutarse sin revisar ese catálogo en otra base.

Los resultados están en `outputs/validaciones/resultado_validacion_inventario.json` y `outputs/validaciones/resultado_carga_inventario.json`. Se revisaron las 15 pantallas a 1366×768 y 1920×1080 y seis formularios sin guardar operaciones; las comprobaciones de cámara y micrófono requieren iniciarlas expresamente. Pasaron las 19 verificaciones automatizadas de exportaciones y módulos operativos. La consulta de textos de todas las columnas de caracteres de SQL Server confirmó que ya no contienen los términos retirados.

No se necesitan dependencias nuevas, cambios de esquema, cuentas de acceso ni servicios externos. La calibración facial sigue pendiente en esta instalación y no existe historial persistente de reconocimientos; la carga no cambia esas limitaciones.

<a id="facial-historico"></a>

## Registro de diagnóstico facial

> Documento técnico conservado de una etapa anterior. Las cifras, rutas y estados de su entrega no sustituyen la configuración ni los datos actuales. Consulta la instalación y arquitectura al principio de este archivo.


Causa raíz: el cambio de CNN a SFace dejó la galería vacía y no existía una calibración válida. No era una puntuación baja. La calibración sigue siendo necesaria para autorizar identidades.

### Cambios
- Regeneración explícita desde las imágenes originales de subjects vinculados en SQL. No se convierten vectores CNN, no se reasignan empleados y se respalda una galería anterior.
- Botón REGENERAR BASE FACIAL en la interfaz; procesa fuera del hilo Tk.
- Modo básico predeterminado: detección global en cada frame, landmarks YuNet, alignCrop SFace, BGR, embedding 128D normalizado L2, producto escalar como cosine similarity (mayor es mejor). Sin tiles, tracking ni votación.
- Debug real en consola una vez por segundo y sobre el video, incluso cuando la calidad impide autorizar. Imprime todas las comparaciones, mejor y segundo score, umbral y motivo de rechazo.

### Resultados reales
16 empleados SQL; 192 embeddings regenerados. Roger: 27 imágenes detectables de 30; se excluyeron capture008, capture028 y capture029 porque YuNet no detectó rostro. Los otros 15 subjects conservan 11 imágenes cada uno. Esos GIF pertenecen al dataset histórico Yale; sus nombres SQL no prueban que correspondan a personas reales de la empresa. Se conservaron las relaciones existentes; conviene verificarlas.

16/16 candidatos correctos al reprocesar una imagen usada en la galería; cosine same-image aproximadamente 1.0. Esto comprueba coherencia del pipeline, NO reconocimiento en imágenes independientes.

Roger capture001 vs capture002: 0.752660; máximo Roger capture001 frente a muestras de otra identidad: 0.234476. Puntaje top3 Roger: 0.856412; segundo candidato Alejandro: 0.204739; margen 0.651673. Norma 1.0, dimensión 128.

El recorte histórico capture001 mide 100x100 y YuNet localiza un rostro de 65x81. El pipeline de cámara informa ROSTRO_MUY_PEQUENO (mínimo 80) en esa imagen: no se agrandó para fingir resolución. La prueba de comparación de embeddings se hace independientemente de la autorización por calidad.

Threshold operativo: ninguno; falta calibración. No se ha bajado ni inventado un threshold. La revisión automática rechazó habilitar autorización sin calibración. El candidato y las similitudes se muestran para depuración, sin autorizar movimientos ni empleados.

42 pruebas existentes pasan; sintaxis e importación de interfaz correctas. La prueba nueva de frame histórico confirmó candidato Roger y rechazo correcto por tamaño.

### Uso
En la raíz del proyecto:

    .\.venv\Scripts\python.exe -X utf8 -m ai.facial.diagnostico_facial_basico regenerar
    .\.venv\Scripts\python.exe -X utf8 -m ai.facial.diagnostico_facial_basico diagnosticar

Resultados: evaluacion_facial/diagnostico_basico.json y evaluacion_facial/matriz_similitud.csv. Cada celda de la matriz es el coseno entre centroides normalizados; no es probabilidad.

Cámara real: 1280x720, 92 frames procesados en 8.782 segundos; 0 rostros detectados. Esta prueba comprueba captura y procesamiento; no valida identificación de una persona presente.

Falta validar Roger frente a la cámara a 0.5, 1 y 2 metros, con distancia medida por una persona, y capturas independientes de personas desconocidas para calibración. No se probó larga distancia.

Archivos modificados en esta corrección: ui/interfaz.py, ai/facial/reconocimiento_embeddings.py, reconocimiento_facial_config.json. Nuevos: ai/facial/pipeline_facial_basico.py, ai/facial/diagnostico_facial_basico.py, DEPURACION_FACIAL.md. Artefactos generados: modelos/facial_embeddings/galeria.npz, evaluacion_facial/diagnostico_basico.json, evaluacion_facial/matriz_similitud.csv.

## Consolidación documental

Se integraron los 13 Markdown de la raíz y `docs/` en este `README.md`.
Los originales se conservaron y verificaron por SHA-256 en `backups/documentacion/markdown_20261007_232514.zip`.
La aplicación no depende de estos documentos. Los Markdown de librerías externas y del entorno virtual no forman parte de esta consolidación.

<a id="cuestionario-modelado"></a>

## Cuestionario técnico de modelado — revisión del 11 de octubre de 2026

Las siguientes 53 respuestas se basan en código, configuraciones, artefactos guardados y consultas de lectura a SQL Server. Se distingue entre resultados experimentales, diagnósticos con imágenes reutilizadas y comprobaciones de software. No se entrenaron modelos nuevos, no se activaron cámara ni micrófono físicos y no se ejecutaron cargas de inventario para responder este cuestionario. Esta sección actualiza los estados de IA descritos en los documentos históricos anteriores.

### Resultados verificados

| Componente | Evidencia disponible | Interpretación correcta |
|---|---|---|
| CNN facial alternativa | 36 aciertos de 39 imágenes; accuracy 92,31%; F1 macro 0,8917 | Clasificación cerrada de imágenes del conjunto local; no mide aceptación de desconocidos ni vigilancia real |
| YuNet/SFace principal | 192 embeddings, 16 identidades, sin calibración válida | Implementación y galería disponibles; aceptación de identidades pendiente de calibración |
| Diagnóstico histórico SFace | 16/16 candidatos correctos al reutilizar imágenes del registro | Coherencia del pipeline; no precisión en personas o imágenes independientes |
| NLP aislado | 14/18 consultas correctas, 77,78%; cuatro rechazos por baja confianza | Evaluación pequeña de frases separadas del archivo de entrenamiento |
| Flujo del agente con reglas | 40/40 formulaciones de ocho capacidades | Cobertura funcional conocida; no equivale al accuracy del clasificador aislado |
| Predicción | Tres de 24 productos cumplen hoy el mínimo de la ventana de 30 días | Disponibilidad de historial; no exactitud predictiva medida |
| Anomalías | Tres hallazgos sobre 230 detalles disponibles; 37 candidatos con historial suficiente | Detección estadística; los tres registros persistidos siguen PENDIENTE |
| Regresión de software | 106 casos ejecutados: 105 aprobados y uno omitido por falta de FastAPI | Integración y comportamiento del código; no validación científica de los modelos |

### I. Información general del sistema

**1. ¿Cuáles son los componentes de IA implementados?**

Reconocimiento facial principal con YuNet/SFace y alternativa CNN propia; clasificación de intenciones mediante TF-IDF y regresión logística; reconocimiento de voz con Vosk; integración opcional con un LLM local mediante Ollama. También hay predicción por estadística/regresión y detección estadística de anomalías. El módulo de anomalías conserva Isolation Forest como alternativa heredada, sin dirigir el flujo principal actual.

**2. ¿Qué funciones usan IA y cuáles reglas o consultas tradicionales?**

Detección/extracción facial, clasificación CNN, interpretación de intenciones y transcripción utilizan modelos aprendidos. El consumo medio, riesgo de stock, calidad facial y detección principal de cantidades inusuales usan cálculos y reglas estadísticas. Altas, movimientos, transferencias, saldos, catálogos, mapa, Dashboard y generación de reportes consultan o actualizan SQL y presentan resultados; no son modelos aprendidos por sí mismos. JARVIS combina interpretación aprendida con reglas y herramientas de consulta.

**3. ¿Qué está implementado, pendiente o no implementado?**

Los flujos de inventario, análisis, JARVIS, voz y reconocimiento están implementados. La CNN tiene un entrenamiento guardado con evaluación cerrada. YuNet/SFace tiene modelos y galería, pero falta calibración válida para autorizar identidades. Falta validación de campo de voz y reconocimiento, evaluación retrospectiva de predicción y etiquetado humano de anomalías. No están implementadas métricas operativas verificadas de alcance facial en metros ni evaluación predictiva con MAE/RMSE/MAPE. Ollama y la API son opciones; no se comprobó experimentalmente un LLM activo en esta revisión y FastAPI falta en el entorno utilizado.

**4. ¿Qué lenguaje y bibliotecas se utilizan?**

Python; OpenCV y NumPy para visión; TensorFlow/Keras para CNN; scikit-learn para TF-IDF, regresión logística, regresión lineal e Isolation Forest; RapidFuzz y spaCy opcional para lenguaje; Vosk/sounddevice para transcripción; Edge TTS/pyttsx3 y pygame para voz; pandas y Matplotlib para análisis y gráficos. pyodbc conecta con SQL Server y Tkinter/ttkbootstrap presenta la interfaz. Las dependencias declaradas están en [requirements.txt](requirements.txt).

**5. ¿Dónde están modelos, algoritmos y entrenamiento?**

Pesos, etiquetas y resultados CNN: `modelos/`. YuNet, SFace y galería: `modelos/facial_embeddings/`. Vosk: `modelos_voz/vosk-model-small-es-0.42/`. Imágenes: `Clasificacion/rostros/DataSet01/data/`. Los algoritmos activos permanecen en la raíz; instalación, calibración y evaluación están en `herramientas/` y las regresiones en `pruebas/`.

### II. Modelos de reconocimiento facial

**6. ¿Cuál es el algoritmo facial actual?**

El motor configurado es `embeddings`: YuNet detecta caras y cinco landmarks; SFace alinea y extrae un vector de 128 componentes. Se compara con múltiples muestras de cada identidad mediante similitud coseno. Código: [ai/facial/pipeline_facial.py](ai/facial/pipeline_facial.py) y [ai/facial/reconocimiento_embeddings.py](ai/facial/reconocimiento_embeddings.py).

**7. ¿Cuál es el principal y cuáles las alternativas?**

Principal: YuNet 2023mar + SFace 2021dec, ambos ONNX preentrenados. Alternativa seleccionable: CNN propia con detector Haar Cascade en [ai/facial/reconocimiento_cnn.py](ai/facial/reconocimiento_cnn.py). Existe además un flujo LBPH de compatibilidad en `ai/facial/reconocimiento_facial.py`, sin uso visible como opción habitual de la interfaz. No se utilizan actualmente ArcFace, InsightFace, SCRFD ni RetinaFace en el motor principal.

**8. ¿Qué dataset se utiliza y cuántas imágenes/personas tiene?**

La carpeta contiene **255 imágenes y 18 etiquetas**: `subject01` a `subject15` tienen 11 GIF cada una, y `subject16`, `subject17`, `subject18` tienen 30 PNG cada una. El subconjunto activo en SQL y en las etiquetas CNN tiene **16 identidades y 195 imágenes**: las primeras 15 más `subject17`. La galería SFace tiene **192 embeddings**: 11 para cada una de las primeras 15 identidades y 27 para `subject17`.

Los GIF históricos corresponden al conjunto Yale según la documentación y estructura conservadas; las capturas PNG son ampliaciones locales. Una asociación en SQL no demuestra que la persona de una foto pública sea el empleado cuyo nombre aparece en la base. Esa correspondencia requiere verificación humana. Conteos y filtrado: [ai/facial/dataset_rostros.py](ai/facial/dataset_rostros.py), [etiquetas_rostros.json](modelos/etiquetas_rostros.json).

**9. ¿Qué preprocesamiento se aplica?**

SFace: detección YuNet, landmarks, recorte con margen, alineación `alignCrop` a 112×112, entrada BGR, normalización interna del modelo y normalización L2 del embedding. No se aplica conversión RGB adicional ni se amplía el rostro para fingir información a distancia.

CNN: gris, recorte Haar cuando corresponde, 100×100, `float32`, valores entre 0 y 1 y un canal. En entrenamiento hay aumento moderado de giro, escala, iluminación, ruido y degradación de resolución. El cargador CNN conserva como alternativa la imagen completa si Haar falla en una imagen histórica; esa excepción no equivale a reconocer una cara no detectada en cámara.

**10. ¿Son modelos preentrenados o propios?**

YuNet y SFace son preentrenados; no se ajustan sus pesos con empleados. El registro construye una galería de embeddings. La CNN sí se entrena localmente con las imágenes de las identidades activas. Vosk también utiliza un modelo preentrenado.

**11. ¿Qué arquitectura y entrenamiento tiene la CNN?**

Entrada 100×100×1; tres bloques Conv2D con 16, 32 y 64 filtros de 3×3, ReLU y MaxPooling2D; Flatten; Dense de 64 unidades ReLU; Dropout 0,3; salida softmax con 16 clases en el modelo registrado. Adam con learning rate inicial 0,001 y pérdida `sparse_categorical_crossentropy`. Batch 16, semilla 42, máximo 50 épocas; EarlyStopping con paciencia 8 y restauración del mejor peso, y ReduceLROnPlateau con factor 0,5, paciencia 4 y mínimo 10⁻⁶.

El número exacto de épocas ejecutadas no está guardado en el JSON de métricas, por lo que **no se afirma que se completaron 50**. Arquitectura: [ai/facial/modelo_cnn.py](ai/facial/modelo_cnn.py). Entrenamiento: [ai/facial/entrenar_cnn_rostros.py](ai/facial/entrenar_cnn_rostros.py).

**12. ¿Cómo se decide una identidad?**

SFace normaliza los vectores y calcula productos escalares, equivalentes a coseno. Para cada identidad promedia sus tres mejores similitudes, exige al menos cinco muestras y compara mejor candidato contra segundo candidato. Para reconocer necesita umbral, margen, calidad y consenso temporal; también valida la relación y actividad del empleado en SQL. El umbral debe proceder de `calibracion.json`, ligado mediante hashes a galería y configuración. **Ese archivo no está presente y no hay umbral operativo válido**, por lo que un candidato no debe convertirse en identidad autorizada.

La CNN usa softmax ≥0,65 y, en su flujo temporal, al menos tres coincidencias dentro de cinco predicciones, además de controles de calidad y relación SQL. Softmax y coseno son puntuaciones diferentes, y no prueban por sí solos una probabilidad de identidad calibrada.

**13. ¿Qué pruebas y métricas faciales existen?**

El JSON CNN conserva accuracy, precision, recall, F1 por clase y matriz de confusión sobre 39 imágenes de prueba: accuracy **92,31%**, precision macro **0,8958**, recall macro **0,9063**, F1 macro **0,8917**, F1 ponderado **0,9111**. Accuracy de entrenamiento y validación registrados: 100% y 100%. Inferencia guardada: **3,516 ms por imagen en un batch**; no equivale a FPS de cámara.

Un diagnóstico histórico SFace obtuvo 16/16 candidatos correctos reutilizando imágenes de su propia galería. Hay un benchmark de degradación de una imagen y una medición de cámara histórica de 43 frames/5 s, 8,6 FPS, con **cero frames con rostro**. Esos artefactos comprueban extracción/rendimiento, no identificación independiente. La herramienta permite medir FAR, FRR y confusión, pero no existe una calibración independiente real guardada que las respalde.

**14. ¿Cuántos aciertos, errores y no identificados hubo?**

CNN cerrada: **36 clasificaciones correctas y tres incorrectas sobre 39**. La matriz muestra una imagen `subject03` clasificada como `subject06`, y dos de `subject06` clasificadas como `subject01` y `subject14`. En esa evaluación se usa argmax entre clases conocidas, sin categoría desconocido: **no se midió el número de rechazos ni la falsa aceptación de personas desconocidas**.

Diagnóstico SFace histórico: 16 candidatos correctos de 16 imágenes reutilizadas. No hay una evaluación independiente suficiente para informar aciertos, falsos reconocimientos y no identificados del reconocimiento operativo. Cero frames con rostro en la medición de cámara no significa cero errores de identificación.

### III. Predicción de inventario

**15. ¿Qué método predice consumo o agotamiento?**

El método principal es consumo diario promedio observado y cobertura `stock total / consumo promedio`. No es una red neuronal ni un modelo de series temporales entrenado previamente. Código: [ai/prediction/prediccion_stock.py](ai/prediction/prediccion_stock.py).

**16. ¿Existe regresión o combinación de técnicas?**

Sí. Además del promedio, `LinearRegression` ajusta una recta al consumo diario y calcula una estimación auxiliar del consumo del día siguiente y cobertura asociada. La cobertura principal y la fecha de agotamiento se basan en el promedio, no en una proyección multidiaria de esa recta. La etiqueta AUMENTANDO/ESTABLE/DISMINUYENDO compara medias de la primera y segunda mitad del período; no se obtiene directamente de la pendiente.

**17. ¿Qué datos son entradas?**

Fechas y cantidades de movimientos `Salida` vigentes, producto, stock total actual, stock mínimo, fecha SQL de análisis, ventana elegida y horizonte de cobertura. Entradas y transferencias se excluyen del consumo. El stock global procede de las existencias de todas las ubicaciones.

**18. ¿Cuál es el mínimo de historial?**

La configuración activa exige **cinco días distintos con salidas dentro de la ventana**, no cinco detalles ni cinco días calendario con valores cero. Las ventanas permitidas son 7, 30, 60 y 90 días; la actual es 30. Ese mínimo es una regla de suficiencia implementada, **no una garantía estadística de predicción confiable**.

**19. ¿Cómo se calculan consumo y días restantes?**

Se suman salidas por fecha y se construye una serie desde la primera salida disponible dentro de la ventana hasta la fecha de análisis, incluyendo días intermedios sin salidas como cero. Consumo medio = cantidad total de salidas / días calendario de esa serie. Días restantes = stock total / consumo medio. Con stock positivo y consumo positivo, la fecha estimada es fecha de análisis + techo de días restantes; se evita producir fechas extremas imposibles.

**20. ¿Qué ocurre con pocos movimientos o ausencia de consumo?**

Se devuelve `datos_suficientes=False`, riesgo SIN DATOS y fecha/cobertura no disponibles. Sin consumo reciente se informa expresamente ese estado. Los días sin salidas sí se incluyen al calcular la media cuando existe historial. No se fabrica una fecha y no se cuentan transferencias como consumo.

**21. ¿Hubo separación entrenamiento-prueba?**

No hay partición de entrenamiento/prueba ni validación temporal de rendimiento para este motor. El promedio se calcula directamente y la regresión se ajusta a la serie disponible. No se ha implementado un backtest con fechas de corte para evaluar predicciones fuera del período usado para ajustarlas.

**22. ¿Qué métricas predictivas se midieron?**

No hay resultados guardados de MAE, RMSE o MAPE. Los casos de regresión de software comprueban fórmulas, ventanas, ausencia de consumo y preservación del stock global; no miden error predictivo sobre observaciones futuras.

**23. ¿Qué resultados existen y cómo se contrastaron con operación real?**

En la consulta actual, **tres productos de 24** cumplen el mínimo de la ventana de 30 días: `TOR-002`, `FIL-001` y `CAB-001`; 21 no lo cumplen. La base tiene 253 movimientos entre el 10 de julio y el 6 de octubre de 2026. La disponibilidad cambia con la fecha de análisis y la ventana, por lo que conteos de informes anteriores no son el estado actual.

Se verificaron cálculos e integración, pero **no se ha contrastado la fecha prevista contra agotamientos reales observados posteriormente**. Parte del historial fue construido mediante scripts de carga; su presencia en SQL no demuestra procedencia operativa independiente. No puede declararse una precisión predictiva real a partir de esos datos.

### IV. Detección de anomalías

**24. ¿Qué método detecta movimientos inusuales?**

El flujo principal utiliza estadística explicable por producto y tipo de movimiento en [ai/anomalies/deteccion_anomalias.py](ai/anomalies/deteccion_anomalias.py). Cada detalle se compara solo con antecedentes anteriores. Isolation Forest permanece como función heredada separada, no como decisión principal de la pantalla de Anomalías.

**25. ¿Son reglas fijas, desviación estándar o Z-score?**

Si existe variación, el score es `(cantidad − promedio previo) / desviación estándar poblacional previa`. Si la desviación es cero y el promedio es positivo, utiliza `cantidad / promedio`. Se considera inusual una cantidad superior al promedio cuyo score alcance la sensibilidad configurada, actualmente **3,0**. Es una detección unilateral de excesos, no una búsqueda de cualquier desviación positiva o negativa.

**26. ¿Qué variables se analizan?**

Cantidad, producto, tipo y orden cronológico. Entradas, salidas y transferencias tienen grupos separados; los ajustes no entran en esta detección principal. Empleado y ubicaciones acompañan el detalle, pero no son variables del score principal. Hora, día de semana y stock anterior pertenecen a la alternativa Isolation Forest, junto con cantidad.

**27. ¿Cómo se identifica una cantidad inusual?**

El candidato se evalúa antes de incorporarlo al historial, para evitar contaminar su propia referencia. Se exige el mínimo de antecedentes del mismo producto y tipo, luego se aplica la fórmula anterior. Con los límites actuales, score ≥6 es CRÍTICA, ≥4 ALTA, ≥3 MEDIA; BAJA puede aparecer si la sensibilidad se reduce por debajo de 3. Score no significa porcentaje de anomalía ni prueba de fraude.

**28. ¿Qué pasa con historial pequeño?**

Antes de **10 movimientos previos** del mismo producto y tipo, el candidato no recibe clasificación estadística. Si ningún candidato alcanza ese mínimo se informa insuficiencia. Una ausencia de hallazgos con pocos datos no demuestra comportamiento normal.

**29. ¿Se usaron datos reales o sintéticos?**

Las regresiones usan cantidades controladas en memoria y registros SQL creados dentro de transacciones que se revierten. El historial ampliado del almacén procede principalmente de una carga programada con patrones de consumo y unos pocos valores inusuales deliberados. Por tanto, incluye **datos sintéticos de evaluación**, aunque nombres, códigos y relaciones sean naturales y estén guardados en SQL. También se conservaron datos anteriores cuya procedencia operativa no está acreditada en los artefactos inspeccionados. No debe presentarse este conjunto como un estudio exclusivamente de movimientos reales del taller.

**30. ¿Cuántas anomalías hubo y cuántas se confirmaron?**

El análisis actual lee **230 detalles** dentro de la ventana configurada de 90 días, evalúa **37** con antecedentes suficientes y detecta **tres**. Los tres hallazgos persistidos están **PENDIENTE**; ninguno aparece REVISADA ni JUSTIFICADA. Los escenarios de carga incluyeron salidas altas de tornillos, filtros y cable, pero no existe confirmación humana independiente de tres incidentes operativos reales. Pendiente no equivale a falso ni a verdadero.

**31. ¿Se midieron falsos positivos y negativos?**

No hay un conjunto de movimientos reales etiquetados por expertos que permita calcular precision, recall, F1, falsos positivos o falsos negativos operativos. Las regresiones verifican sensibilidad, mínimo de historial y separación de grupos, no tasas reales de error.

### V. Procesamiento del lenguaje natural y JARVIS

**32. ¿Cómo se interpretan consultas escritas o habladas?**

Vosk transforma voz en texto. Texto y transcripción pasan por el mismo agente. Se normaliza el texto, se clasifica intención, se extraen entidades con patrones y se resuelven contra catálogos SQL. Reglas de respaldo, contexto y herramientas completan la consulta. Ollama puede proponer una intención y entidades en JSON, que Python valida antes de ejecutar herramientas; su uso es opcional.

**33. ¿Qué hacen scikit-learn, RapidFuzz y spaCy?**

scikit-learn construye TF-IDF y el clasificador de intenciones. RapidFuzz compara nombres/tokens de forma aproximada; si falta utiliza `SequenceMatcher`. spaCy aporta análisis lingüístico y lemas cuando `es_core_news_sm` está instalado; si falta se utilizan tokens normalizados. **En esta revisión spaCy no está activo**, aunque el código conserva su soporte.

**34. ¿Existe un clasificador entrenado de intención?**

Sí: regresión logística multiclase sobre unión de TF-IDF de palabras de uno/dos términos y caracteres `char_wb` de tres a cinco caracteres. Se entrena en memoria al crear `ProcesadorNLPJarvis`, a partir del JSON local. Código: [jarvis/nlp_jarvis.py](jarvis/nlp_jarvis.py).

**35. ¿Cuántas frases e intenciones tiene?**

El archivo actual contiene **226 frases en 32 intenciones**: stock, ubicación, último retiro, último movimiento, historial de producto, stock mínimo, stock bajo, agotados, alertas, empleado, movimientos, resumen, predicción, anomalías, movimientos de empleado, subject, rostro del empleado, listado de rostros, empleados sin rostro, reabastecimiento, producto, listado de productos, menor stock, empleados activos, movimientos de hoy, alertas de reconocimiento, rostro y movimientos, saludo, agradecimiento, despedida, nombre del asistente y ayuda. Fuente: [intenciones_jarvis.json](intenciones_jarvis.json).

**36. ¿Cómo se manejan ambigüedad, desconocidos y errores?**

Se eliminan tildes y variaciones de caja, se reconocen algunas variantes de «Jarvis», se combinan n-gramas y búsqueda aproximada. La intención se rechaza si su probabilidad máxima es menor que **0,38**; después el agente intenta reglas de respaldo. Una entidad solo se selecciona automáticamente cuando queda una coincidencia válida; varias coincidencias requieren aclaración. Si no existe un producto o una consulta no se entiende, se informa y no se inventan cantidades ni ubicaciones.

**37. ¿Qué evaluación de intenciones existe?**

Se ejecutaron hoy las 18 frases de `tests/probar_nlp_jarvis.py`, ninguna idéntica a una frase del JSON de entrenamiento: **14 correctas (77,78%)**. Las otras cuatro se rechazaron por baja confianza: «operacion mas nueva del motor», «actividad anterior del taladro», «quien fue responsable de sacar el producto» y «cómo debo dirigirme a ti». En este conjunto no se asignaron esas cuatro a otra intención: quedaron sin clasificación aceptada.

La prueba de cobertura del agente, que combina clasificador y reglas, obtuvo **40/40** en cinco formulaciones de cada una de ocho capacidades. Es otro conjunto y otro flujo; no debe atribuirse ese 100% al clasificador aislado. No hay validación cruzada, intervalos de confianza ni evaluación extensa de consultas reales no vistas.

### VI. Entrenamiento y configuración

**38. ¿Qué necesita entrenamiento?**

CNN propia: entrenamiento supervisado. Clasificador de intención: entrenamiento supervisado local en memoria. YuNet/SFace y Vosk: pesos preentrenados; la galería facial requiere registro y calibración, no reentrenar SFace. Predicción principal y anomalías estadísticas calculan parámetros del historial. La regresión lineal auxiliar y el Isolation Forest heredado sí se ajustan a datos disponibles cuando se invocan. No se entrena un LLM propio en el proyecto.

**39. ¿Qué archivos entrenan y cuáles infieren?**

`ai/facial/modelo_cnn.py` define la arquitectura y `ai/facial/entrenar_cnn_rostros.py` entrena/evalúa; `ai/facial/reconocimiento_cnn.py` infiere. `jarvis/nlp_jarvis.py` entrena e interpreta; `jarvis/agente_inventario.py` orquesta. `ai/facial/pipeline_facial.py` extrae/compara y `ai/facial/reconocimiento_embeddings.py` integra cámara/registro. `ai/facial/diagnostico_facial_basico.py` regenera la galería; `tools/evaluar_reconocimiento_facial.py` calibra/evalúa. `ai/prediction/prediccion_stock.py` y `ai/anomalies/deteccion_anomalias.py` calculan los análisis de inventario.

**40. ¿Cuáles son los parámetros y cómo se eligieron?**

CNN: Adam 0,001; batch 16; máximo 50 épocas; Dropout 0,3; aceptación softmax 0,65 y tres coincidencias de cinco. NLP: regresión logística `C=8`, `max_iter=1500`, clases balanceadas, semilla 42, umbral 0,38; similitud aproximada mínima 0,76 y candidatos cercanos al mejor dentro de 0,04.

YuNet: score detector 0,9, NMS 0,3 y top-k 5000. Facial operativo: rostro mínimo 80 px; nitidez Laplaciano ≥45; iluminación 45–210; roll ≤35°; yaw relativo ≤0,65; cuatro muestras en ventana de siete, consenso ≥0,8 y evidencia de dos segundos; detección cada tres frames o al vencer 0,25 s. Umbral de identidad y margen se obtienen de calibración, hoy ausente.

Predicción: ventana 30 días, mínimo cinco días con salidas, horizonte 30; riesgo crítico por stock/cobertura ≤3 días y alto por stock mínimo/cobertura ≤7. Anomalías: 90 días, mínimo 10 antecedentes, sensibilidad 3,0. Isolation Forest heredado: mínimo 30 salidas, contaminación 0,05, semilla 42. Los valores están definidos por diseño y configuración; **no hay evidencia de una optimización comparativa formal** de todos ellos.

**41. ¿Cómo se separan ajuste y evaluación?**

CNN: separación estratificada por imagen, 80/20 inicial y división 80/20 del bloque de desarrollo. Con 195 imágenes resultan **124 de entrenamiento, 32 de validación y 39 de prueba**: aproximadamente 64/16/20. Imágenes de una misma identidad aparecen en las particiones; no se ha acreditado separación por sesión de captura. Aumento solo en entrenamiento.

La calibración SFace está implementada con sesiones separadas y exige, en cada conjunto de calibración/prueba, al menos 20 conocidas y 20 desconocidas, cobertura de todas las identidades y desconocidos de calidad suficiente. **Ese procedimiento no se ha completado con un artefacto válido actual**. NLP tiene un conjunto pequeño separado de frases, sin validación cruzada. Predicción/anomalías no cuentan con backtest o validación etiquetada independiente; evitar que el candidato entre en su referencia histórica no sustituye esas evaluaciones.

**42. ¿Cómo se guardan y actualizan?**

CNN: `.keras`, etiquetas JSON, métricas JSON y gráficas PNG. Solo sustituye el modelo si entrenamiento y prueba alcanzan 0,60; guarda respaldo del anterior. SFace: pesos ONNX; galería `.npz` con vectores, etiquetas, IDs y hashes de imágenes; calibración JSON ligada a hashes de galería/configuración/pipeline. Cambios en esos recursos invalidan una calibración incompatible.

El clasificador NLP no tiene un pickle/joblib guardado: vuelve a entrenarse al iniciar el proceso a partir de `intenciones_jarvis.json`. Configuración: `config_sistema.json` y compatibilidad facial JSON. El promedio, regresión auxiliar e Isolation Forest heredado no se guardan como modelos persistentes. Hallazgos de anomalías y sus estados sí se conservan en SQL.

**43. ¿Se compararon algoritmos/configuraciones?**

El proyecto conserva CNN/Haar y YuNet/SFace, promedio y regresión, y estadística e Isolation Forest. Hay un benchmark facial de degradación de una sola imagen y regresiones de políticas de calidad/consenso. **No existe un ensayo común con el mismo conjunto independiente que demuestre qué alternativa gana**. La búsqueda de parámetros de calibración SFace está programada, pero falta ejecutarla con evidencia real suficiente.

### VII. Resultados y selección

**44. ¿Qué resultados cuantitativos tiene cada componente?**

CNN: 36/39 y 92,31% de accuracy cerrada; F1 macro 0,8917. SFace: galería 192×128 y diagnóstico histórico 16/16 reutilizado, sin FAR/FRR operativo. NLP: 14/18 aislado y cobertura híbrida 40/40. Predicción: tres productos suficientes y 21 insuficientes hoy, sin métricas de error. Anomalías: tres hallazgos, todos pendientes; 230 detalles disponibles y 37 evaluables en la ventana. Voz y LLM no tienen WER, latencia de audio extremo a extremo ni exactitud experimental vigente documentadas.

**45. ¿Qué métricas sirven para comparar y por qué?**

Se guardaron accuracy, precision, recall, F1 y confusión de la CNN para describir errores y clases desbalanceadas. SFace incluye herramientas de FAR/FRR y tasa de identidad incorrecta, importantes para distinguir rechazo y aceptación indebida, pero no dispone de resultados operativos válidos. NLP se comprobó mediante proporción de frases correctas y cobertura funcional. Predicción requeriría MAE/RMSE y cobertura/agotamiento observado; MAPE exige cautela con días de consumo cero. Anomalías requeriría precision/recall/F1 sobre etiquetas humanas. Estas últimas son pruebas pendientes, no métricas ya obtenidas.

**46. ¿Qué técnica obtuvo los mejores resultados?**

No puede declararse un ganador empírico por falta de comparación independiente común. La CNN es la única alternativa facial con métricas de clasificación cerrada guardadas, pero eso no demuestra superioridad operativa sobre SFace. El agente combinado supera al clasificador aislado en su suite de cobertura, aunque las suites son diferentes. Promedio y estadística son las técnicas activas de inventario, sin demostración experimental de que superen a todas las alternativas.

**47. ¿Qué limitaciones se identificaron?**

Pocas imágenes y mezcla de fotos públicas/capturas locales; correspondencias empleado-foto que requieren verificación; falta de calibración facial y de desconocidos independientes; partición CNN por imagen y no por sesión, con entrenamiento/validación perfectos que no prueban generalización. No hay alcance validado en metros. NLP tiene cuatro rechazos en una evaluación pequeña y spaCy no está activo. Predicción supone consumo estable y ausencia de nuevas entradas; ahora tiene historial suficiente en pocos productos. Anomalías solo detecta excesos de cantidad y carece de etiquetas humanas. El historial programado no acredita operación real y los tiempos de batch no representan latencia completa de cámara.

**48. ¿Qué técnicas se seleccionaron y con qué criterios?**

Configuración vigente: YuNet/SFace como principal por extracción consistente, operación local y posibilidad de rechazo calibrado; CNN queda como alternativa. JARVIS usa TF-IDF/regresión logística con búsqueda aproximada y reglas por su ejecución local y consultas controladas. Vosk transcribe localmente. Stock usa promedio observado como estimación principal y regresión auxiliar; anomalías usa estadística por producto/tipo por su explicación e integración transaccional. Esos son criterios de implementación y mantenibilidad; no resultados de una competición experimental.

**49. ¿Qué mejoras hacen falta antes de operación real?**

Verificar identidades y registrar personas reales con sesiones variadas; calibrar con conocidos/desconocidos y evaluar video temporal en la cámara instalada. Separar sesiones para medir generalización, registrar versiones y hashes de modelos/datasets/métricas. Obtener historial operativo verificable; realizar backtests temporales y contrastar agotamiento/reabastecimiento. Etiquetar anomalías con responsables del almacén y medir errores. Ampliar la evaluación de lenguaje con consultas externas al catálogo de frases; medir WER, ruido, silencio, eco y tiempos de audio. Ninguna mejora debe basarse en bajar umbrales sin evaluación.

### VIII. Evidencias y documentación

**50. ¿Dónde se comparte el código y la configuración?**

- Facial: [ai/facial/pipeline_facial.py](ai/facial/pipeline_facial.py), [ai/facial/reconocimiento_embeddings.py](ai/facial/reconocimiento_embeddings.py), [ai/facial/reconocimiento_cnn.py](ai/facial/reconocimiento_cnn.py), [ai/facial/modelo_cnn.py](ai/facial/modelo_cnn.py), [ai/facial/entrenar_cnn_rostros.py](ai/facial/entrenar_cnn_rostros.py), [ai/facial/dataset_rostros.py](ai/facial/dataset_rostros.py).
- Evaluación y calibración: [evaluar_reconocimiento_facial.py](tools/evaluar_reconocimiento_facial.py), [ai/facial/diagnostico_facial_basico.py](ai/facial/diagnostico_facial_basico.py).
- Inventario analítico: [ai/prediction/prediccion_stock.py](ai/prediction/prediccion_stock.py), [ai/anomalies/deteccion_anomalias.py](ai/anomalies/deteccion_anomalias.py).
- JARVIS: [jarvis/nlp_jarvis.py](jarvis/nlp_jarvis.py), [jarvis/agente_inventario.py](jarvis/agente_inventario.py), [jarvis/asistente_voz.py](jarvis/asistente_voz.py), [jarvis/llm_jarvis.py](jarvis/llm_jarvis.py).
- Configuración: [config_sistema.json](config_sistema.json), [reconocimiento_facial_config.json](reconocimiento_facial_config.json), [intenciones_jarvis.json](intenciones_jarvis.json).

**51. ¿Qué resultados, gráficas y capturas existen?**

CNN: [métricas y matriz numérica](modelos/metricas_modelo_rostros.json), [matriz de confusión](modelos/matriz_confusion_rostros.png) y [curvas de entrenamiento](modelos/entrenamiento_rostros.png). Facial: [diagnóstico de reutilización](evaluacion_facial/diagnostico_basico.json), [matriz de similitud](evaluacion_facial/matriz_similitud.csv), [benchmark de degradación](evaluacion_facial/benchmark.json), [medición histórica de cámara](evaluacion_facial/rendimiento_camara_local.json). Son artefactos conservados, con las limitaciones indicadas; no se generaron nuevas capturas de personas en esta revisión.

Las pruebas de software y los casos lingüísticos están en `pruebas/`. Los resultados nuevos de lectura y comprobación se registran en esta sección, sin crear otro archivo Markdown ni añadir resultados experimentales inventados.

**52. ¿Existe documentación de arquitectura y parámetros?**

Sí, este `README.md` reúne instalación, arquitectura, integración, informes previos y este cuestionario actualizado. Para el estado de IA prevalecen esta revisión y las configuraciones actuales sobre cifras históricas de otras secciones. El código citado permite comprobar fórmulas y valores efectivos.

**53. ¿Qué componentes todavía carecen de resultados experimentales y qué falta?**

YuNet/SFace carece de validación independiente abierta de identidad y calibración válida; faltan FAR/FRR, confusión y evaluación temporal con desconocidos en campo. CNN carece de evaluación por sesiones independientes y de aceptación de desconocidos. Predicción carece de errores sobre períodos futuros separados. Anomalías carece de verdad de referencia operativa etiquetada. Voz carece de WER/ruido y latencia real documentados; Ollama carece de evaluación comparativa de intenciones y robustez. NLP sí tiene una evaluación pequeña reproducida, pero falta ampliar el conjunto y reportar métricas por intención. Aprobar regresiones de software no sustituye estas pruebas.

### Reproducción de las comprobaciones realizadas

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m tests.probar_nlp_jarvis
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s pruebas -p "probar_cobertura_jarvis.py" -v
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s pruebas -p "probar_*.py" -q
```

La primera mide el NLP aislado; la segunda, cobertura del agente; la tercera, comportamiento de software y regresiones, incluyendo casos SQL que revierten sus registros. El aviso «sounddevice: ocupado» corresponde a un error simulado del caso que comprueba micrófono ocupado; no demuestra fallo del micrófono físico. Los porcentajes CNN proceden de métricas previamente guardadas: no se repitió su entrenamiento.

<a id="jarvis-conversacional"></a>

## Motor conversacional JARVIS — actualización del 11 de octubre de 2026

Esta actualización modifica el asistente existente y mantiene un solo punto de entrada:
`agente_inventario.procesar_consulta`. Texto de la interfaz, transcripción de voz,
API y las funciones antiguas `procesar_pregunta`/`procesar_consulta_estructurada`
pasan por ese motor. No se creó otro asistente ni se modificaron modelos faciales,
motor predictivo, esquema SQL o dependencias de audio.

### Problemas encontrados y correcciones

Antes había una extensión de stock/mapa/predicción y un procesador general con
prioridades superpuestas. Los seguimientos dependían de listas pequeñas de frases;
los candidatos ambiguos no se conservaban; coincidencias por una sola palabra
podían mezclar «filtro de aire» y «filtro de aceite». Una explicación podía recuperar
una predicción anterior después de cambiar de tema. Algunos casos de movimientos
podían caer en señales genéricas de stock. La extensión anterior se retiró.

El router ahora considera primero el dominio explícito, después la intención,
las entidades y la memoria necesaria. Movimientos, anomalías y contenido de
ubicaciones tienen prioridad sobre señales como «cuántos». Las capacidades
generales, empleados, rostros, alertas y ayuda se conservan mediante el adaptador
interno de compatibilidad. Ese adaptador ya no es un punto de entrada independiente.

### ConversationContext

`ConversationContext` centraliza producto actual y anterior, empleado, categoría,
ubicaciones, intención, último resultado, predicción, anomalía, movimiento,
listas/candidatos y plan/filtros pendientes. Mantiene los últimos **20 turnos**.
Un bloqueo por conversación serializa mensajes; ContextVar evita que dos
conversaciones mezclen sus entidades en distintos hilos. La API permite un
identificador de conversación opcional; no es una cuenta ni autenticación.

La sesión predeterminada es `escritorio`. Cuando todos los canales están en el
mismo proceso comparten esa memoria. Si Uvicorn se ejecuta como proceso separado,
su memoria es independiente: comparten código y comportamiento, pero no memoria
entre procesos. No se añadió SQL ni un servicio externo para persistir diálogos.
El registro está limitado a 64 conversaciones por proceso.

El inicio de la aplicación y **Reiniciar contexto** limpian referencias,
candidatos, planes, resultados e historial. El botón muestra «Contexto reiniciado».
Seleccionar un producto y abrir JARVIS desde Productos o el botón de cabecera
puede establecer su identidad como contexto visual; el stock se consulta después.

### Referencias, entidades y ambigüedad

«¿Dónde están?», «¿Cuánto queda?», «Muéstramelos», «¿Cuánto durarán?» y
«¿Y ese?» reutilizan el producto únicamente cuando no se escribió otra entidad.
Una referencia sin producto pide aclaración. «El anterior» recupera la identidad
previa. Un nombre nuevo desconocido no se reemplaza silenciosamente por el anterior.

Los candidatos se numeran y conservan el plan completo. «El segundo» o «el de
aceite» seleccionan dentro de esa lista y ejecutan la consulta pendiente,
incluida stock más ubicación. Los números fuera de rango no seleccionan nada.
«¿Qué hay ahí?» usa una ubicación anterior; si había varias solicita selección.
Las anomalías conservan lista, filtros y selección para «¿Cuál es la más grave?»
y «¿Por qué fue marcada?». Los empleados pueden resolverse por nombre/código,
y sus seguimientos usan el dominio del empleado.

La búsqueda normaliza tildes/caja, singular-plural y variantes fonéticas limitadas,
sin sustituir nombres arbitrarios. Puntúa todas las palabras relevantes: una
palabra compartida no basta para elegir entre artículos distintos. Nombres/códigos
exactos tienen prioridad. Se comprobaron «filto de aseite», «motro electrico»
y «tornyo», además de rechazos con coincidencias débiles.

La extracción comprende zona, estante, pasillo, código de ubicación, categoría,
tipo de movimiento, niveles y cantidades de lectura. Para movimientos/anomalías
admite hoy, ayer, semana actual, mes actual, últimos N días (1–365) y fecha ISO.
Los rangos son inclusivos y se calculan en UTC−6. No interpreta una cantidad
como autorización para registrar movimientos.

### Servicios y respuestas

`jarvis/herramientas_jarvis.py` concentra los adaptadores de datos y reutiliza
`inventario_service`, `movimientos.buscar_movimientos`, `mapa_almacen`,
`prediccion_stock` y `deteccion_anomalias.listar_anomalias`. Movimientos admite
ahora el filtro parametrizado de empleado. Los campos espaciales provienen de
una lista blanca y los valores de SQL se pasan como parámetros.

Cada consulta obtiene stock y datos vigentes. Guardar una identidad/lista no
convierte un resultado anterior en stock actual. Un fallo de conexión responde
«No pude consultar la base de datos en este momento». JARVIS no recalcula ni
persiste anomalías al consultarlas; predicción usa `actualizar_alertas=False`.
Las respuestas separan `datos`, `respuesta`, `voz` y `acciones_ui`.

La ubicación produce acciones para resaltar el producto en el mapa; el motor
no afirma que el mapa ya cambió antes de que Tkinter ejecute esas acciones.
Predicción utiliza el mismo motor existente, sin duplicar cálculos. Se conserva
la insuficiencia de historial. La combinación «productos bajos y cuál se agotaría
primero» evalúa las predicciones de ese conjunto, utilizando IDs para no confundir
productos de nombres iguales.

Las respuestas de stock usan unidades naturales y omiten repetir el nombre en
seguimientos claros. Las explicaciones vuelven a consultar el dominio adecuado.
Las listas largas se muestran en pantalla y se resumen por voz. Los códigos de
ubicación se conservan en texto; la voz usa la jerarquía registrada.

### Voz, interfaz y depuración

Se mantienen Vosk, sounddevice, Edge TTS/pyttsx3, colas de eventos, burbujas y
scroll. SQL/NLP/TTS siguen fuera del hilo Tkinter. Mientras TTS habla no se inicia
escucha. Una nueva consulta escrita en modo manual detiene TTS y espera su evento
de finalización antes de procesarla; no habilita el micrófono durante el habla.

`DEBUG_JARVIS=True` o la variable `JARVIS_DEBUG=1` activa trazas mediante el logger `jarvis`: entrada normalizada,
intención/plan, entidades, origen del contexto, dominio y respuesta estructurada.
No se muestran en el chat ni se guarda el historial en SQL. Los modelos NLP y
Vosk mantienen su carga existente por proceso; no se cachea stock.

### Archivos y validación

Modificados: `jarvis/agente_inventario.py`, `jarvis/nlp_jarvis.py`, `intenciones_jarvis.json`,
`jarvis/herramientas_jarvis.py`, `jarvis/jarvis_personality.py`, `inventory/movimientos.py`, `jarvis/api_jarvis.py`,
`ui/interfaz.py`, este README y las regresiones de agente, inventario y voz.
Creado: `tests/probar_contexto_jarvis.py`, con **28 casos de conversación**.
Consolidado: la antigua extensión `_consulta_central` en el router y contexto
comunes. No se añadieron módulos de producción ni dependencias.

El catálogo lingüístico pasó de 226 a **258 frases**, manteniendo 32 intenciones.
Se añadieron 32 formulaciones, sin copiar las 18 frases exactas de evaluación.
El NLP aislado pasó de **14/18 a 17/18 (94,44%)** en ese conjunto conocido;
todavía rechaza por baja confianza «cómo debo dirigirme a ti», que el motor
conversacional atiende mediante una señal social explícita. No es una evaluación
ciega ni demuestra exactitud universal. La suite de cobertura continúa separada.

La suite completa ejecutó **135 casos: 134 aprobados y uno omitido** por falta de
FastAPI. Las pruebas cubren contextos aislados y concurrentes, stock fresco,
candidatos, pronombres, fechas, explicaciones por dominio, mapa, fallo SQL,
reinicio y cancelación de TTS sin eco. Los casos SQL revierten sus registros.

Con SQL real se comprobó una conversación completa: FIL-001 → ubicación en dos
sitios → mapa → predicción → FIL-002 → estado → explicación → anomalías → mayor
gravedad → motivo → movimientos por fecha → contenido de Zona A. Los recuentos
de productos, existencias, movimientos, detalles, alertas, anomalías, empleados
y relaciones faciales permanecieron iguales durante esa verificación de lectura.
Los valores procedieron de SQL, no de los valores conceptuales de la solicitud.

La aplicación inició y se comprobaron selección visual y Reiniciar contexto sin
errores de callbacks. No se validaron micrófono o altavoces físicos en esta etapa;
la coordinación de audio se comprobó con regresiones. Falta instalar FastAPI para
ejecutar la API HTTP opcional. No se soportan combinaciones infinitas de intenciones
ni referencias sin antecedente suficiente; se pide aclaración en esos casos.


## JARVIS central: arquitectura, herramientas y confirmaciones

La revisión encontró un motor que ya compartía `ConversationState`, un router
por dominio y servicios de lectura, pero mantenía rutas de compatibilidad con
resultados de distintas formas. Faltaban el contrato común, la preparación de
entradas/salidas/transferencias y algunos seguimientos entre dominios. Se amplió
esa arquitectura de manera incremental, conservando las capacidades existentes.

La entrada pública es `jarvis.procesar(mensaje, session_id, origen)`. Devuelve
`JarvisResult` con `ok`, `intent`, `respuesta`, `datos`, `accion_ejecutada`,
`requiere_confirmacion` y `requiere_aclaracion`. `to_dict()` conserva también los
campos compatibles `intencion`, `voz`, `acciones_ui`, archivos y métricas.

El flujo es: adaptador de canal → normalización → router y resolución de
entidades → contexto de sesión → plan → herramienta autorizada → presentación
del resultado. `jarvis/jarvis.py` no añade otro clasificador ni otra memoria.
`jarvis/jarvis_router.py` conserva el planificador; `jarvis/jarvis_capacidades.py` registra las
capacidades adicionales mediante reglas declarativas; `jarvis/jarvis_acciones.py`
prepara movimientos sin escribir. `jarvis/herramientas_jarvis.py` mantiene el catálogo
central, y `jarvis_tools/` añade adaptadores mínimos y políticas de confirmación.
El LLM local opcional conserva su lista de decisiones de lectura: no genera SQL
y no obtiene autorización para ejecutar escrituras por proponer una herramienta.

Archivos creados en esta ampliación: `jarvis/jarvis.py`, `jarvis/jarvis_acciones.py`,
`jarvis/jarvis_capacidades.py`, `jarvis/tools/__init__.py`, `jarvis/tools/acciones.py` y
`tests/probar_cerebro_central.py`. Se modificaron `jarvis/agente_inventario.py`,
`jarvis/jarvis_router.py`, `jarvis/jarvis_consultas.py`, `jarvis/herramientas_jarvis.py`, `ui/interfaz.py`,
`integrations/telegram/telegram_bot_service.py`, `jarvis/api_jarvis.py`, `tests/probar_agente_avanzado.py`,
`tests/probar_orquestador_jarvis.py` y
este documento. No se modificaron SQL, esquema, mapa, motores CNN/SFace/YOLO,
predicción, detección de anomalías, Arduino ni la arquitectura de audio.

### Contexto y canales

`desktop` y `escritorio` identifican la misma conversación. El adaptador de
escritorio y la entrada de voz llaman a `jarvis.procesar_consulta`, que delega en
`procesar`; mantienen el mismo contexto. Telegram llama a `procesar` con origen
`telegram` y sesión `telegram:<chat_id>`. La API opcional usa origen `api`. Los
servicios de notificaciones automáticas de Telegram conservan su funcionamiento.

La memoria conserva producto, empleado, ubicación, movimiento, alerta, anomalía,
intención, candidatos, resultados y última acción. Las claves `pending_intent`,
`pending_entity` y `pending_confirmation` son alias del mismo estado existente,
no copias independientes. Se admiten hasta 64 sesiones y 20 turnos de historial
corto por sesión. Cada conversación tiene un bloqueo reentrante para ordenar
consultas y confirmaciones concurrentes. Reiniciar contexto vacía su memoria.

Una intención incompleta conserva lo solicitado. Después de «Ubicación», el
nombre de un producto completa la localización; no se vuelve a preguntar qué
operación realizar. Los candidatos ambiguos permanecen disponibles para elegir
por nombre, código o número. Los seguimientos de alertas conservan su nivel;
las consultas temporales de movimientos conservan las entidades explícitas,
incluso cuando la consulta anterior no tuvo filas. Una consulta global nueva
mantiene su alcance global. Las cantidades de unidades diferentes se presentan
por separado.

### Lecturas, acciones y política central

Las lecturas consultan servicios existentes. No se fabrican cantidades, nombres,
ubicaciones, resultados biométricos ni predicciones. El estado distingue
componentes comprobados, modelos presentes pero no cargados, servicios sin
verificar y simulación. Consultar estado no abre cámara ni micrófono y no
reproduce audio. La clasificación facial desconocida requiere un evento explícito
de desconocido; no se deduce de un rostro no visible o de una evaluación pendiente.

No requieren confirmación: consultas, búsqueda, navegación y mapa, consulta de
estado, vista previa o exportación de reportes y luces de localización. Se
conservó el apagado global de LEDs como acción reversible de localización.
Las exportaciones solicitadas sin formato usan PDF; Excel debe indicarse. La
respuesta y el resultado estructurado informan la ruta del archivo generado.

Requieren confirmación: entradas, salidas, transferencias, ajustes de stock,
aplicación de un conteo completo, atención de alertas e inicio/parada de vigilancia.
Las eliminaciones y cambios de configuración no se ofrecen desde conversación:
se mantienen en sus pantallas. No se agregaron cuentas, roles ni autenticación.

Un movimiento conserva producto, cantidad decimal, origen/destino y responsable
explícito. Si falta alguno, pregunta antes de preparar la acción. No asigna
automáticamente un empleado. Los servicios reales mantienen las transacciones,
disponibilidad, capacidad física y validaciones. Los productos con control de
lotes deben operarse desde Movimientos, donde ya existe la selección de lote.

La confirmación conserva la acción y parámetros durante 120 segundos. Se consume
antes de ejecutar; «sí» repetido no vuelve a escribir. Se vuelven a consultar las
entidades y, para salidas/transferencias, el saldo de origen. Un cambio invalida
la propuesta. Los ajustes y conteos conservan sus comprobaciones transaccionales
existentes. Cancelar, «no», «olvídalo» o «mejor no» elimina la propuesta; una nueva
consulta sustantiva no la ejecuta. Un fallo no provoca reintentos automáticos de
escritura. El listener Telegram conserva su cursor persistente contra entregas
repetidas. La entrada central admite además `event_id`, con hasta 128 resultados
por sesión para reintentos dentro del proceso. Esto no equivale a una garantía
durable de ejecución exactamente una vez frente a cualquier caída del equipo.

### Intenciones y capacidades soportadas

| Dominio | Intenciones/capacidades |
|---|---|
| Productos | `buscar_producto`, `productos_listar`, `productos_contar`, `productos_ultimo`, `productos_primero`, `productos_maximo`, `productos_minimo`, `producto_detalle`, `consultar_producto` |
| Stock | `consultar_stock`, `stock_minimo`, `stock_bajo`, `stock_bajo_resumen`, `productos_agotados`, `stock_categoria`, `stock_por_ubicacion`, resumen de inventario |
| Ubicaciones y mapa | `consultar_ubicacion`, `contenido_ubicacion`, `ubicaciones_contar`, `ubicaciones_maximo`, `consultar_led`, `abrir_mapa`, acciones `producto_mapa` y `ubicacion` |
| Movimientos | `consultar_movimientos`, `movimientos_listar`, `movimientos_contar`, `movimientos_ultimo`, `movimientos_primero`, `movimientos_maximo`, `movimientos_minimo`, `movimientos_comparar`, `movimientos_sumar`, `movimientos_promedio`, `movimiento_referencia` |
| Empleados | `empleados_listar`, `empleados_contar`, `empleados_ultimo`, `empleados_primero`, `consultar_empleado`, movimientos por empleado, asociaciones faciales existentes |
| Alertas | `alertas_listar`, `alertas_contar`, `alertas_ultimo`, `alertas_primero`, `alertas_explicar`, filtros por producto, fecha y nivel |
| Anomalías | `consultar_anomalias`, `anomalias_listar`, `anomalias_ultimo`, `anomalias_primero`, `anomalias_explicar`, `seleccionar_anomalia`, `explicar_anomalia`, `alertas_y_anomalias`, `eventos_criticos` |
| Predicción | `prediccion_agotamiento`, `riesgos_producto`, `consultar_riesgo`, reabastecimiento mediante el servicio existente |
| Conteo | `conteos_listar`, `conteos_contar`, `conteos_ultimo`, `conteos_primero`, `conteos_diferencias`, preparación confirmada de aplicación |
| Vigilancia y facial | `vigilancia_listar`, `vigilancia_ultimo`, `vigilancia_primero`, `facial_listar`, `facial_ultimo`, `facial_primero`, eventos conocidos/desconocidos guardados |
| Sistema y reportes | `estado_sistema`, `generar_reporte`, `abrir_modulo` |
| Acciones y diálogo | `led`, `led_apagar_todos`, `confirmacion_requerida`, `accion_confirmada`, `confirmacion_vencida`, `cancelar_consulta`, `reiniciar_contexto`, `aclaracion` |
| Conversación | saludo, cortesía, ayuda, agradecimiento, despedida y pregunta de nombre, sin consultas SQL |

Los identificadores compatibles emitidos por rutas anteriores se conservan.
El catálogo de herramientas y parámetros se obtiene con
`jarvis_tools.catalogo()`; su copia verificada queda en
`outputs/jarvis/catalogo_herramientas.json`. Las consultas escritas y habladas
producen el mismo resultado lógico; TTS solo adapta la presentación oral.

### Catálogo completo de herramientas

| Herramienta | Dominio | Parámetros | Confirmación |
|---|---|---|---|
| `ajustar_stock` | acciones | `datos` | Sí |
| `alertas_reconocimiento` | inventario | — | No |
| `aplicar_conteo` | acciones | `datos` | Sí |
| `atender_alerta` | acciones | `datos` | Sí |
| `consultar_agotados` | inventario | — | No |
| `consultar_alertas` | alerta | — | No |
| `consultar_alertas_filtradas` | inventario | — | No |
| `consultar_anomalias` | anomalia | — | No |
| `consultar_empleado` | empleado | `id_empleado` | No |
| `consultar_movimientos` | inventario | — | No |
| `consultar_movimientos_empleado` | movimiento | `id_empleado` | No |
| `consultar_prediccion_stock` | prediccion | — | No |
| `consultar_producto` | producto | `id_producto` | No |
| `consultar_reabastecimiento` | prediccion | — | No |
| `consultar_rostro_empleado` | rostro | `id_empleado` | No |
| `consultar_stock` | producto | `id_producto` | No |
| `consultar_stock_bajo` | inventario | — | No |
| `consultar_subject` | subject | `pregunta_o_etiqueta` | No |
| `consultar_ubicacion` | producto | `id_producto` | No |
| `contenido_ubicacion` | ubicacion | `codigo` | No |
| `detener_vigilancia` | acciones | `datos` | Sí |
| `historial_producto` | movimiento | `id_producto` | No |
| `iniciar_vigilancia` | acciones | `datos` | Sí |
| `led_apagar_todos` | leds | — | No |
| `led_producto` | leds | `id_producto`, `encendido` | No |
| `listar_productos` | inventario | — | No |
| `mas_movidos_mes` | inventario | — | No |
| `mayor_stock` | inventario | — | No |
| `movimientos_empleado` | movimiento | `id_empleado` | No |
| `movimientos_hoy` | inventario | — | No |
| `orquestador_alertas` | alertas | `filtros` | No |
| `orquestador_anomalias` | anomalias | `filtros` | No |
| `orquestador_conteos` | conteos | `filtros` | No |
| `orquestador_empleados` | empleados | `filtros` | No |
| `orquestador_facial` | facial | `filtros` | No |
| `orquestador_movimientos` | movimientos | `filtros` | No |
| `orquestador_productos` | productos | `filtros` | No |
| `orquestador_ubicaciones` | ubicaciones | `filtros` | No |
| `orquestador_vigilancia` | vigilancia | `filtros` | No |
| `prediccion_agotamiento` | inventario | — | No |
| `producto_menor_stock` | inventario | — | No |
| `productos_agotados` | inventario | — | No |
| `registrar_entrada` | acciones | `datos` | Sí |
| `registrar_salida` | acciones | `datos` | Sí |
| `registrar_transferencia` | acciones | `datos` | Sí |
| `reporte_generar` | reportes | `tipo`, `filtros`, `formato` | No |
| `resumen_inventario` | inventario | — | No |
| `sistema_estado` | sistema | — | No |
| `stock_bajo` | inventario | — | No |
| `ultimo_movimiento` | movimiento | `id_producto` | No |
| `ultimo_retiro` | movimiento | `id_producto` | No |

### Comprobaciones y límites reales

La suite `tests/probar_cerebro_central.py` cubre los enunciados solicitados,
consultas compuestas, pendientes, separación de sesiones, confirmación única,
cancelación, vencimiento, cambios de saldo, fallos y confirmaciones concurrentes.
Las escrituras se sustituyen por mocks; no se modifica el inventario real.
`outputs/jarvis/regresion_central.json` registra las pruebas ejecutadas y las
omisiones. `outputs/jarvis/verificacion_central_sql.json` conserva consultas
reales de solo lectura, incluyendo el recorrido producto → stock → movimiento →
responsable → mapa y las ubicaciones de productos agotados.

Resultado final de esta ampliación: 290 casos ejecutados, 289 correctos y uno
omitido por ausencia de FastAPI opcional. Se comprobaron 38 turnos contra SQL
Server con las escrituras bloqueadas y se generó un PDF real mediante el motor
de reportes existente, verificando su archivo y ruta. Las acciones de escritura,
cancelación y reintento se verificaron con servicios sustituidos, sin alterar
existencias. Los resultados no constituyen una comprobación de cámara,
micrófono, Arduino físico ni envío/recepción real de Telegram.

Permanecen rutas compatibles y reglas deterministas: no se garantiza comprender
cualquier formulación libre. Ollama es opcional y su disponibilidad depende del
entorno local. No se entrenó ningún modelo nuevo ni se agregaron dependencias.
La memoria conversacional es del proceso; no se conserva tras reiniciarlo.
Las acciones gráficas se aplican en escritorio: Telegram recibe texto y rutas,
no una apertura remota de widgets ni una transferencia automática de reportes.
Los eventos faciales y de vigilancia consultables son los registros guardados,
no una inspección de cámara disparada por una pregunta. Los estados sin evidencia
permanecen sin verificar. Las comprobaciones no envían mensajes reales, abren
dispositivos ni prueban Arduino físico. FastAPI continúa siendo opcional.

## Diseño del mapa del almacén

El mapa conserva las consultas existentes y la distribución física de seis
estantes, dos niveles y dos posiciones por nivel. Las tarjetas se distribuyen
en tres columnas en 1366×768, 1600×900 y 1920×1080. La composición compacta muestra
nombre en una línea con elipsis, código junto al stock y estado junto a posición
y LED. Las unidades se abrevian en las tarjetas y se conservan completas en el
detalle. El nombre completo aparece al pasar el cursor.

En la comprobación local, las tarjetas pasaron de 185 a 90 px de alto y los
estantes de 503 a 284 px. Los filtros ocupan una línea; los indicadores presentan
valor y etiqueta juntos. El panel lateral tiene unos 240 px de ancho. En la
aplicación completa a 1920×1080 se verificaron los seis estantes sin scroll
vertical y el detalle seleccionado completo. En 1366×768 se conserva scroll
vertical cuando es necesario. No se detectó desbordamiento horizontal en las
tres resoluciones. Se eliminaron filas vacías del grid que prolongaban el área
desplazable después de cambiar de una a tres columnas.

La cabecera agrupa filtros, botones separados de búsqueda y actualización,
indicadores calculados con los datos visibles y una leyenda de estados. Los
agotados conservan su posición. Para cantidades positivas, el estado de stock
utiliza la clasificación del producto global del motor existente; no se asigna
un mínimo inventado a cada posición.

Una selección individual muestra su detalle y permite abrir la ficha existente
del producto. Seleccionar el encabezado de un nivel muestra sus dos posiciones.
La búsqueda conserva sus fuentes originales: resalta coincidencias, prioriza
para la selección un nombre o código exacto y desplaza la página al estante.
Las ubicaciones abiertas desde Productos, movimientos y JARVIS utilizan los
mismos métodos públicos. Las decisiones conversacionales de JARVIS no cambian.

El botón de encendido/apagado de la posición seleccionada está en el detalle,
junto al estado y el indicador de Arduino. «Apagar todos» permanece como acción
global del mapa. El ámbar señala un LED encendido; el azul identifica la selección
y el turquesa los resultados. Los estados de stock incluyen texto, además de
fondos suaves. Los comandos se delegan al servicio LED existente, en su worker.

La comprobación `tools/verificacion_ui/verificar_mapa_diseno.py` utiliza datos SQL de
solo lectura y una instancia aislada de simulación LED. Revisa las tres
resoluciones, selección, búsqueda, acceso a ficha mediante callback y controles
de LEDs. Las capturas y el reporte quedan en `outputs/mapa_compacto/actual/`. La conexión
a un Arduino físico no se verifica en este procedimiento.

## Codificación de textos y verificación Unicode

Los textos fuente y la configuración se mantienen en UTF-8 sin BOM. El editor
declara UTF-8 en `.editorconfig` y en la configuración de VS Code. El lanzador
configura las salidas de consola en UTF-8 y arranca el intérprete del proyecto
en modo UTF-8 cuando necesita cambiar al entorno virtual.

La revisión encontró literales que ya contenían interrogaciones en lugar de
letras acentuadas. Esos caracteres estaban guardados en el archivo: cambiar
la fuente de Tkinter o volver a decodificarlos no recuperaba la información.
Se restauraron los textos identificados, sin conversiones automáticas de
respuestas, nombres del inventario ni resultados SQL. No se pudo determinar
qué herramienta produjo originalmente esa pérdida de caracteres.

También se convirtió a UTF-8 el documento de procedencia del conjunto facial,
cuyas comillas correspondían a Mac Roman, y se retiró el BOM de seis archivos
de texto. Las imágenes y los modelos permanecieron sin cambios.

La configuración JSON ya conservaba Unicode mediante lectura/escritura UTF-8
y `ensure_ascii=False`. La lectura de `.env` ahora declara su codificación
explícitamente. La normalización sin tildes de JARVIS se conserva únicamente
para comparación interna.

Verificación de fuentes, sin modificar archivos ni conectarse a servicios:

```powershell
.venv\Scripts\python.exe -X utf8 -m tools.verificar_codificacion
.venv\Scripts\python.exe -X utf8 -m unittest tests.probar_codificacion -q
```

El reporte `outputs/codificacion/fuentes.json` contiene archivos y líneas
sospechosas; omite el contenido de las líneas para proteger credenciales.
Se inspeccionan literales y comentarios Python, textos y configuración, se
validan los JSON y se distinguen consultas de URLs y parámetros SQL. Es una
verificación heurística: no puede detectar por sí sola toda falta ortográfica
ni reconstruir letras perdidas. Excluye dependencias, binarios, respaldos y
salidas generadas.

La revisión de interfaz y SQL puede repetirse con:

```powershell
.venv\Scripts\python.exe -X utf8 -m tools.verificacion_ui.verificar_unicode
```

Este procedimiento abre las pantallas, bloquea escrituras SQL antes de enviarlas
y desactiva el inicio de Telegram y el precalentamiento de voz. No abre cámaras,
no inicia vigilancia y no modifica datos. Requiere SQL Server local y una sesión
de escritorio disponible. Sus resultados y capturas quedan en
`outputs/codificacion/`. La comprobación registrada revisó 70 columnas y 2,014
valores de texto sin hallar los patrones buscados; también verificó el retorno
de un parámetro Unicode. No se modificaron tablas ni registros históricos.

## Síntesis de voz de JARVIS

La salida de voz utiliza una cola y un único trabajador. Las llamadas `hablar(texto)` deben realizarse desde un hilo de trabajo, como ya hace la interfaz. El motor local se inicializa una vez y permanece en su hilo propietario de Windows/COM. Las frases se reproducen en orden; **Detener voz** cancela la reproducción y las frases pendientes. El reconocimiento Vosk y la lógica de consultas conservan su funcionamiento.

En **Configuración > JARVIS**:

- **Síntesis de voz habilitada** permite desactivar TTS.
- **Proveedor de voz**: `auto` o `edge` intentan Edge y recurren al motor local si falla; `local` evita la conexión a Internet.
- **Voz Edge TTS** conserva `es-MX-JorgeNeural` como opción inicial.
- **Velocidad Edge** acepta porcentajes entre `-90%` y `+100%`.
- **Velocidad pyttsx3** y **Volumen** controlan la reproducción local y el volumen de salida.

El primer fallo de Edge desactiva sus intentos durante la sesión, muestra un único mensaje resumido sin URLs ni parámetros y utiliza pyttsx3 directamente en las frases siguientes. Reiniciar la aplicación permite intentar Edge de nuevo. La barra de JARVIS muestra el proveedor seleccionado; la pantalla Estado distingue si hubo una reproducción completada. Se busca una voz instalada en español por sus metadatos; si no existe, se conserva la voz predeterminada.

La verificación realizada encontró `edge-tts 7.2.8` dentro de `.venv`, coincidente con la versión publicada en PyPI. La síntesis aislada de «Hola. Soy Jarvis.» recibió HTTP 403: el servicio rechazó la solicitud; el código exacto de rechazo no identifica su causa interna. No se alteraron tokens ni endpoints. Dos frases locales se reprodujeron con **Microsoft Sabina Desktop - Spanish (Mexico)** reutilizando el motor. `requirements.txt` requiere `edge-tts>=7.2.8,<8`; no fue necesaria una actualización del paquete instalado.

Comprobaciones de TTS sin hardware:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "probar_tts.py" -q
```

Diagnóstico aislado de Edge, sin micrófono ni reproducción (requiere Internet):

```powershell
.venv\Scripts\python.exe -c "from asistente_voz import diagnosticar_edge; print(diagnosticar_edge())"
```

Edge sigue dependiendo del servicio externo. La selección local no necesita Internet, pero requiere una voz instalada de Windows y un dispositivo de salida operativo. Los fallos locales se muestran con un mensaje comprensible y no impiden usar las consultas escritas.

Validación final de esta corrección: 143 comprobaciones ejecutadas, 142 correctas y una omitida por la dependencia opcional FastAPI. Se verificó también la interrupción real de la voz local y su reproducción posterior. La base de datos y la lógica conversacional no se modificaron para esta corrección.


## Continuidad conversacional de JARVIS

`ConversationState` en `jarvis/agente_inventario.py` consolida la memoria existente. `ConversationContext` conserva compatibilidad como alias de la misma clase. No se crea un motor por pregunta. `procesar_consulta` obtiene el estado de la sesión y serializa sus turnos mediante el bloqueo existente. La interfaz entrega tanto el teclado como la transcripción de Vosk al mismo punto de entrada y a la misma sesión de escritorio.

El fallo corregido consistía en guardar el plan solo al desambiguar varios productos. Una pregunta sin producto no guardaba para qué se solicitaba el nombre; además, seleccionar un candidato podía imponer un plan anterior sobre una nueva intención.

El estado conserva producto, ubicaciones, predicción, anomalía, empleado, movimiento, tema, resultado y los últimos 20 turnos. Para consultas incompletas mantiene `plan_pendiente`, `intencion_pendiente`, `tipo_entidad_pendiente`, `entidad_pendiente`, `candidatos_ambiguos`, filtros y `pregunta_incompleta`. Los estados activos son `IDLE`, `WAITING_FOR_PRODUCT`, `WAITING_FOR_LOCATION`, `WAITING_FOR_DISAMBIGUATION` y `WAITING_FOR_CLARIFICATION`.

- «Ubicación» sin producto guarda la consulta y pide el nombre. Al recibirlo ejecuta ubicación directamente.
- Si se conoce el producto pero falta la intención, conserva su identidad y pregunta qué consultar.
- Los candidatos pueden seleccionarse por ordinal, nombre, código o una medida explícita. No se elige arbitrariamente si persisten varias coincidencias. Se conserva la lista para referencias posteriores como «el segundo».
- Una nueva intención explícita tiene prioridad sobre la pendiente. Un cambio a otro dominio utiliza sus rutas existentes. «Cancelar» descarta la consulta pendiente; reiniciar contexto limpia todo.
- Saludos completos como «Qué nota dogh» reciben una respuesta breve y no descartan la consulta pendiente. Un saludo combinado con una consulta operativa sigue la ruta de inventario.
- Las referencias consultan otra vez los servicios reales; el estado no funciona como caché de cantidades. Un error de servicio conserva la consulta incompleta para reintentar.
- «¿Y ayer?» después de movimientos conserva producto, empleado y tipo cuando corresponden; una consulta explícita global mantiene su alcance global.

`IntentRouter` y `EntityResolver`, en `jarvis/nlp_jarvis.py`, reutilizan el plan conversacional y el resolvedor NLP existentes. `jarvis/jarvis_personality.py` sigue construyendo las respuestas desde resultados verificados. Ollama, si se utiliza, recibe también estado e intención pendientes y una lista acotada de candidatos; no obtiene capacidad para ejecutar SQL libre.

Con `JARVIS_DEBUG=1`, la consola muestra estado e intención al entrar, contexto resuelto, plan, entidades, resultado y estado final. Estos detalles no se incluyen en las burbujas.

Se añadieron 15 comprobaciones de conversación. La verificación completa ejecutó 158 casos: 157 correctos y uno omitido por FastAPI opcional. Se comprobó también mediante lectura en SQL Server la secuencia ubicación, nombre, stock y duración con Tornillo 1/2: mostró sus ubicaciones y stock registrados, e indicó historial insuficiente para predecir cuando correspondía.

La memoria permanece en el proceso y se pierde al cerrar la aplicación. Una API ejecutada en otro proceso no comparte esta memoria de escritorio; las sesiones se distinguen por identificador dentro de cada proceso. El lenguaje abierto puede requerir aclaraciones y una predicción depende de historial suficiente. No se modificaron TTS, Vosk, la distribución del chat ni el esquema de SQL Server para esta corrección.


## Ampliación del cerebro conversacional y del chat

Esta etapa conserva las correcciones anteriores de `ConversationState` y la arquitectura de audio. Texto escrito y transcripción siguen entrando por `procesar_consulta` con la misma sesión de escritorio. El estado no se recrea por mensaje.

Se completaron estas capacidades:

- `SINONIMOS`, en `jarvis/nlp_jarvis.py`, concentra el vocabulario de stock, ubicación, predicción y anomalías. El router respeta las prioridades por dominio: contar movimientos no consulta stock. Las entidades se resuelven contra catálogos reales conservando códigos y medidas.
- Small talk admite también «qué haces», «perfecto», «dale», «ok», «listo» y «todo bien». No descarta productos ni consultas pendientes; los mensajes mixtos siguen consultando inventario.
- Una aclaración pregunta «¿Cuál quieres localizar?» o por stock/duración según el plan pendiente. «El de media» puede reducir candidatos con la medida real 1/2, sin crear productos.
- Si el resolvedor estricto no identifica un producto, una coincidencia moderada puede ofrecer candidatos. Nunca ejecuta su consulta automáticamente. Una sugerencia única pasa a `WAITING_FOR_CONFIRMATION`; confirmar completa la intención, rechazarla solicita otro producto y mantiene el plan. Una confianza baja no produce identificaciones.
- «El otro» conserva la intención si hay exactamente una alternativa; si hay varias, pide elegir. Las referencias no usan listas antiguas mientras se espera un producto nuevo.
- La selección visual se guarda como contexto secundario y no reemplaza un producto de conversación activo ni cancela su consulta pendiente. El texto explícito mantiene prioridad.
- «Abre el mapa» envía una acción a la interfaz existente. Localizar un producto conserva la integración con `mostrar_producto_en_mapa`. La predicción sigue usando el motor existente; no se duplicaron cálculos ni SQL.
- Si se pide explicar una anomalía sin haber elegido una, el estado `WAITING_FOR_ANOMALY_SELECTION` recuerda ese propósito. La elección por ordinal o número devuelve el motivo real registrado. «Qué pasó ahí» puede explicar la anomalía seleccionada.
- `respuesta_ubicaciones`, en `jarvis/jarvis_personality.py`, redacta filas ya consultadas: indica múltiples ubicaciones, cantidades con unidades en plural y evita prefijos repetidos. El texto y la versión hablada proceden de las mismas filas.

El chat existente de `ui/ui_theme.py` conserva JARVIS a la izquierda y usuario a la derecha, usa aproximadamente 68% como ancho máximo y 12 píxeles entre mensajes, y mantiene desplazamiento automático al final. `ui/interfaz.py` presenta Disponible, Escuchando, Procesando, Hablando y Error; al terminar la reproducción vuelve a Disponible mediante su consumidor de eventos. No se rehízo la cola, cancelación o fallback TTS.

Archivos modificados en esta ampliación: `jarvis/agente_inventario.py`, `jarvis/nlp_jarvis.py`, `jarvis/jarvis_personality.py`, `ui/ui_theme.py`, `ui/interfaz.py`, `tests/probar_contexto_jarvis.py`, `tests/probar_agente_avanzado.py` y este `README.md`. Se generó una captura de verificación en `verificacion_ui/chat_jarvis.png`. No hubo nuevas dependencias, tablas ni migraciones.

Validación final: 172 comprobaciones, 171 correctas y una omitida por FastAPI opcional. Las 57 comprobaciones de conversación pasan. Se verificaron también el ancho y separación de las burbujas en una ventana propia, con respuestas consultadas en SQL Server. Se comprobó que `jarvis/asistente_voz.py` conservó el mismo contenido durante esta etapa.

Limitaciones: las coincidencias lingüísticas son heurísticas y pueden necesitar aclaración. No hay comprensión ilimitada de combinaciones de preguntas. La memoria sigue siendo de sesión y proceso; una API en un proceso separado no comparte automáticamente la memoria de Tkinter. Las predicciones necesitan historial suficiente y el reconocimiento de voz depende de la transcripción obtenida. No se almacenó la conversación en SQL ni se agregaron cuentas de acceso.

## Corrección facial, fuente SQL y presentación numérica

Se mantuvo SQL Server / pyodbc y la conexión central `database.DATABASE = InventarioIA2`. El archivo encontrado fue `C:/Users/rpere/Downloads/BD Actualizada con 24 productos y mas movimientos.sql`, sin el sufijo `(1)` indicado en la solicitud. Se leyó como UTF-16; no se ejecutó su creación de base ni su carga de registros. Sus once tablas operativas conservan las columnas requeridas en la base conectada. La tabla de respaldo `RespaldoStockAntesReparacion`, incluida en el archivo, no está en la base activa ni es necesaria para las consultas del sistema.

La inspección encontró 24 productos, 16 empleados, 16 relaciones faciales, 253 movimientos y 30 existencias. Las consultas siguen utilizando `categorias`, `ubicaciones`, `productos`, `existencias`, `empleados`, `tipos_movimiento`, `movimientos`, `detalle_movimientos`, `tipos_alerta`, `alertas` y `rostros_empleados`, además de las extensiones funcionales existentes de lotes, conteos y anomalías. Se verificó la presencia de `vw_inventario_ubicaciones`, `vw_stock_producto`, `vw_stock_productos`, `vw_inventario`, `vw_historial_movimientos`, `vw_alertas` y `vw_rostros_empleados`. El stock permanece derivado de las existencias y servicios SQL existentes. No se repobló la base, no se eliminaron registros ni se creó otra base. No fue necesario reemplazar consultas por un esquema antiguo ni eliminar catálogos operativos escritos en Python: la verificación completa utiliza la base conectada.

### Formato visual

`core/formato_numerico.py` centraliza `format_numero`, `format_cantidad`, `format_moneda`, `format_porcentaje`, `format_score` y `format_campo`. Las cantidades se presentan con dos decimales; IDs, códigos, fechas, conteos y resoluciones conservan su representación. La tabla común aplica formato por nombre de columna. Dashboard, inventario, predicción, anomalías, mapa, reportes y respuestas de JARVIS utilizan este criterio. JARVIS puede omitir ceros finales para una respuesta más natural, manteniendo un máximo de dos decimales.

Los datos originales no se redondean antes de calcular. Por ejemplo, un valor Excel de `2.125` sigue siendo numérico y conserva esa precisión; su formato de celda es `#,##0.00`. PDF utiliza la misma presentación. No se modificaron los tipos numéricos de SQL. Las métricas almacenadas en los archivos de calibración conservan precisión completa para las decisiones; su representación en pantalla utiliza dos decimales.

### Embeddings y diagnóstico de calidad

La galería existente contiene **192 embeddings normalizados de 128 dimensiones correspondientes a 16 personas**. No había NaN ni vectores cero y las etiquetas tienen relación SQL. Sus referencias `sha256:...` son huellas de imágenes, no rutas de archivos perdidos. Se resolvieron contra el dataset existente. No se regeneró la galería porque sus vectores son compatibles y el procesamiento de embeddings no cambió.

Las causas confirmadas fueron:

- `calibracion.json` no existía, por lo que el motor impedía aceptar identidades.
- El rechazo por borrosidad ocurría antes de extraer el vector, dejando score cero y candidato vacío sin haber realizado una comparación.
- La varianza del Laplaciano se comparaba en recortes de diferentes tamaños con un único límite nativo de 45.
- El vídeo recibía múltiples líneas técnicas y el panel inferior utilizaba cuatro columnas de etiqueta/valor con espacio insuficiente.

Se conserva el flujo **YuNet → landmarks → alignCrop → SFace → vector L2 de 128D → similitud coseno → promedio de las tres mejores muestras de cada persona → evidencia temporal → relación SQL**. Registro, regeneración y reconocimiento reutilizan `MotorEmbeddings.extraer`. No se mezclan estos vectores con las salidas CNN. La alineación sigue la API documentada por [OpenCV](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html); no se copió el umbral de un benchmark externo.

`calibrar_registrados()` mide similitudes intra/inter persona excluyendo la imagen consultada y otras entradas con la misma huella. En 192 consultas, el mínimo intra fue aproximadamente 0.686 y el máximo inter aproximadamente 0.338. Su punto medio produjo un umbral de **0.5118978918** y el margen medido fue **0.2200627625**. La política se vincula a las firmas de galería, pipeline y configuración. Esta es una calibración interna, no una validación de FAR con personas desconocidas o sesiones de cámara independientes; esa limitación consta en el archivo.

`medir_nitidez` mide el Laplaciano a una escala de referencia de hasta 160 píxeles, sin ampliar rostros pequeños para inventar detalle. El percentil inferior medido de las imágenes registradas fue **100.0060125512**. Una degradación controlada de las mismas imágenes produjo el límite de rechazo **13.3090939582**. Entre ambos valores la calidad se considera aceptable y necesita seis evidencias consistentes, frente a cuatro para calidad normal. Por debajo del límite de rechazo no se confirma una identidad. Tamaño, iluminación, visibilidad y landmarks siguen siendo condiciones independientes. Los valores anteriores y nuevos no se comparan directamente: corresponden a escalas de medición distintas.

Puede generarse una comparación diagnóstica en una imagen borrosa para mostrar dónde falla el flujo, pero una calidad rechazada nunca acepta identidad. Cuando no se extrajo un vector, la interfaz presenta ausencia de score, no una similitud cero que parezca calculada. Los tamaños CERCA/MEDIA/LEJOS siguen siendo categorías de píxeles; no equivalen a metros. Una cara por debajo del mínimo operativo de 80 píxeles no se identifica.

La comprobación del pipeline completo con una imagen registrada por persona reconoció 15 de 16; la imagen restante fue rechazada por tamaño facial. Se reutilizaron muestras de la galería y se repitieron frames: esto verifica el funcionamiento, no demuestra generalización ni estabilidad en una cámara real con caras nuevas. Esas imágenes originales se conservaron.

### CNN y rendimiento

Se conserva el modelo CNN entrenado y su mapeo explícito de 16 salidas. La preparación real es **gris → 100×100 → float32 en [0,1] → canal único**, compartida por dataset e inferencia. No se cambió a RGB ni se volvió a entrenar automáticamente.

En la partición reproducible de 39 imágenes se midieron 36 clasificaciones correctas y tres incorrectas. Se obtuvo un umbral de **0.9660459161**, usando el siguiente valor representable float32 por encima del score incorrecto más alto. En esa medición cerrada conserva 30 aciertos y rechaza las tres clasificaciones incorrectas. No prueba rechazo de personas desconocidas ni sesiones nuevas. `calibracion_cnn.json` vincula el límite al hash del modelo y sus etiquetas. Sin política válida el escáner CNN informa que falta calibración antes de abrir cámara.

Los cambios de rendimiento fueron:

- El modelo permanece cargado y se recarga solo si cambian sus recursos.
- La elección entre llamada directa y `predict` usa calentamiento previo y medianas, evitando comparar una ejecución fría con otra caliente. En la medición realizada, la llamada directa tardó aproximadamente **7.84 ms** y `predict` **47.21 ms** por llamada; se selecciona la más rápida.
- Captura, inferencia y actualización Tk permanecen desacopladas, con colas de un solo frame y descarte de pendientes antiguos.
- Se eliminó la espera activa cuando no había un frame nuevo.
- Detección trabaja con un lado máximo de 640 píxeles y las coordenadas se devuelven al frame original. El preprocesamiento convierte únicamente el recorte a gris.
- La frecuencia CNN se centralizó, con tres frames como intervalo inicial; se usan la fuente y resolución configuradas.
- Se refrescan relaciones SQL durante la sesión, se descarta identidad si el resultado llega tarde y se reinicia evidencia ante un cambio importante de caja facial.
- Tras evidencia suficiente por debajo del límite, se muestra DESCONOCIDO en lugar de analizar indefinidamente. Empleados inactivos no se confirman como activos.

Una medición breve de captura entregó **1280×720 y unos 8.66 FPS**. Incluye condiciones de inicio del dispositivo. No se obtuvo una comparación fiable del escáner completo antes/después, por lo que no se afirma una mejora porcentual ni 30 FPS. El rendimiento también depende de cámara, iluminación y hardware.

### Escáner y operación

En el vídeo quedan caja, estado y, al reconocer, nombre y puntuación. Las etiquetas se ubican fuera de la caja cuando hay espacio; si no lo hay, el panel conserva la información. No se dibujan threshold, blur, candidatos o FPS sobre la cara. Similitud SFace y score CNN se rotulan por separado y no se presentan como probabilidades de certeza.

El panel usa dos columnas: Persona/Cargo/Estado/Calidad y Código/Similitud o score/Tamaño aparente/FPS y motor. Los títulos quedan encima de sus valores. `Mostrar información técnica` está desactivado por defecto y habilita un bloque externo al vídeo con etapa, blur, umbral, candidatos, margen y tiempos. Ausencias se representan mediante raya o mensajes como Motor sin calibrar. Se verificó la distribución en una ventana propia y se guardó `verificacion_ui/escaner_facial.png`, sin abrir cámara ni guardar rostros para esa captura.

Se ofrecen `embeddings`, `cnn` y `comparacion`. Comparación es un modo técnico que procesa ambas rutas secuencialmente sobre la misma captura y puede consumir más recursos. Conserva la decisión temporal SFace y muestra el score CNN por separado, sin fusionar identidades ni equiparar métricas. Para uso normal se mantiene embeddings.

En Empleados están disponibles **Diagnóstico facial**, **Calibrar motores** y **Regenerar base**. Regenerar conserva imágenes, respalda la galería y ahora puede reconstruir una base incompatible. Calibrar mide las muestras existentes; no entrena CNN. Entrenar CNN sigue siendo una operación explícita separada. Si cambian muestras o parámetros relevantes, volver a calibrar.

### Archivos y verificación

Creado: `core/formato_numerico.py`, `tests/probar_optimizacion_facial.py`, `modelos/facial_embeddings/calibracion.json`, `modelos/calibracion_cnn.json`, `evaluacion_facial/verificacion_pipeline.json` y la captura del escáner.

Modificados: `ai/facial/pipeline_facial.py`, `ai/facial/pipeline_facial_basico.py`, `ai/facial/diagnostico_facial_basico.py`, `ai/facial/reconocimiento_embeddings.py`, `ai/facial/reconocimiento_cnn.py`, `ui/ventanas_camara.py`, `core/config_manager.py`, `config_sistema.json`, `ui/interfaz.py`, `ui/dashboard.py`, `ui/inventario_ui.py`, `inventory/mapa_almacen.py`, `ui/prediccion_ui.py`, `ui/anomalias_ui.py`, `jarvis/jarvis_personality.py`, `ai/prediction/prediccion_stock.py`, `ai/anomalies/deteccion_anomalias.py`, `ai/facial/entrenar_cnn_rostros.py`, `core/estado_sistema.py`, `integrations/reporting/reportes.py`, `integrations/reporting/report_render.py`, `integrations/reporting/report_theme.py`, las comprobaciones existentes de pipeline/reportes/módulos operativos y este README. Los cambios de servicios de predicción/anomalías/entrenamiento son de presentación textual, no de cálculo o entrenamiento.

Verificación final: **178 comprobaciones ejecutadas, 177 correctas y una omitida por FastAPI opcional**. Se verificaron sintaxis, configuración, políticas vinculadas, dimensión real de SFace, formato de Excel manteniendo valores numéricos y evidencia adicional para calidad aceptable. No se modificaron TTS, Vosk, la memoria de JARVIS, tablas ni datos operativos. No hubo dependencias nuevas.

Para cargar los cambios, reiniciar la aplicación y abrir Empleados → Diagnóstico facial → Reconocer, con motor embeddings. La calibración interna ya está instalada; completar después una evaluación independiente con imágenes actuales de cámara y personas desconocidas mediante la herramienta de evaluación existente. La mejora del pipeline no corrige por sí misma imágenes antiguas pequeñas o relaciones de identidad mal registradas; esos casos requieren muestras adecuadas y revisión de los vínculos reales.
# Revisión exclusiva de CNN del 14/10/2026

La CNN permanece **sin calibración segura**. Se corrigieron la decisión, el
protocolo de datos y la captura exclusiva de CNN. No se activó un clasificador
que todavía acepta identidades incorrectas. Se comprobaron por SHA-256 **44
archivos de SFace idénticos**, incluidos código del pipeline, galerías,
calibración, modelos y configuración. No se regeneraron ni recalibraron embeddings.

## Causas comprobadas en CNN

El modelo existente recibe rostros alineados en gris de 100×100, float32 y rango
0–1, tanto al entrenar como al inferir. El mapeo explícito de 16 salidas coincide
con `modelos/etiquetas_rostros.json`: índices 0–14 → subject01–subject15 y 15 →
subject19. No se encontró un intercambio RGB/BGR ni un índice accidental como
causa actual. La arquitectura se conservó: Conv2D 16/32/64, MaxPooling, Flatten,
Dense 64, Dropout 0,3 y salida softmax de 16 clases.

Los problemas medidos fueron:

- Pocas imágenes por identidad y distribución desigual: entre 8 y 28 muestras
  utilizables, con nueve copias repetidas y dos imágenes de iluminación deficiente
  excluidas. No se borraron ni reasignaron archivos.
- Las 28 capturas de subject19 pertenecen a una sola sesión. La partición anterior
  las repartió entre entrenamiento, calibración y evaluación, contaminando la
  independencia entre conjuntos.
- El conjunto llamado calibración también había servido para validación durante
  el entrenamiento. El protocolo nuevo los separa.
- La regla anterior no utilizaba el segundo candidato ni su margen. Una salida
  softmax ganadora no es una probabilidad calibrada de identidad.
- El modelo anterior registró 100 % de accuracy en entrenamiento y validación,
  frente a 85,71 % en las 35 imágenes de evaluación. Esta brecha indica un problema
  de generalización; la contaminación impide presentar ese resultado como una
  evaluación independiente entre sesiones.

## Imágenes por etiqueta

La segunda columna cuenta archivos del dataset histórico; las capturas canónicas
de subject19 se leen de su registro original, evitando sus copias reducidas.
Solo se entrenan etiquetas vinculadas a empleados activos en SQL.

| Etiqueta | Archivos históricos | Muestras utilizables para CNN | Grupos |
|---|---:|---:|---:|
| subject01 | 11 | 11 | 11 |
| subject02 | 11 | 10 | 10 |
| subject03 | 11 | 10 | 10 |
| subject04 | 11 | 10 | 10 |
| subject05 | 11 | 11 | 11 |
| subject06 | 11 | 10 | 10 |
| subject07 | 11 | 8 | 8 |
| subject08 | 11 | 10 | 10 |
| subject09 | 11 | 10 | 10 |
| subject10 | 11 | 11 | 11 |
| subject11 | 11 | 11 | 11 |
| subject12 | 11 | 10 | 10 |
| subject13 | 11 | 11 | 11 |
| subject14 | 11 | 10 | 10 |
| subject15 | 11 | 11 | 11 |
| subject16 | 30 | Fuera de las etiquetas activas | No se utiliza |
| subject17 | 30 | Fuera de las etiquetas activas | No se utiliza |
| subject18 | 30 | Fuera de las etiquetas activas | No se utiliza |
| subject19 | 28 | 28 | 1 sesión |

Se conservaron 182 muestras utilizables de 16 etiquetas activas. Un grupo de
archivos históricos sin sesión documentada no acredita una nueva sesión. La
comprobación de contenido puede detectar conflictos entre etiquetas, pero no
certifica automáticamente la identidad humana de una fotografía.

## Decisión y calibración corregidas

La inferencia obtiene mejor clase, mejor score, segunda clase, segundo score y
margen. Cada voto debe superar **score y margen**. Se requieren cinco resultados
recientes, con al menos cuatro votos válidos para la misma identidad y acuerdo del
resultado más reciente. Un frame ambiguo, una cara distinta, una pérdida de rostro
o evidencia vencida revocan la confirmación. La relación con el empleado se resuelve
en SQL y se rechazan empleados inactivos o vínculos incompatibles.

La búsqueda de umbral y margen utiliza únicamente calibración. La evaluación no
elige ni modifica esos valores. El candidato calculado fue threshold **0,4504130**
y margen **0,1477312**, pero **no fue aprobado**. Sobre las imágenes reservadas del
modelo anterior produjo 28 aciertos aceptados, tres errores aceptados y cuatro
rechazos. Las confusiones aceptadas fueron:

| Identidad esperada | Predicción | Score | Margen |
|---|---|---:|---:|
| subject02 | subject09 | 0,60 | 0,21 |
| subject04 | subject03 | 0,54 | 0,38 |
| subject06 | subject10 | 0,76 | 0,65 |

También hubo errores de subject01 → subject03 y subject08 → subject03, rechazados
por los criterios del candidato. La matriz y los errores por clase están en
`evaluacion_facial/cnn/matriz_confusion.png` y `calibracion.json`.

Estos son diagnósticos del modelo anterior, no una evaluación independiente nueva.
La decisión vigente bloquea la CNN: cero aciertos aceptados, cero errores aceptados
y 35 rechazos en esas imágenes. La aplicación **ya bloqueaba** la identificación
CNN antes de esta revisión; no se atribuye una mejora de exactitud al bloqueo ni se
afirma haber medido el rechazo poblacional de personas desconocidas.

## Entrenamiento y captura

El entrenamiento nuevo reserva grupos completos para entrenamiento, validación,
calibración y evaluación, antes de aumentar datos. Imágenes repetidas o casi
idénticas no se reparten entre conjuntos. Se mantienen EarlyStopping con restauración
de los mejores pesos y ReduceLROnPlateau. Se prepararon pesos por clase para el
desbalance, guardado de pérdidas y respaldos de los artefactos CNN. Estos cambios
de entrenamiento todavía no produjeron un modelo nuevo: el proceso se detuvo antes
de iniciar TensorFlow al detectar que subject19 solo dispone de un grupo.

Para continuar, registrar **al menos tres sesiones nuevas y variadas de subject19**
desde el selector CNN, con el empleado ya vinculado en SQL. Las sesiones completas
se guardan en `modelos/cnn_muestras/`; las parciales se conservan para revisión y no
entran al entrenamiento. Esta captura no modifica SFace ni las relaciones SQL.
Conviene ampliar especialmente subject07 y las clases confundidas subject02,
subject04 y subject06, con sus candidatas subject09, subject03 y subject10, y revisar
de forma supervisada las etiquetas. Después, entrenar CNN y ejecutar su calibración.
Si siguen existiendo confusiones o una partición inválida, continuará bloqueada.

El botón Calibrar motores ejecuta **solo el motor seleccionado**. En CNN muestra
threshold y margin cuando son válidos; de lo contrario explica las confusiones y
los grupos insuficientes. El diagnóstico muestra cantidades y recomendaciones.

## Rendimiento y verificación de esta revisión

Se conservó la captura independiente, el worker de inferencia, la cola de un único
frame reciente, el modelo cargado una vez y el intervalo configurable de tres
frames. La cámara real entregó 1280×720 y el vídeo se renderizó a **17,30 FPS** en
una observación de diez segundos. No se detectó un rostro apto en esa observación:
se ejecutaron cero inferencias. La inferencia sobre las imágenes reales del
diagnóstico se midió aparte y figura en `evaluacion_facial/cnn/informe_final.json`;
no equivale a FPS de inferencia con cámara ni incluye detección.

Pasaron 55 comprobaciones automáticas y una comprobación en la interfaz real del
botón de calibración, los mensajes por clase y la ausencia de llamadas a calibración
SFace. Los 44 archivos protegidos permanecieron idénticos.

Archivos creados: `ai/facial/seguridad_cnn.py`, `ai/facial/cnn_dataset.py`, `ai/facial/calibracion_cnn.py`,
`tools/revisar_cnn.py`, `tests/probar_seguridad_cnn.py` y
`tools/verificacion_ui/validar_cnn_aislada.py`. Modificados: `ai/facial/reconocimiento_cnn.py`,
`ai/facial/dataset_rostros.py`, `ai/facial/entrenar_cnn_rostros.py`, `ai/facial/captura_rostros.py`, `ui/interfaz.py`,
la función CNN de `ai/facial/diagnostico_facial_basico.py` y este documento. Se actualizaron
únicamente la política y los informes CNN; el modelo y los archivos originales de
imágenes se conservaron. No se instalaron dependencias.

Desde consola: `.venv\Scripts\python.exe -X utf8 -m tools.revisar_cnn dataset`
para revisar y la misma orden con `calibrar` para medir la política sin entrenar.
La salida de calibración no aprobada termina con código 2 y explica la causa.

# Antecedente de reconocimiento facial del 13/10/2026

El motor principal continúa siendo **YuNet 2023mar + SFace 2021dec**, local y BGR.
El escáner normal siempre acumula evidencia temporal. La CNN es una alternativa;
el selector de Empleados ofrece `embeddings` y `cnn` y no ejecuta ambos a la vez.

La causa de «Sin calibrar» fue doble: la galería cambió después de calibrarse y
conservaba `subject17`, una etiqueta sin vínculo activo en SQL, mientras Roger
está vinculado a `subject19`. Estas etiquetas alcanzaban similitud 0,85 y eran
tratadas como personas diferentes. No se modificaron empleados ni relaciones SQL.
La etiqueta retirada permanece en los respaldos, fuera de la galería operativa.

También se corregió la regeneración de capturas: `registro.json` identifica las
imágenes que ya salieron de `alignCrop`; se extrae su característica directamente,
sin volver a detectar/alinear el recorte. Las nuevas capturas conservan además el
frame original. Las imágenes históricas completas pasan por detección, landmarks,
alineación y extracción. No se decide que una imagen está alineada solamente por
su tamaño. Referencia del pipeline: [OpenCV, detección y reconocimiento facial](https://docs.opencv.org/4.11.0/d0/dd4/tutorial_dnn_face.html).

## Resultado de embeddings

- Se inspeccionaron 193 archivos de las 16 identidades activas: nueve duplicados
  y dos imágenes oscuras se excluyeron; quedaron 182 muestras válidas de 128D.
- No se encontraron NaN ni vectores cero; las normas son aproximadamente 1.
- La galería operativa tiene 124 muestras. Se reservaron 21 imágenes para calcular
  la política y 37 diferentes para evaluarla. El botón Calibrar conserva estas
  particiones al repetirse; no incorpora las imágenes reservadas a la galería.
- Umbral calculado: **0,4885172844**; margen: **0,2550157309**. No son valores
  elegidos manualmente ni probabilidades de identidad.
- Calibración top-3: misma persona mínimo 0,66202 / promedio 0,82501;
  mejor persona distinta máximo 0,31501 / promedio 0,21263.
- Distribución completa de pares de las 182 muestras: 1.096 comparaciones intra,
  mínimo 0,39679 y media 0,73760; 15.375 inter, máximo 0,36783 y media 0,03367.
- Evaluación separada: **37/37 identificaciones correctas, cero incorrectas
  aceptadas**. Las imágenes de una misma sesión siguen correlacionadas: esto no
  valida el rechazo de desconocidos ni nuevas sesiones o distancias.

| Empleado | Muestras válidas disponibles | En galería | Calibración | Evaluación |
|---|---:|---:|---:|---:|
| Carlos Lopez | 11 | 8 | 1 | 2 |
| Ana Martinez | 10 | 7 | 1 | 2 |
| Luis Ramirez | 10 | 7 | 1 | 2 |
| Maria Hernandez | 10 | 7 | 1 | 2 |
| Jose Gonzalez | 11 | 8 | 1 | 2 |
| Daniela Perez | 10 | 7 | 1 | 2 |
| Miguel Torres | 8 | 5 | 1 | 2 |
| Andrea Castillo | 10 | 7 | 1 | 2 |
| Kevin Morales | 10 | 7 | 1 | 2 |
| Sofia Mendoza | 11 | 8 | 1 | 2 |
| Fernando Ruiz | 11 | 8 | 1 | 2 |
| Gabriela Sanchez | 10 | 7 | 1 | 2 |
| Alejandro Vargas | 11 | 8 | 1 | 2 |
| Valeria Rojas | 10 | 7 | 1 | 2 |
| Ricardo Navarro | 11 | 8 | 1 | 2 |
| Roger Perez | 28 | 15 | 6 | 7 |

El registro guiado solicita 15 muestras en siete etapas, descarta baja calidad y
capturas casi idénticas y conserva originales y procedencia. No requiere recapturar
todo para habilitar embeddings. Conviene ampliar las muestras de Miguel y obtener
sesiones nuevas de todos los participantes. Los controles de iluminación, pose y
tamaño siguen activos. La nitidez se mide a escala comparable; el rechazo vigente
es 13,31 y la calidad objetivo 100,01: estar por debajo del objetivo no implica
rechazo automático. En calidad aceptable se exigen más evidencias temporales.
Estas magnitudes de Laplaciano no son porcentajes universales de calidad.

## Resultado de CNN

Se corrigió la diferencia entre recortes de entrenamiento e inferencia. Ambos usan
YuNet, `alignCrop`, conversión BGR a gris, 100×100, float32 y división por 255.
La CNN existente recibe un canal; no se cambió a RGB sin reentrenamiento. El
modelo se reentrenó con 182 imágenes y 16 clases, índices explícitos y particiones
persistidas. Se conserva el modelo anterior. El contrato de preprocesamiento y
los hashes del modelo/etiquetas se validan antes de inferir.

Entrenar y calibrar son operaciones independientes. La calibración utiliza el
conjunto reservado, no el de entrenamiento; se comprueba después otro conjunto.
La CNN acertó **30/35 imágenes de evaluación (85,71%)**. El umbral candidato
0,4504131, derivado del conjunto de calibración, aceptaría tres errores en
evaluación: Ana Martinez, Maria Hernandez y Daniela Perez. Otras dos imágenes
incorrectas (Carlos Lopez y Andrea Castillo) serían rechazadas.

**La identificación CNN queda bloqueada: BASE NO CALIBRADA.** Puede abrirse su
vídeo para observar calidad y rendimiento. No se afirma que el modelo sea seguro
para reconocer personas ni se aumentó el umbral utilizando el conjunto de
evaluación. Se necesitan nuevas muestras variadas y otra evaluación independiente,
especialmente de estas cinco identidades. Una probabilidad softmax alta no prueba
que una persona desconocida pertenezca al catálogo.

Captura e inferencia tienen hilos separados. La cola conserva un único frame,
el modelo se carga una vez, la inferencia se solicita cada tres frames y no se
ejecuta si no hay un rostro apto. CNN utiliza la alineación compartida, sin ejecutar
el cálculo de embeddings durante su reconocimiento. Los errores del worker se
devuelven a la sesión para cerrar la cámara y mostrar el problema.

## Mediciones y verificación

Mediciones locales de diez segundos con ventana Tk renderizando, sin guardar
fotografías ni generar alertas:

| Motor | FPS de vídeo renderizado | Procesamientos/inferencias por segundo | Latencia CNN media |
|---|---:|---:|---:|
| Embeddings | 17,27 | 16,71 | No corresponde |
| CNN | 16,69 | 4,88 | 10,03 ms |

La cámara entregó 1280×720. En embeddings se observaron estados RECONOCIDO;
no se usó esta observación como una medición de exactitud con identidad verificada.
Las cifras dependen del hardware, iluminación, escena y cantidad de rostros aptos.
No son promesas de FPS ni de distancia. La medición CNN incluye sus rechazos de
calidad y no debe confundirse con el máximo teórico de inferencias por segundo.

Se ejecutaron 39 comprobaciones automáticas: procedencia de capturas, coherencia
del preprocesamiento, separación de imágenes, exclusión de etiquetas retiradas,
recalibración repetible, calidad, tracking y presentación.

Evidencias en `evaluacion_facial/`: `diagnostico_antes_correccion.json`,
`diagnostico_completo.json`, `distribuciones_similitud.csv`, `regeneracion_actual.json`,
`evaluacion_separada.json`, `rendimiento_embeddings_actual.json` y
`rendimiento_cnn_actual.json`. Las particiones CNN y su evaluación están en
`modelos/particiones_cnn.json` y `modelos/diagnostico_calibracion_cnn.json`.
Los respaldos de galería/calibración están en `evaluacion_facial/respaldos/` y
`modelos/facial_embeddings/galeria_respaldo_*.npz`.

Archivos de código creados: `ai/facial/base_facial.py`,
`tools/medir_motores_faciales.py`, `tests/probar_correccion_facial.py`.
Modificados: `ai/facial/pipeline_facial.py`, `ai/facial/diagnostico_facial_basico.py`,
`ai/facial/reconocimiento_embeddings.py`, `ai/facial/reconocimiento_cnn.py`, `ai/facial/dataset_rostros.py`,
`ai/facial/captura_rostros.py`, `ai/facial/entrenar_cnn_rostros.py`, `ui/interfaz.py`, `ui/ventanas_camara.py`
y este documento. Se actualizaron galería, calibración, modelo y métricas CNN.
No se modificó el esquema ni los registros de SQL, no se instalaron dependencias
y no se cambió voz, inventario, JARVIS ni predicción.

Para comprobar desde la interfaz: Empleados → embeddings → Reconocer con cámara.
Diagnóstico facial muestra las muestras y distribuciones reales. Después de una
nueva captura, regenerar/calibrar embeddings; para CNN, entrenar explícitamente y
después calibrar. Calibrar motores informa los dos resultados por separado: un
fallo de CNN no impide conservar una calibración válida de SFace.

## Telegram como servicio automático central

`integrations/telegram/telegram_service.py` concentra HTTP, política por categoría y nivel, cola,
entregas y reintentos. La configuración de esta instalación queda activada;
Inventario, Anomalías, Vigilancia, Reconocimiento facial y Sistema mantienen
sus selectores en Configuración → Telegram. La categoría Vigilancia de esa
pantalla también controla el selector de Telegram de Vigilancia, sin un segundo
interruptor independiente. Reiniciar la aplicación para cargar esta integración.
Las credenciales siguen en `.env`; no se muestran ni se escriben en los logs.

Eventos conectados:

- Nuevas alertas SQL de stock bajo y agotado, con stock total, mínimo y ubicación.
- Riesgo de agotamiento calculado por el motor de predicción existente, después
  de nuevas operaciones. Los cambios de riesgo alto/crítico tienen referencia propia.
- Nuevos movimientos: se ejecuta el detector existente y se guardan únicamente
  sus hallazgos asociados a esas operaciones, incluidos patrones de cantidad,
  horario y movimiento cuando el detector los identifica. No se les llama fraude.
  Las transferencias se analizan por anomalías y no reducen stock global para
  predicción. La alerta SQL y su hallazgo asociado no originan dos avisos iguales.
- Nuevas intrusiones YOLO: mensaje con fecha/hora, cámara, zona, nivel e identidad
  disponible; captura real y, posteriormente, clip real. Actualizar la identidad
  en la evidencia no vuelve a enviar la intrusión.
- Desconocidos confirmados por SFace: evidencia de calidad suficiente y consenso
  vigente. Se encola la fotografía y se registra la alerta desde el trabajador;
  no se informa «desconocido» por baja calidad ni por un resultado CNN. También
  se utiliza SFace para desconocidos detectados durante Vigilancia.
- Caída de SQL, detención inesperada de Vigilancia y errores importantes
  comprobados desde Estado. Se notifica una vez por caída; una recuperación
  permite notificar una caída posterior. No se notifica cada actualización de pantalla.

Hay una cola limitada a 200 eventos y un solo trabajador de Telegram. Tkinter,
la inferencia y la captura no ejecutan HTTP. `notificar_evento(...)` devuelve
PENDIENTE al encolar, no una confirmación de entrega. Las entregas reales se
consultan en Configuración → Telegram. Si se satura la cola, se conserva el
evento original y se registra el problema; no se crean hilos adicionales.

La referencia única de `notificaciones_telegram`, el bloqueo de inserción y la
toma atómica de una entrega impiden reenviar una referencia ya confirmada.
El progreso de texto, foto y vídeo se conserva en el contenido de esa misma
fila: un clip pendiente no repite una foto confirmada. Una imagen ausente
produce un mensaje de texto. JPG/JPEG/PNG se suben como archivos con `sendPhoto`;
los clips se adjuntan con `sendVideo`. El clip posterior usa otra referencia
del mismo evento y no repite el mensaje completo de la foto. Se registran los
adjuntos ausentes, rechazados o demasiado grandes; no se interrumpe Vigilancia.

Los errores transitorios confirmados admiten hasta tres intentos, con espera
entre ellos. Los errores permanentes no generan reintentos automáticos.
Una entrega cuya confirmación se perdió queda INCIERTO y exige revisar el chat:
reintentar automáticamente una petición posiblemente aceptada podría duplicarla.
El botón Reintentar errores también respeta el límite. Logs con rotación en
`outputs/telegram/servicio.log`; estado y fechas en SQL. No se registran URLs
con token ni las excepciones HTTP originales.

El corte se fija al iniciar el servicio. No se recorren pendientes de sesiones
anteriores ni se publican alertas históricas. La migración
`010_fecha_eventos_telegram.sql` añade solo una fecha nullable a
`anomalias_inventario`, con valor predeterminado para inserciones nuevas;
los hallazgos anteriores conservan NULL. Se reutilizan las tablas de la
migración 008; no se crean tablas paralelas para alertas.

Si SQL cae, los eventos que no pueden registrarse se conservan localmente en
`outputs/telegram/`. El aviso de caída de SQL puede enviarse desde ese respaldo;
al recuperar SQL durante la misma ejecución se registra su resultado sin
reenviarlo. Los respaldos de sesiones anteriores no se reproducen al reiniciar.
La cola en memoria no sustituye un registro transaccional ante un cierre forzado
o una pérdida de energía antes de que el trabajador conserve el evento.

Preparación en otra instalación, sin enviar mensajes:

```powershell
.venv\Scripts\python.exe -m tools.migrar_alertas_telegram
```

Comprobación funcional desde la aplicación:

1. Configuración → Telegram: activar las categorías y usar Comprobar conexión
   sin enviar mensaje. CONECTADO requiere una respuesta real del servicio.
2. Stock: registrar una salida válida que cambie a bajo o agotado. Actualizar
   pantallas varias veces y comprobar una sola referencia entregada.
3. Predicción: registrar una nueva operación de un producto con historial
   suficiente que cambie al riesgo alto/crítico calculado por el motor.
4. Anomalías: registrar una operación que el detector existente clasifique como
   inusual. Comprobar producto, cantidad, nivel e ID del movimiento en el aviso.
5. Vigilancia: iniciar una zona válida y generar una nueva entrada. Comprobar
   foto y clip; la identidad solo aparece cuando SFace tiene evidencia suficiente.
6. Facial: con el consentimiento correspondiente, usar SFace frente a una persona
   no incluida en la galería, con buena calidad. VERIFICANDO o un rostro borroso
   no deben publicar un aviso de desconocido. CNN no participa.
7. Sistema: utilizar una fuente de cámara no disponible o comprobar un componente
   realmente caído. Repetir la comprobación no debe multiplicar el aviso.
8. Recuperación: revisar los estados de entrega y los adjuntos. INCIERTO se
   contrasta con el chat antes de cualquier nuevo envío.

Verificaciones realizadas: 69 comprobaciones aisladas de Telegram, política,
vigilancia e identidad; 12 de alertas/predicción; 2 de entrega y progreso contra
SQL con rollback y HTTP sustituido. Se comprobó la conexión real mediante
`getChat` sin publicar mensajes. La migración se aplicó: los 12 hallazgos
existentes conservaron su fecha nueva en NULL y los observadores no encolaron
los históricos. No se publicaron fotografías ni clips durante estas verificaciones.

Fuentes de los adjuntos: [sendPhoto](https://core.telegram.org/bots/api#sendphoto)
y [sendVideo](https://core.telegram.org/bots/api#sendvideo).

### Diagnóstico del flujo de Telegram, 17/10/2026

Antes de esta corrección la tabla de entregas estaba vacía y el log no contenía
trazas. `getChat` y el botón Probar Telegram evitaban la cola; comprobarlos no
demostraba que un evento automático llegara al trabajador. Además, la API pública
de notificación dependía de que otro componente hubiera iniciado previamente
el servicio. No había trazas para determinar retrospectivamente si una detección
anterior se generó o si el trabajador estaba vivo en esa ejecución.

Ahora `notificar_evento` asegura el inicio del trabajador antes de encolar;
Probar Telegram usa esa misma API, espera el resultado y no confunde PENDIENTE
con ENVIADA. PRUEBA se clasifica como Sistema y los alias de intrusión se
clasifican como Vigilancia. Se respetan los filtros existentes. La pantalla de
Vigilancia consulta el resultado del trabajador para la referencia del evento,
en lugar de conservar únicamente el texto devuelto al encolar.

Las trazas registran recepción, referencia, categoría, severidad, filtro,
deduplicación, cola, trabajador, existencia/tamaño del archivo, método de API,
HTTP, `ok` y resultado final. Los fallos conservan descripción de Telegram o tipo
de excepción con URLs y credenciales ocultadas. ENVIADA exige HTTP 200 y `ok=true`.

Se publicaron expresamente un mensaje y una imagen PNG de diagnóstico mediante
el flujo central. `sendMessage` confirmó el mensaje 11 y `sendPhoto` el mensaje 12,
ambos con HTTP 200, `ok=true` y estado SQL ENVIADA. El trabajador estaba vivo y la
cola quedó vacía. El diagnóstico cerró su trabajador normalmente al terminar.
Evidencia: `outputs/telegram/diagnostico_entregas.json` y
`outputs/telegram/servicio.log`. No se probaron vídeos en esta comprobación.
Pasaron 75 verificaciones aisladas y 2 de integración SQL con rollback.

Reiniciar la aplicación para cargar la corrección. Para repetir explícitamente
el envío de texto y foto, desde el proyecto:

```powershell
.venv\Scripts\python.exe -m tools.diagnosticar_telegram --enviar --imagen "ruta_de_una_captura_real.jpg"
```

Sin `--enviar` solo se muestra el estado configurado. La comprobación anterior
utilizó una imagen neutral. Ahora `--imagen` es obligatorio: debe indicar una
captura real existente; el diagnóstico no genera imágenes de sustitución.

### Mensajes estructurados y evidencia de cámara

Los eventos automáticos utilizan un encabezado `[TIPO]` y campos de categoría,
subtipo, fecha, hora, módulo, nivel y descripción. Cámara y zona aparecen cuando
el evento es visual. Identidad, empleado, código, similitud SFace, track,
confianza YOLO, producto, stock, riesgo y estadísticas solo aparecen si el
evento contiene esos datos. La similitud del escáner facial no se presenta como
confianza YOLO. Promedio y desviación se reutilizan desde la referencia
histórica del detector; no se calculan valores nuevos para completar el mensaje.

`generar_snapshot_evento(frame, evento, ruta_salida)` copia el frame BGR recibido,
conserva su resolución completa y dibuja polígono, caja, tipo, fecha/hora,
cámara, zona e identidad. Guarda un JPEG mediante escritura atómica. No abre
otra cámara, no obtiene una imagen posterior y no utiliza imágenes genéricas.
El snapshot de intrusión procede del frame entregado al confirmar la entrada;
los de identidad proceden del frame al recibir el resultado confirmado de SFace.
El reconocimiento conserva su procesamiento asíncrono, su consenso y su TTL:
esto no elimina la latencia de identificación respecto de la captura.

La foto principal se adjunta con caption. Después se adjunta el recorte si
existe y, para intrusiones, el clip cuando termina de grabarse. El clip consulta
la referencia de la foto y espera si esta sigue pendiente. Nunca sustituye la
foto. Un caption extenso se acompaña de texto adicional sin perder la
descripción completa. Si falla la foto, se intenta enviar el texto; si falla
el clip, se conserva el progreso y no se repite una foto confirmada.

Vigilancia conserva YOLO/ByteTrack y la identidad existente de YuNet/SFace.
Además de INTRUSIÓN, registra DESCONOCIDO y EMPLEADO RECONOCIDO como eventos
propios con snapshot. Una identidad estable no crea un evento en cada frame:
se distingue por track, generación, estado e ID del empleado. La actualización
de identidad de una intrusión mantiene su UUID y no vuelve a enviarla.
VERIFICANDO, rostro no visible o identidad insuficiente no se transforman en
DESCONOCIDO. CNN no interviene en estos avisos.

La identidad se conserva en metadata local y en el payload SQL de la
notificación. Las intrusiones siguen enriqueciendo la alerta SQL original;
los desconocidos utilizan su alerta existente; los empleados reconocidos se
registran en las notificaciones centrales sin fabricar una alerta de intrusión.
La interfaz muestra Fecha/hora, Tipo, Categoría, Cámara, Zona, Track, Identidad,
SQL y Telegram. Al abrir el historial, recupera los estados SQL sin reenviarlos.
Muestra Foto enviada, Recorte enviado, Clip enviado, Pendiente o la causa de
error, según las confirmaciones reales del servicio.

Se mantienen stock bajo, agotado, riesgo de agotamiento, anomalías, movimientos
inusuales y fallos importantes como eventos de texto. También se informa si
SFace no puede iniciar, sin detener YOLO ni atribuir identidades. Los errores de
Telegram quedan en SQL/log para diagnóstico; un canal inaccesible no puede
confirmar su propia alerta de caída.

No se añadieron dependencias ni tablas en esta mejora. Solo se agregó el código
del producto a la consulta de anomalías. Pasaron 86 verificaciones aisladas y
3 de SQL con rollback y HTTP sustituido, incluidas preservación del frame,
orden de adjuntos, captions extensos, espera del clip y deduplicación por track.
No se enviaron imágenes genéricas ni se generaron detecciones físicas para
completar la documentación.

Textos generados desde registros existentes, sin publicarlos ni alterar SQL:
`outputs/telegram/mensajes_desde_registros.json` y
`outputs/telegram/mensajes_desde_registros.txt`. Hay una alerta de stock bajo
(Multimetro digital, 1.00 frente a mínimo 2.00) y una anomalía de Arandela M8
(salida 100.00, promedio previo 13.18, desviación 6.63). No se encontraron
eventos reales de intrusión, desconocido o empleado reconocido en las fuentes
consultadas; sus mensajes se verificaron con datos aislados, sin presentarlos
como detecciones reales.

### Notificaciones centrales en Empleados y módulos operativos

Empleados publica reconocimientos confirmados por SFace y desconocidos que
superan el consenso y la calidad existentes. Cada aviso conserva el frame
que produjo el resultado y, si existe una caja facial válida, un recorte.
Los archivos se organizan en `outputs/eventos/empleados/` y
`outputs/eventos/desconocidos/`. Un empleado reconocido se notifica una vez
por track e identidad durante la sesión de cámara. CNN no publica estos eventos.
La similitud facial se informa como valor del modelo, sin convertirla en una
probabilidad ni etiquetarla como confianza YOLO.

Configuración permite filtrar Inventario, Alertas, Anomalías, Predicción,
Vigilancia, Empleados/Facial y Sistema. Todos quedan habilitados por defecto;
se conservan las opciones guardadas anteriormente. Alertas controla los avisos
originados en ese módulo y se combina con el filtro específico de stock,
anomalías o predicción cuando corresponde. Los hallazgos asociados a una alerta
se notifican una sola vez mediante la referencia de la anomalía.

El observador consulta cada cinco segundos las nuevas operaciones. Reutiliza
los motores de anomalías y predicción, sin tratar transferencias como consumo.
Un riesgo alto o crítico nuevo tras un movimiento también se notifica cuando
todavía no había estado previo almacenado. Las alertas recreadas con el mismo
riesgo se omiten; abrir Predicción sigue sin producir avisos. Los avisos de
stock distinguen normal, bajo y agotado: una nueva alerta de stock bajo mientras
persiste el mismo estado se registra como omitida. Al observar recuperación
a normal se habilita una nueva transición. Cambios intermedios entre dos
consultas pueden no quedar reflejados como transiciones individuales.

Empleados, Alertas, Anomalías y Predicción muestran la entrega central más
reciente de sus categorías; el escáner SFace muestra además la entrega del
rostro actual. Las etiquetas consultan memoria, sin SQL ni HTTP desde Tkinter.
Se conservan los estados por adjunto, las referencias únicas en SQL, los
reintentos limitados y la confirmación exclusivamente con HTTP 200 y `ok=true`.
No se publican registros históricos al iniciar. Un fallo inesperado del
consumidor central encola un aviso y reintenta su ejecución. Si Telegram no
está disponible, la falla queda en los estados de entrega y logs; no puede
confirmarse una notificación a través de un canal inaccesible.

No se agregaron dependencias ni tablas. Se ampliaron las consultas de lectura
para incorporar código del producto y stock anterior/posterior de la ubicación
en los mensajes de anomalías. No se modificaron los cálculos del inventario,
los modelos ni sus umbrales, JARVIS, Arduino o el mapa.

Verificación: `tests.probar_telegram_modulos` cubre los nuevos enlaces de
Empleados, exclusión de CNN, frame y recorte, filtros, transiciones de stock,
riesgo repetido, recuperación del worker y estados de interfaz. Se ejecutaron
también las suites previas de Telegram, vigilancia e identidad y las de SQL
con rollback y transporte HTTP sustituido. Las columnas nuevas de consulta
se contrastaron con la base actual mediante lectura. No se realizaron nuevas
detecciones físicas ni envíos al chat durante estas verificaciones.

### Telegram como interfaz de conversación con JARVIS

El bot conserva las notificaciones automáticas y añade entrada de texto mediante
`integrations/telegram/telegram_bot_service.py`. Al abrir la aplicación se inicia un listener en un
hilo independiente; al cerrar se solicita su detención sin bloquear Tkinter.
La aplicación debe permanecer abierta y tener conexión para responder.

Se reutilizan `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` de la configuración
existente. Para recibir consultas, el chat autorizado debe estar expresado como
ID numérico, incluido el signo negativo si corresponde a un grupo. No se guardan
credenciales en el código. Configuración > Telegram permite habilitar o
deshabilitar «Conversación con JARVIS» independientemente de las notificaciones.
Las nuevas opciones se incorporan al cargar configuraciones anteriores.

Comandos disponibles:

| Comando | Comportamiento |
| --- | --- |
| `/start` | Presenta el sistema, opciones y teclado. |
| `/help` | Muestra los comandos. |
| `/jarvis` | Activa la conversación para ese chat. |
| `/salir` | Termina la conversación y limpia solo su contexto; las alertas continúan. |
| `/estado` | Consulta SQL y muestra disponibilidad del motor, cámara y vigilancia. |
| `/alertas` | Resume las alertas pendientes, sin refrescarlas ni crearlas. |

También se aceptan «Hablar con Jarvis», «Quiero hablar con Jarvis»,
«Activar Jarvis», «Salir de Jarvis» y «Dejar de hablar con Jarvis».
Tras `/jarvis`, cada mensaje pasa directamente a `procesar_consulta`, el mismo
punto de entrada de escritorio, con sesión `telegram:<chat_id>`. Se conservan
intenciones pendientes y productos de referencia mediante ConversationState,
IntentRouter y EntityResolver existentes. No se duplican consultas de productos,
predicción, ubicaciones o anomalías. La memoria de Telegram queda separada de
escritorio y de otros chats; se mantiene en memoria mientras corre el proceso.
Un reinicio requiere activar nuevamente `/jarvis`.

Telegram entrega únicamente el campo de respuesta textual: no ejecuta acciones
de navegación, abre mapas, reproduce TTS ni descarga notas de voz. Las funciones
que JARVIS ya ejecuta internamente conservan su comportamiento. Las respuestas
largas se dividen en fragmentos de hasta 4000 caracteres, sin formato Markdown
de Telegram ni truncar el contenido. Antes de enviar se ocultan credenciales,
URLs y rutas internas. Si el chat no coincide con el autorizado, solo recibe
«Chat no autorizado.»; no se crea sesión ni se consulta JARVIS o SQL.

La recepción usa `getUpdates` con long polling de 15 segundos y timeout HTTP
superior. Un bloqueo del sistema operativo por bot impide consumidores locales
simultáneos, incluso desde otra copia del proyecto. Si existe un webhook o
Telegram responde HTTP 409, se detiene únicamente el listener y se muestra el
conflicto en Configuración; las notificaciones siguen activas. No se elimina
ningún webhook automáticamente. Después de resolver un conflicto externo,
reiniciar la aplicación permite volver a iniciar el listener.

El offset se guarda de forma atómica en `outputs/telegram/bot_cursor_*.json`;
no contiene conversaciones ni credenciales. Se persiste antes de ejecutar cada
comando para evitar repetirlo tras una caída. Si el proceso cae después de
guardar el offset y antes de responder, esa respuesta puede perderse: el usuario
debe volver a enviar su consulta. Los mensajes pendientes aún no procesados
pueden recibirse al reiniciar; esto no reenvía las alertas históricas del sistema.
Un cursor dañado detiene la entrada con un estado de error, sin reiniciar su
posición silenciosamente.

Recepción y respuestas comparten el transporte y las credenciales de
`integrations/telegram/telegram_service.py`. El hilo de notificaciones conserva su cola, referencias,
evidencias y confirmaciones. Una consulta lenta de JARVIS no detiene las alertas;
`/salir` no toca su configuración ni su worker. Las respuestas conversacionales
no se convierten en alertas ni quedan sujetas a filtros de severidad.

No se comprueba la cámara abriéndola desde `/estado`: se informa el estado
observado de vigilancia o uso por reconocimiento y «SIN VERIFICAR» cuando no
hay evidencia. «JARVIS DISPONIBLE» indica que el motor puede importarse; la
disponibilidad SQL se consulta por separado. Los fallos de consulta se responden
con un mensaje general, sin enviar excepciones ni trazas al chat.

Archivos creados: `integrations/telegram/telegram_bot_service.py` y
`tests/probar_telegram_bidireccional.py`. Modificados: `integrations/telegram/telegram_service.py`,
`ui/interfaz.py`, `core/config_manager.py`, `config_sistema.json`, `ui/configuracion_ui.py`
y este documento. No se agregaron dependencias ni tablas, ni se modificaron
los motores de voz, reconocimiento, JARVIS o los cálculos del inventario.

Verificación de esta integración: 186 comprobaciones aisladas, incluidas 25
del bot bidireccional, y 15 comprobaciones de SQL con rollback y HTTP simulado.
Se comprobó una conversación con el motor real y datos aislados, la memoria
independiente, autorización, comandos, offsets, conflictos, recuperación de
cursor, transporte compartido y continuidad de las notificaciones. Se consultó
además el resumen actual de alertas en SQL sin publicar mensajes. Queda pendiente
la comprobación de extremo a extremo desde el chat real; las verificaciones no
consumieron actualizaciones reales ni enviaron respuestas a Telegram.

Referencia del protocolo: [Telegram Bot API: getUpdates](https://core.telegram.org/bots/api#getupdates).

### Orquestador central de JARVIS

La clasificación anterior mezclaba heurísticas, clasificación local y un
fallback de compatibilidad. La regla que reconocía «quién» o «empleado» se
evaluaba antes de reconocer la relación con un movimiento. Una pregunta sobre
el responsable del último movimiento podía llegar al buscador de empleados
como si la frase fuera un nombre. Se corrigió esa prioridad también en el NLP
compartido; no se añadieron personas ni respuestas precalculadas.

Ahora `procesar_consulta` sigue siendo la entrada de escritorio, voz, API y
Telegram. Dentro de ese punto, `jarvis/jarvis_router.py` interpreta un plan con dominio,
operación, filtros, entidades, límite y orden. Primero determina qué consulta
se solicita; después resuelve las menciones del catálogo y las referencias
de ConversationState. El plan se ejecuta mediante herramientas y se presenta
con la personalidad existente. Las consultas de producto, planes compuestos,
resolución aproximada y acciones LED que ya funcionaban se mantienen como
capacidades del mismo orquestador. El clasificador local y Ollama opcional
existentes no se reemplazaron ni se entrenó un modelo nuevo.

Los nuevos adaptadores están en `jarvis/jarvis_consultas.py`, integrados al registro
central de `jarvis/herramientas_jarvis.py`. Reutilizan inventario, movimientos,
predicción, mapa, alertas, anomalías, conteos, reportes, vigilancia y LEDs.
La interfaz solo procesa las acciones visuales devueltas; no ejecuta SQL.

| Dominio | Operaciones disponibles |
| --- | --- |
| Productos y empleados | Buscar, listar, contar activos, ordenar por fecha de alta, detalles de producto, precio y categoría. |
| Stock | Consulta actual y mínimo, agotados, bajo, total por unidad, comparación, agrupación por categoría o ubicación. |
| Movimientos | Recientes/primeros/últimos, autor relacionado, producto y empleado, fechas, tipos, conteo por movimiento único, sumas y promedio por movimiento. |
| Relaciones y comparaciones | Producto con mayor/menor stock, responsable/producto con más movimientos y comparación de entidades explícitas, conservando empates. |
| Alertas y anomalías | Conteo, nivel, producto/empleado cuando está relacionado, selección, recientes y explicación basada en el registro. |
| Predicción | Duración y riesgo mediante el motor existente; riesgos relevantes y mayor riesgo disponible. |
| Vigilancia y facial | Estado, intrusiones registradas, reconocimientos confirmados presentes en notificaciones SQL, acceso al reconocimiento desde escritorio. |
| Conteos | Estado, pendientes, último, diferencias, acceso al módulo y aplicación confirmada de un borrador completo. |
| Reportes | Vista previa y exportación PDF/Excel mediante el motor existente, en la carpeta configurada. |
| Sistema y Arduino | Estados observados, fallos comunicados, correspondencia LED y localización mediante el servicio existente. |
| Conversación | Saludo, cortesía, ayuda, cancelación, aclaraciones y seguimiento. |

«Último» y «primero» se resuelven por las fechas del dominio y un identificador
como desempate. Si faltan fechas no se presenta el ID como evidencia de
antigüedad. Para anomalías se conserva la fecha del movimiento utilizada por
el módulo; no se confunde con una fecha de detección no registrada. Se admiten
ventanas relativas, límites de resultados e intervalos ISO, además de «antes
de» y «después de» con límites exclusivos. Los conteos de movimientos usan
identificadores únicos para no contar los detalles como operaciones distintas.
Las cantidades de unidades distintas se muestran separadas; no se suman metros,
litros y unidades como si fueran una sola magnitud. El promedio de salidas
consultado como movimiento es por operación registrada; la predicción conserva
su propio consumo diario y no reutiliza ese promedio como si fuera diario.

ConversationState conserva el mismo lock por sesión, producto y empleado,
último movimiento, alerta/anomalía seleccionada, ubicación, resultados,
referencias y planes pendientes. Las aclaraciones usan las entidades e intención
pendientes existentes. Un resultado ambiguo presenta opciones; el siguiente
número o código completa la consulta original. Una pregunta sin dominio como
«¿Quién fue el último en ser agregado?» pide distinguir producto de empleado.
Un código inexistente no provoca que se responda con un movimiento global.
Las consultas refrescan los servicios; un error SQL no convierte el stock
memorizado en un resultado actual.

Las acciones sensibles habilitadas son una lista cerrada: ajuste de stock,
aplicación de conteo, atención de alerta e inicio/detención de vigilancia.
Antes de ejecutar, JARVIS presenta el efecto y guarda una confirmación por
sesión que vence a los 120 segundos. Solo «sí», «confirmar», «confirmo» o «hazlo»
la consumen. Cancelar, cambiar de consulta o limpiar la conversación invalida
la operación. Consumir la confirmación antes de llamar al servicio impide
ejecutarla dos veces por una repetición del mismo asentimiento.

El ajuste requiere producto, ubicación y empleado responsable explícito; si
falta alguno lo pregunta. Muestra el stock de esa ubicación, cantidad física,
diferencia y responsable. Los decimales se extraen del texto original y se
validan con el mismo validador de inventario, antes de normalizar el lenguaje.
El ajuste transaccional vuelve a comprobar el stock esperado bajo el bloqueo
existente; si cambió, no aplica la operación. Los productos con lotes requieren
el flujo de Movimientos para seleccionar el lote y no se ajustan desde este
diálogo. Los conteos conservan responsable y snapshot completo de filas,
validados por el servicio al aplicar. Vigilancia revalida estado/configuración
y el mensaje solo confirma que se solicitó iniciar/detener, no que la cámara
ya completó su arranque.

Consultar, localizar, mostrar mapa bajo petición explícita, abrir módulos,
preparar/exportar reportes y operar los LEDs existentes mantienen sus acciones
de bajo riesgo. La navegación solo se ejecuta en escritorio; Telegram recibe
el texto y nunca abre mapas o cámaras. No se habilitaron borrados arbitrarios,
cambios generales de configuración ni creación libre de entradas/salidas por
lenguaje natural. Esas operaciones siguen en sus pantallas con sus validaciones;
no se simula una confirmación para una herramienta que no está habilitada.

Escritorio y voz conservan la sesión `escritorio`; Telegram sigue utilizando
`telegram:<chat_id>`. No hay otro cerebro ni memoria exclusiva de voz. La voz
deriva de la misma respuesta textual: solo adapta marcas y separadores para
pronunciación, sin sustituir listas por un mensaje distinto. No cambiaron Vosk,
la cola de audio, Edge TTS, pyttsx3 ni cancelación. `JARVIS_DEBUG=1` habilita el
diagnóstico existente, ahora con el plan, entidades, contexto, herramienta y
banderas de aclaración/confirmación; esos datos no se muestran en el chat normal.

Archivos nuevos: `jarvis/jarvis_router.py`, `jarvis/jarvis_consultas.py`,
`tests/probar_orquestador_jarvis.py` y `tests/probar_orquestador_sql.py`.
Se modificaron agente, NLP, presentación, el adaptador de navegación de la
interfaz y las consultas de movimientos/anomalías para exponer el ID del
empleado; la lectura de empleados incorpora la fecha de creación. Alertas
admite lectura sin refrescar vencimientos para que consultar no genere alertas.
Se ajustaron las verificaciones existentes a la respuesta desconocida nueva,
mapa únicamente explícito y el mismo contenido lógico por voz.
No hubo dependencias nuevas, tablas, migraciones o cambios de modelos faciales.

Evidencias de esta entrega:

- `outputs/jarvis/resultados_orquestador.txt`: detalle de las 273 verificaciones
  aisladas, 272 aprobadas y una omitida porque la API FastAPI opcional no está
  instalada. Sin fallos ni errores.
- `outputs/jarvis/resultados_orquestador.json`: 303 turnos documentados con
  consulta, sesión, intención y respuesta, usando catálogos aislados y servicios
  sustituidos. Incluye las preguntas obligatorias, variantes, aclaraciones,
  contexto, comparación y confirmación; no son detecciones físicas.
- `outputs/jarvis/verificacion_orquestador_sql.txt`: 18 verificaciones aprobadas
  contra SQL Server con rollback exterior y Telegram sustituido.
- `outputs/jarvis/verificacion_orquestador_sql.json`: diez lecturas comprobadas
  y resultados de la verificación. La cadena real de Tornillo M8 devolvió
  ubicación E04-N01, 166 unidades y movimiento #4885 atribuido a Carlos Lopez,
  usando las fechas existentes, sin copiar los valores conceptuales del pedido.

Las pruebas SQL verificaron ajuste decimal, ausencia de escritura antes de
confirmar, rechazo de stock cambiado y aplicación de conteo mediante el motor
real. Las filas se revirtieron; no se enviaron mensajes a Telegram ni se probaron
cámara, micrófono o LEDs físicos. La API opcional y la validación de uso con
hardware/chat reales quedan pendientes. La interpretación sigue acotada a los
dominios y herramientas descritos: una frase fuera de esas capacidades pide
aclaración o informa que la operación debe hacerse desde su pantalla.

## Bus central de eventos (19 de octubre de 2026)

La aplicación de escritorio instala una única instancia local al arrancar.
No incorpora dependencias, servicios externos ni tablas nuevas. El bus integra
los hechos producidos por los servicios; conserva las reglas de stock, lotes,
predicción, detección de anomalías, YOLO, SFace y confirmaciones de JARVIS.

### 1. Archivos creados

| Archivo | Responsabilidad |
|---|---|
| `core/event_types.py` | 48 tipos, 11 categorías y cinco severidades centralizadas |
| `core/system_event.py` | Evento inmutable y copia propia de evidencia visual |
| `core/event_store.py` | Últimos 500 eventos del proceso, con filtros |
| `core/event_bus.py` | Instancia compartida, suscripciones, colas, deduplicación, transiciones y publicación después de commit |
| `core/event_logger.py` | Registro JSON por línea, rotación y ocultación de credenciales |
| `core/eventos_servicios.py` | Publicadores comunes de stock, riesgo, anomalías, vigilancia, facial y disponibilidad |
| `core/event_subscribers.py` | Consumidores de Alertas, Telegram, log y confirmación de persistencia de evidencia |
| `jarvis/tools/eventos.py` | Consultas del historial reciente de eventos |
| `tests/probar_event_bus.py` | Contratos de infraestructura |
| `tests/probar_integracion_eventos.py` | Flujos integrados aislados |
| `tools/verificar_eventos.py` | Ejecución y reporte de la regresión conjunta |

### 2. Archivos modificados

Publicadores: `inventory/movimientos.py`, `inventory/alertas.py`, `ai/anomalies/deteccion_anomalias.py`,
`ai/prediction/prediccion_stock.py`, `inventory/conteo_inventario.py`, `inventory/empleados.py`,
`ai/facial/reconocimiento_embeddings.py`, `surveillance/vigilancia_yolo.py`, `integrations/arduino/led_service.py`,
`core/estado_sistema.py` y `jarvis/jarvis.py`.

Integración y consumo: `integrations/telegram/telegram_service.py`, `jarvis/tools/__init__.py`,
`jarvis/jarvis_router.py`, `ui/dashboard.py` e `ui/interfaz.py`.
Se adaptaron las verificaciones de `tests/probar_telegram_automatico.py`,
`tests/probar_telegram_modulos.py` y `tests/probar_cerebro_central.py`
al nuevo recorrido. La documentación permanece consolidada en este README.

### 3. Arquitectura anterior

Los servicios faciales llamaban directamente a Telegram. El worker de vigilancia
registraba alertas y solicitaba notificaciones. El observador de Telegram
detectaba novedades de stock, anomalías y riesgo y decidía sus envíos.
El dashboard se refrescaba mediante sus mecanismos existentes, sin una señal
común para los cambios entre módulos.

### 4. Arquitectura nueva

```text
Servicio que ejecuta la operación
        |
        | SystemEvent; después de commit cuando corresponde
        v
Bus compartido -----------> EventStore (500)
        |                       |
        |                       +--> herramientas de JARVIS
        |
        +--> cola Alertas ------> tablas SQL existentes
        +--> cola Telegram -----> cola/transporte/evidencia existentes
        +--> cola Log ----------> logs/events.log
        +--> cola confirmación -> estado SQL de evidencia de vigilancia
        +--> buzón UI ----------> Tk.after -> refresco del dashboard
```

Para preservar la integridad actual, los movimientos siguen validando stock,
lotes y alertas SQL dentro de su transacción. Sus eventos se preparan en una
bandeja asociada al contexto de ejecución y solo se publican tras confirmar la
transacción. Un rollback descarta la bandeja y no cambia las transiciones del
bus. El consumidor de Alertas reconoce las alertas de stock ya actualizadas y
evita repetir su cálculo. Para cambios externos detectados por el observador,
sí aplica la función idempotente existente.

### 5. Tipos, categorías y severidades

El catálogo completo está en `core/event_types.py`:

| Familia | Tipos |
|---|---|
| Inventario y movimientos | `STOCK_BAJO`, `STOCK_AGOTADO`, `STOCK_NORMALIZADO`, `RIESGO_AGOTAMIENTO`, `MOVIMIENTO_REGISTRADO`, `MOVIMIENTO_INUSUAL`, `AJUSTE_INVENTARIO` |
| Alertas | `ALERTA_CREADA`, `ALERTA_ACTUALIZADA`, `ALERTA_RESUELTA`, `ALERTA_CRITICA` |
| Anomalías | `ANOMALIA_DETECTADA`, `ANOMALIA_CRITICA`, `ANOMALIA_RESUELTA` |
| Vigilancia | `INTRUSION_DETECTADA`, `PERSONA_DETECTADA`, `PERSONA_DESCONOCIDA`, `PERSONA_RECONOCIDA`, `EVIDENCIA_ACTUALIZADA` |
| Facial y empleados | `ROSTRO_RECONOCIDO`, `ROSTRO_NO_RECONOCIDO`, `FACIAL_NO_DISPONIBLE`, `EMPLEADO_ACTUALIZADO` |
| Predicción | `PREDICCION_GENERADA`, `RIESGO_MEDIO`, `RIESGO_ALTO`, `RIESGO_CRITICO` |
| Disponibilidad | `SQL_CONECTADO`, `SQL_DESCONECTADO`, `CAMARA_CONECTADA`, `CAMARA_DESCONECTADA`, `TELEGRAM_CONECTADO`, `TELEGRAM_ERROR`, `JARVIS_DISPONIBLE`, `JARVIS_ERROR`, `YOLO_DISPONIBLE`, `YOLO_ERROR`, `SFACE_DISPONIBLE`, `SFACE_ERROR`, `ARDUINO_CONECTADO`, `ARDUINO_DESCONECTADO` |
| Arduino | `LED_ACTIVADO`, `LED_DESACTIVADO` |
| Conteo | `CONTEO_INICIADO`, `CONTEO_GUARDADO`, `CONTEO_FINALIZADO`, `DIFERENCIA_CONTEO` |

Categorías: `INVENTARIO`, `MOVIMIENTOS`, `ALERTAS`, `ANOMALIAS`, `PREDICCION`,
`VIGILANCIA`, `FACIAL`, `EMPLEADOS`, `SISTEMA`, `ARDUINO`, `CONTEO`.
Severidades: `INFO`, `BAJA`, `MEDIA`, `ALTA`, `CRITICA`; se aceptan y normalizan
las variantes acentuadas y masculinas de los servicios actuales.

El catálogo no implica que todos los tipos tengan un emisor independiente.
Para una anomalía crítica se publica un solo `ANOMALIA_DETECTADA` con severidad
`CRITICA`. No se emite además `ANOMALIA_CRITICA`. Los tipos alternativos de
criticidad y `FACIAL_NO_DISPONIBLE` quedan disponibles para integraciones futuras;
la disponibilidad actual de SFace se expresa con `SFACE_DISPONIBLE/SFACE_ERROR`.

### 6. Suscriptores

Los nombres estables `log`, `alertas`, `telegram` y `evidencia-estado` impiden
registrar consumidores repetidos. El dashboard utiliza una suscripción propia
que elimina al cerrarse. Cada consumidor lento tiene una cola FIFO acotada de
256 eventos y un worker independiente. El bus también admite consumidores
síncronos para tareas breves y buzones locales.

### 7. Publicadores

| Servicio | Hechos publicados |
|---|---|
| Movimientos | Operación confirmada, ajuste y transiciones del stock total |
| Alertas | Creación o resolución de stock y atención manual |
| Anomalías | Hallazgo realmente insertado y cambio a revisada/justificada |
| Predicción | Resultado calculado, disponibilidad de datos y cambio de riesgo |
| Vigilancia | Persona detectada por track, intrusión, identidad confirmada y evidencia disponible |
| Escáner SFace | Rostro reconocido o desconocido tras sus validaciones actuales |
| Conteo | Inicio persistido, guardado, diferencias contadas y aplicación confirmada |
| Empleados | Registro, edición y desactivación confirmados |
| Arduino | LED confirmado o simulado, conexión, desconexión y fallo del comando |
| Disponibilidad/JARVIS/Telegram | Resultados observados y transiciones; sin iniciar dispositivos para inventar estados |

Las operaciones ejecutadas por JARVIS publican desde el servicio subyacente.
JARVIS no vuelve a emitir el movimiento, ajuste o encendido del LED.

### 8. Flujos migrados

La migración comprende las seis etapas solicitadas: infraestructura; movimientos,
stock, Alertas y Telegram; anomalías y predicción; vigilancia y SFace; estados y
Arduino; consultas de JARVIS y refresco del dashboard. Se mantiene el observador
SQL ya existente como puente para detectar cambios externos y ejecutar los
cálculos periódicos que ya realizaba. Ahora publica los eventos correspondientes.
No se creó otro detector de anomalías ni otro cálculo de riesgo.

### 9. Integraciones directas retiradas del recorrido normal

El escáner SFace publica eventos en lugar de solicitar envíos. El worker normal
de vigilancia publica evidencia en lugar de registrar directamente en Alertas y
Telegram. El observador de stock, anomalías y riesgo entrega al bus en lugar de
notificar por un camino paralelo. Los diagnósticos de componentes publican
transiciones. Las funciones de formato y transporte de Telegram permanecen
como adaptadores utilizados por su suscriptor.

### 10. Hilos y cierre

La publicación no hace HTTP, genera clips ni escribe archivos. La evidencia
de vigilancia conserva sus workers de disco. El bus no modifica widgets: la
suscripción del dashboard solo marca un buzón de capacidad uno; Tk lo consume
desde su temporizador y agrupa las actualizaciones con un intervalo de dos
segundos. Al cerrar, la aplicación detiene los productores y cierra las
integraciones desde un worker, sin esperar al bus dentro de Tkinter.

### 11. Aislamiento y límites de entrega

Un callback con error no impide entregar el evento a los demás ni guardarlo.
Se registra el nombre del consumidor y la clase del error, sin imprimir
excepciones que pudieran contener credenciales. Si una cola se satura, el bus
incrementa su contador de errores y registra el incidente; no bloquea al emisor.
El historial reciente conserva el evento. Este bus local no ofrece entrega
durable exactamente una vez ni recuperación de sus colas tras finalizar el
proceso. Los reintentos de red y evidencia ya aceptada por Telegram continúan
en su mecanismo existente. Un fallo del consumidor SQL queda registrado; el
bus no incorpora un nuevo sistema de reintentos SQL persistente.

### 12. Historial e inmutabilidad

`SystemEvent` es inmutable, con UUID, instante con zona horaria, tipo, categoría,
severidad, fuente, título, mensaje, referencia, datos, metadatos e imagen/video
opcionales. Los diccionarios y listas se congelan recursivamente. Los frames
se copian a bytes propios; cada consumidor que necesita una matriz recibe una
copia independiente. El EventStore conserva hasta 500 eventos sin retener esos
frames: conserva las rutas de evidencia disponibles y compacta matrices
anidadas. No sustituye el historial SQL ni carga eventos históricos al iniciar.

`logs/events.log` registra ID, instante, tipo, categoría, severidad, fuente,
referencia y mensaje. Tiene rotación a dos millones de bytes y tres respaldos.
No vuelca los payloads, imágenes o credenciales; oculta tokens, contraseñas y
direcciones que aparezcan en campos de texto. El estado sensible de `.env`
no se copia al log.

### 13. Deduplicación

El UUID identifica una emisión. `reference` identifica el incidente lógico.
El bus rechaza un UUID repetido y permite deduplicación explícita por referencia;
los publicadores de incidentes la solicitan. Para stock, riesgo y disponibilidad
se utiliza una clave de transición. El historial de IDs, referencias y estados
se limita a 4096 entradas por índice. Telegram conserva su deduplicación
persistente actual. Las recurrencias de un estado tras recuperarse tienen un
nuevo UUID y una referencia de entrega distinta; las fotos y clips mantienen
las referencias estables de su incidente y parte.

### 14. Transiciones

Stock: `NORMAL -> BAJO -> AGOTADO -> NORMAL`; el estado repetido no genera otro
aviso. Se respeta la comparación vigente `stock <= mínimo`. El riesgo utiliza
los niveles calculados por el motor actual, con estado separado para consultas
pasivas y evaluación operativa. Las consultas pasivas no envían Telegram.
SQL, cámara, Telegram, JARVIS, YOLO, SFace y Arduino también publican únicamente
cambios de disponibilidad. El baseline inicial de stock del observador no se
presenta como una operación nueva. El bus rechaza estados antiguos entregados
con demora. Un cierre solicitado de cámara o Arduino queda como evento
informativo y no genera una alerta crítica por Telegram.

### 15. Telegram

Recibe el evento original: stock bajo/agotado, anomalía, movimiento inusual,
intrusión, identidad facial, riesgo alto/crítico y fallos de servicios
compatibles. Conserva filtros por categoría y severidad, cola central, formatos,
evidencia, confirmación de entrega y reintentos existentes. Los eventos
`ALERTA_CREADA` derivados son internos y no generan un segundo envío; solo las
alertas externas sin un evento de dominio equivalente pueden notificarse por
ese tipo. Los cambios de identidad de una evidencia no reenvían la foto; el
clip es una actualización identificada por separado. Los errores del propio
Telegram se registran para JARVIS y logs, sin intentar notificarse a sí mismos.

### 16. Alertas y base de datos

El consumidor recibe stock, intrusión, rostro desconocido y anomalías. Reutiliza
las funciones y tablas existentes. La alerta de un movimiento anómalo ya
registrada dentro de su transacción no se inserta otra vez. Para un hallazgo
persistido independientemente se comprueba su relación producto/movimiento y
el catálogo antes de insertar. La intrusión mantiene su identificador SQL
idempotente. El consumidor de confirmaciones actualiza el estado de persistencia
de la evidencia. `ALERTA_CREADA/ACTUALIZADA/RESUELTA` no están suscritos al
creador de alertas: no existe un ciclo de creación recursiva.

Se utilizan `alertas`, `tipos_alerta`, `anomalias_inventario`, los catálogos y
movimientos existentes, más la persistencia actual de Telegram. No se agregaron
tablas ni migraciones y no se ejecutó una carga de registros para esta entrega.

### 17. JARVIS

El catálogo común añade cuatro herramientas: `obtener_eventos_recientes`,
`obtener_eventos_criticos`, `obtener_ultimo_evento(tipo=None)` y
`obtener_eventos_categoria`. Las consultas «¿Qué acaba de pasar?», «¿Qué pasó
recientemente?», «¿Hubo alguna intrusión?» y «¿Hay algo crítico?» consultan
eventos reales del proceso actual. La última consulta describe eventos críticos
recientes y no sustituye la consulta de alertas SQL pendientes. Sin eventos,
JARVIS lo indica explícitamente. Escritorio, texto, voz y Telegram mantienen
su entrada y memoria compartidas existentes; no se modificó Vosk ni TTS.

### 18. Verificación reproducible

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.verificar_eventos
```

El informe se guarda en `outputs/eventos/regresion.json` y la salida completa
en `outputs/eventos/ejecucion.txt`. Resultado de esta entrega: **323 pruebas
ejecutadas, 322 correctas, una omitida por FastAPI opcional ausente, sin fallos
ni errores**. La comprobación Tk pasó con Tcl/Tk accesible fuera del entorno
restringido. La compilación de los módulos modificados y la revisión UTF-8
de 262 archivos también finalizaron sin hallazgos. El conjunto reúne las pruebas nuevas, la
regresión anterior de JARVIS, voz, Telegram, vigilancia, identidad, Arduino y
codificación, más las verificaciones aisladas de predicción. Comprueba
suscripción, publicación, varios consumidores, error aislado, desuscripción,
concurrencia, historial, deduplicación, transiciones, log, eventos tras commit,
descarte tras rollback y bloqueo de estados atrasados.

Los flujos de stock, intrusión con captura y clip, rostro desconocido, fallo de
Telegram, persistencia de un hallazgo nuevo, riesgo y ACK serial usan transporte,
SQL y dispositivos sustituidos. La evidencia visual se genera con una matriz
controlada en un directorio desechable. La verificación del dashboard usa una
ventana Tk oculta para comprobar que la actualización ocurre en el hilo principal;
se omite si Tcl/Tk no está disponible en el entorno restringido. No son pruebas
con personas, cámaras, Arduino o mensajes reales. La API FastAPI opcional se
omite cuando su dependencia no está instalada.

### 19. Alcance pendiente

El catálogo CRUD de productos, unidades, categorías y ubicaciones no tiene aún
eventos propios de creación/edición. Sus consecuencias de stock siguen siendo
detectables por el observador actual. Los scripts externos y transacciones con
conexión proporcionada por el llamador deben publicar después de su commit;
no se presupone que una operación ajena a la aplicación haya sido confirmada.
El clasificador CNN conserva su recorrido anterior y no se incorporó al emisor
de identidades SFace. La inyección explícita de callbacks de vigilancia sigue
disponible por compatibilidad y verificaciones; el recorrido normal usa el bus.
Los ejecutables independientes que requieran consumidores deben llamar una vez
a `iniciar_eventos()` y cerrar con `cerrar_eventos()`.

Queda por comprobar el funcionamiento con SQL y hardware/chat reales en un
entorno operativo. El proceso actual se verificó sin modificar registros reales.
La memoria de eventos empieza de nuevo al reiniciar la aplicación; para consultas
históricas siguen utilizándose SQL, las evidencias guardadas y los logs.

## Estado central de los servicios (19 de octubre de 2026)

Esta sección actualiza la integración de disponibilidad descrita anteriormente.
Los servicios reportan observaciones a `system_state.state_manager`; las vistas
leen esa instancia compartida. El bus de eventos existente transporta sus
transiciones. No hay otra instancia de estado por pantalla ni otro bus.

### 1. Archivos creados

- `core/system_state.py`: modelo inmutable, registro, snapshots, observadores,
  transiciones, seguimiento de recursos y presentación común.
- `core/health_monitor.py`: único monitor de comprobaciones periódicas y caché de salud.
- `ui/service_state_ui.py`: buzón entre observadores y el hilo principal de Tk.
- `tests/probar_system_state.py`: comprobaciones aisladas y consistencia de vistas.

### 2. Archivos modificados

- Estado y vistas: `core/estado_sistema.py`, `ui/estado_ui.py`, `ui/interfaz.py`,
  `ui/dashboard.py`, `ui/configuracion_ui.py`, `integrations/arduino/arduino_ui.py`, `surveillance/vigilancia_ui.py`,
  `ui/tareas_ui.py`.
- Reporte desde servicios: `core/database.py`, `integrations/telegram/telegram_service.py`, `surveillance/camara_utils.py`,
  `ai/facial/reconocimiento_embeddings.py`, `surveillance/identidad_vigilancia.py`, `ai/facial/pipeline_facial.py`,
  `ai/facial/reconocimiento_cnn.py`, `integrations/arduino/led_service.py`, `jarvis/asistente_voz.py`, `jarvis/jarvis.py`,
  `ai/anomalies/deteccion_anomalias.py` y `surveillance/vigilancia_yolo.py`.
- Integración: `core/eventos_servicios.py`, `core/event_types.py`, `jarvis/jarvis_consultas.py`,
  `jarvis/jarvis_router.py`, `jarvis/tools/__init__.py`.
- Verificación: `tools/verificar_eventos.py`,
  `tests/probar_integracion_eventos.py`, `tests/probar_telegram_automatico.py`,
  `tests/probar_telegram_modulos.py`, `tests/probar_cerebro_central.py`,
  `tests/probar_dashboard.py`, `tests/probar_codificacion.py` y este README.

No se agregaron dependencias, tablas ni migraciones. Los cambios en servicios
se limitan a reportar su estado o leerlo; se conservan los algoritmos, protocolo
serial, SQL operativo, detección, reconocimiento y cola/fallback de audio.

### 3. Estados locales encontrados

`estado_sistema._pruebas` almacenaba diagnósticos separados y su consulta cargaba
recursos y ejecutaba análisis. El dashboard comprobaba SQL por su cuenta.
JARVIS reconstruía disponibilidad usando consultas SQL, bloqueos de cámara,
archivos, variables de audio y componentes del servicio Telegram.
`telegram_service._conexion_estado` y `ServicioTelegram.componentes` duplicaban
disponibilidad. `ServicioLED._estado` mantenía otra etiqueta de conexión.
La barra de JARVIS sustituía disponibilidad por mensajes de escucha o reproducción.

### 4. Estados eliminados y compatibilidad

Se retiraron esos diccionarios de disponibilidad, la variable `_estado` de
Arduino, la comprobación SQL del dashboard y la reconstrucción de estado en
JARVIS. Se retiró el `getChat` del observador de inventario y los temporizadores
que consultaban disponibilidad independiente de Arduino y Telegram en las vistas.

Se conservaron datos que cumplen otra función: handles de cámara/modelos,
bloqueos, eventos de parada, cola de voz, proveedor del intento de reproducción,
la desactivación de Edge durante la sesión, resultados individuales de entregas
Telegram, LEDs confirmados y estado operativo de una sesión de vigilancia.
Ya no se utilizan para fabricar disponibilidad en otras pantallas. Los textos
de compatibilidad de Arduino se proyectan desde el formateador central.

### 5. Servicios registrados

`SQL`, `CAMARA`, `SFACE`, `YOLO`, `TELEGRAM`, `ARDUINO`, `JARVIS`, `TTS`, `VOSK`,
`PREDICCION`, `ANOMALIAS`, `EVENT_BUS`, `MICROFONO` y `CNN`.
Pueden registrarse servicios adicionales sin crear otro administrador.

`ServiceState` contiene `service`, `status`, `available`, `activity`, `message`,
`updated_at`, `last_success`, `last_error`, `details`, `error` y `revision`.
Los datos internos se congelan; `get()` devuelve un objeto inmutable y
`snapshot()/get_all()` devuelven copias consistentes sin exponer objetos internos.
Los detalles eliminan credenciales y ocultan direcciones potencialmente sensibles.

### 6. Estados permitidos

Solo `ONLINE`, `OFFLINE`, `STARTING`, `DEGRADED`, `UNVERIFIED`, `DISABLED` y `ERROR`.
`available` distingue una función utilizable de su estado completo: Arduino en
simulación es `DEGRADED`, `available=True`, `details.mode=SIMULATION`; no implica
conexión física. SQL se considera en línea tras una consulta real satisfactoria.

SQL es el servicio crítico global. Las dependencias de inventario, facial y
vigilancia están declaradas centralmente. La caída de TTS, Telegram o Arduino
no detiene el inventario ni convierte JARVIS por texto en un servicio caído.

### 7. Actividades permitidas

`IDLE`, `INITIALIZING`, `STREAMING`, `SENDING`, `LISTENING`, `SPEAKING`,
`PROCESSING`, `SIMULATION`, `STOPPING`.
Cambiar `IDLE -> STREAMING` o `IDLE -> SPEAKING` informa a los observadores,
sin emitir otra conexión ni cambiar disponibilidad.

### 8. Comprobaciones de salud

`check_sql()` realiza `SELECT 1` mediante el conector existente. Los fallos reales
de apertura del conector también reportan SQL sin realizar consultas adicionales.
`check_telegram()` coordina la comprobación `getChat`; los envíos reales actualizan
la misma observación. Las pantallas consultan la caché y no hacen esas comprobaciones
al renderizarse. Los botones explícitos de diagnóstico mantienen la posibilidad
de comprobar o cargar un recurso solicitado por la persona.

No se abre una cámara, carga un modelo ni ejecuta predicción/anomalías para
rellenar la pantalla Estado. Predicción y anomalías reportan un cálculo ejecutado;
la falta de historial es un detalle del resultado y no significa motor caído.

### 9. Frecuencias

| Servicio | Actualización |
|---|---|
| SQL | Monitor cada 30 segundos; comprobación explícita bajo demanda |
| Telegram | Monitor cada 300 segundos y resultados de solicitudes reales; una confirmación reciente evita otro `getChat` |
| Cámara | Apertura, primer frame, error de lectura y liberación |
| SFace / YOLO / CNN | Carga real, recursos preparados, fallos y liberación de recursos observados |
| Arduino | Cambio de configuración, conexión, desconexión y confirmación/error de comandos |
| JARVIS | Núcleo/router/herramientas cargados; actividad de las consultas |
| TTS / Vosk | Carga, reproducción, fallback, cancelación y errores reales |

Los 250 ms del buzón visual solo consumen avisos en memoria: no son un health
check. Los intervalos del monitor se cuentan desde la última comprobación
completada y pueden retrasarse mientras termina otra solicitud acotada.

### 10. Observadores y ciclo de vida

`subscribe(servicio, callback)`, `subscribe_all(callback)` y `unsubscribe(token)`
permiten observar cambios. Las repeticiones sin cambios relevantes no vuelven
a notificar. Los observadores de UI solo encolan una marca; `StateBinding` consume
el snapshot desde Tk y elimina su suscripción al destruir el widget.
Los errores de un observador no rompen los demás.

Al iniciar, SQL, Telegram, JARVIS, TTS y Vosk pasan por `STARTING` cuando corresponde;
cámara y modelos diferidos permanecen sin verificar. La simulación y los servicios
deshabilitados se identifican como tales. TTS queda pendiente de verificación
hasta una reproducción real, aunque el mezclador esté preparado.

Al cerrar se activa `shutting_down`, se solicita detener el monitor y se espera
su terminación desde el worker de cierre. Las transiciones de cierre no generan
avisos falsos de caída de SQL. Los temporizadores de trabajos UI también se cancelan.

### 11. Bus de eventos

Los servicios actualizan al administrador. Solo el administrador publica la
transición usando el bus ya existente: `SQL_CONECTADO/DESCONECTADO`,
`CAMARA_CONECTADA/DESCONECTADA`, las familias de disponibilidad existentes o
`SERVICIO_ESTADO_CAMBIADO` para estados intermedios y servicios sin par específico.
Los consumidores no vuelven a traducir el evento al mismo estado.

Una simulación no publica `ARDUINO_CONECTADO`. Una degradación que sigue siendo
utilizable tampoco se anuncia como una nueva conexión. La criticidad global se
centraliza en SQL; los cierres esperados y cambios intermedios son informativos.

### 12. Barra superior

Los badges de SQL, JARVIS, cámara y el resumen general leen el snapshot central.
La disponibilidad permanece visible durante una actividad: «JARVIS: En línea ·
Hablando». El pie de la aplicación también utiliza ese estado. Los mensajes de
progreso o error de una consulta siguen visibles en el chat como resultado de
la interacción, sin sustituir la disponibilidad del núcleo.

### 13. Dashboard

Presenta SQL, cámara, Telegram, JARVIS, SFace, YOLO, Arduino, TTS y Vosk usando
el formateador y sus colores centrales. No depende de la variable de actividad
del chat ni del diagnóstico de archivos de Empleados. Los datos de inventario
continúan procediendo de sus consultas existentes; si SQL ya consta sin conexión,
el dashboard no realiza otra comprobación para confirmarlo ni inventa cifras.

### 14. Vista Estado

Es una vista detallada del snapshot: disponibilidad, actividad, mensaje y última
actualización. «Actualizar estado» vuelve a leer el snapshot. Los botones de
comprobación explícita ejecutan el diagnóstico solicitado fuera de Tk y reportan
su resultado al administrador. Cargar CNN no marca SFace como disponible.
Comprobar TTS no convierte un respaldo local degradado en voz neuronal en línea.

### 15. JARVIS

La herramienta `obtener_estado_sistema()` devuelve `state_manager.snapshot()`.
El adaptador compatible `sistema_estado` aplica el mismo formateador central.
Consultas sobre Telegram, cámara, SFace, SQL, Arduino, TTS, Vosk, YOLO o el conjunto
del sistema leen esos datos sin ejecutar comprobaciones independientes.

JARVIS se declara disponible tras cargar núcleo, router y herramientas. Un fallo
de una consulta de inventario o de voz no invalida automáticamente el núcleo.
Si Edge falla y pyttsx3 reproduce, TTS indica `DEGRADED`, proveedor `pyttsx3`,
respaldo local y disponibilidad verdadera. Si no puede reproducir, TTS queda sin
conexión, conservando independiente la disponibilidad de JARVIS por texto.

### 16. Configuración y vigilancia

Configuración muestra disponibilidad central de Telegram, Arduino, JARVIS, TTS,
Vosk y los servicios faciales. Conserva los indicadores de credenciales configuradas
sin mostrar sus valores. Guardar configuración no demuestra una conexión nueva.
Los diagnósticos se solicitan explícitamente mediante el monitor o el servicio.

Vigilancia muestra el mismo estado de cámara y YOLO junto con FPS y detalles
de la sesión. Una captura abierta queda `ONLINE/IDLE` y el primer frame confirma
`STREAMING`. Al liberar la captura se informa `OFFLINE/IDLE`; un error se conserva
como error. Una comprobación manual satisfactoria sin streaming puede dejar cámara
`ONLINE/IDLE`, referida al instante comprobado.

SFace y YOLO observan mediante referencias débiles las instancias preparadas,
sin retener modelos ni volver a cargarlos. La cámara puede estar desconectada
mientras un modelo preparado siga residente. Al liberarse la última instancia
observada se retira su disponibilidad. Si otra instancia tiene recursos válidos,
una galería incompleta no oculta esa disponibilidad.

### 17. Verificación

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.verificar_eventos
```

El informe y salida se conservan en `outputs/eventos/regresion.json` y
`outputs/eventos/ejecucion.txt`. Resultado final: **347 pruebas ejecutadas,
346 correctas, una omitida por FastAPI opcional ausente, sin fallos ni errores**.
Las dos verificaciones de Tk oculto pasaron con Tcl/Tk disponible. La compilación
de los módulos y la revisión UTF-8 de 266 archivos terminaron sin hallazgos.
Se comprueban actualización, lectura, snapshot,
inmutabilidad, estados permitidos, observadores, concurrencia, recuperación,
actividad, degradación, cierre y caché. La secuencia SQL reproduce conexión,
caída y recuperación sin eventos repetidos; la cámara cambia actividad sin
reconectarse. Las pruebas de TTS ejercitan Edge, respaldo local y fallo total
con reproducción sustituida. Una ventana Tk oculta comprueba la coincidencia
entre barra, dashboard, Estado y JARVIS.

La regresión incluye inventario agregado del dashboard, conversación, voz,
Telegram, bus, vigilancia, identidad, serial y codificación. No envía mensajes,
abre dispositivos físicos ni modifica registros reales de SQL.

### 18. Alcance y límites

La disponibilidad global de los servicios registrados está centralizada. Los
estados operativos de una sesión, los recursos físicos y los resultados de
entregas siguen perteneciendo a sus servicios: no son una segunda fuente de
disponibilidad. La pantalla Empleados conserva su diagnóstico de dataset,
calibración y modelo elegido, identificado como diagnóstico del modelo.

Los snapshots reflejan observaciones fechadas; no garantizan que un dispositivo
inactivo siga accesible indefinidamente. No se realiza vigilancia continua de
cámara ni se añade un ping periódico al Arduino. Para tipos futuros que no
admitan referencias débiles, los propietarios deberán reportar su liberación
explícitamente. La integración con hardware, red y audio reales queda pendiente
de una sesión operativa; las comprobaciones de esta entrega utilizan sustituciones.

## Refinamiento global de UX/UI — octubre de 2026

La intervención conserva la barra lateral azul marino, el encabezado oscuro y
el área de trabajo clara. No cambia esquemas SQL, registros, reglas de stock,
algoritmos de IA, conversación, transporte de Telegram ni control del hardware.

1. **Componentes compartidos.** `ui/ui_components.py` incorpora `ModuleHeader`,
   `Card`, `KpiCard`, `FilterBar`, `StatusBadge`, `ActionButton`, `EmptyState`,
   `LoadingState`, `DetailPanel`, `StandardTreeview` y `Tooltip`. Los componentes
   KPI y badge reutilizan sus constructores anteriores. `_tabla` y
   `encabezado_seccion` delegan en los componentes comunes; los callbacks de los
   módulos permanecen en sus pantallas.
2. **Estilos centrales.** `ui/ui_theme.py` reúne los roles de color solicitados,
   tipografía Segoe UI, títulos de 20 puntos, secciones de 12, KPI de 17 y
   espaciado de 4/8/12/16/24 píxeles. Las filas de las tablas tienen 30 píxeles;
   las variantes Primary, Secondary, Danger, Ghost e Icon comparten medidas.
3. **Pantallas revisadas.** Dashboard, Productos, Movimientos, Historial,
   Alertas, Empleados, Análisis IA, JARVIS, Mapa, Predicción, Conteo, Vigilancia,
   Anomalías, Reportes, Estado y Configuración comparten la base visual. Alertas,
   Anomalías y Predicción incorporan detalles laterales; Estado sustituye las
   tarjetas individuales por una tabla del estado central. Empleados separa
   Personal y Reconocimiento facial, conservando selección y herramientas.
4. **Inconsistencias corregidas.** Se redujeron KPI y márgenes excesivos, se
   unificaron encabezados, colores semánticos y tamaños de tablas, y se añadieron
   mensajes de vacío y tooltips para valores completos. Los indicadores del
   encabezado muestran BD, JARVIS y Cámara; el tooltip conserva estado y detalle.
5. **Acciones simplificadas.** Movimientos presenta un selector de tipo y una
   sola acción de registro, con tabla reciente y acceso al historial. Productos
   conserva Nuevo/Editar/Ver ubicación/Más acciones. Empleados agrupa operaciones
   secundarias; Reportes diferencia PDF como acción principal y Excel como
   secundaria. Vigilancia coloca ajustes y comprobaciones en una sección
   desplegable. Los comandos existentes se mantienen.
6. **Filtros.** Alertas añade búsqueda, tipo y nivel a la selección de pendientes.
   Predicción filtra producto y riesgo sin recalcular el motor. Anomalías permite
   filtrar estado desde sus opciones avanzadas, conservando fechas, producto,
   nivel y movimiento. Historial, Productos y Reportes conservan sus filtros.
   La búsqueda de Alertas se aplica con Intro o Actualizar.
7. **Tablas y formatos.** El componente común incluye scroll, selección,
   distribución proporcional, bandas alternas y acceso al detalle. No elimina
   columnas ocultas del registro. `core/formato_numerico.py` presenta fechas y cadenas
   ISO como DD/MM/YYYY HH:MM:SS sin microsegundos; las fechas sin hora conservan
   DD/MM/YYYY. Cantidades usan dos decimales y los contadores siguen enteros.
8. **Estados.** Los badges reutilizan una clasificación visual compartida.
   Los estados de servicios siguen procediendo de `SystemStateManager`; dibujar
   Estado no hace comprobaciones de cámara, micrófono ni red. Las comprobaciones
   explícitas del componente seleccionado permanecen disponibles.
9. **Detalle lateral.** Alertas, Anomalías, Predicción, Empleados y Estado usan
   paneles de 260 píxeles con desplazamiento independiente. El detalle completo
   puede consultarse aunque las columnas principales sean compactas. La gráfica
   de consumo se abre a petición. El Mapa conserva su detalle y geometría compacta.
10. **Composición.** Configuración agrupa General/JARVIS/Voz/Telegram/Vigilancia/
    Arduino; General reúne las opciones existentes del inventario y análisis en
    pestañas internas. Vigilancia enlaza con sus ajustes existentes. JARVIS
    conserva la conversación como contenido dominante y los controles de voz en
    una barra secundaria. Conteo conserva ubicación, captura y revisión.
11. **Resoluciones y evidencias.** `tools/verificacion_ui/revision_global.py` recorre
    las 16 pantallas y páginas internas en 1366×768, 1600×900 y 1920×1080; guarda
    90 capturas y un informe en `outputs/ux_global/revision.json`. La ejecución
    final completó 57 recorridos de filtros, selección y desplazamiento de tablas
    sin errores de interfaz. La galería está en `outputs/ux_global/index.html`;
    los panoramas `panorama_1366.png`, `panorama_1600.png` y `panorama_1920.png`
    facilitan comparar las pantallas. En 1366×768 se admite scroll vertical
    de páginas densas y detalles; en resoluciones mayores se aprovecha el ancho
    adicional. El mapa mantiene tres columnas. Los textos extensos de tabla se
    consultan mediante tooltip o detalle. Las capturas se realizan con SQL de
    solo lectura y servicios externos desactivados; los estados mostrados
    corresponden a ese entorno de revisión, no a una comprobación operativa de
    todos los servicios.
12. **Regresión y límites.** La regresión existente ejecutó 347 casos: 346
    correctos, ninguno fallido y uno omitido por FastAPI opcional ausente.
    `tests/probar_ux_global.py` añadió tres comprobaciones correctas de formato,
    columnas/selección y recarga de predicciones con filas ocultas. La compilación
    y revisión de codificación no reportaron errores. No se incorporaron
    dependencias. No se activaron audio, cámara, Arduino ni envíos de Telegram;
    su funcionamiento físico no se certifica con estas capturas. Los formularios
    de escritura conservaron sus callbacks y confirmaciones, pero no se
    ejecutaron operaciones de alta, eliminación o ajuste sobre los datos reales.

### Archivos de esta intervención

Se ampliaron `ui/ui_theme.py`, `ui/ui_components.py`, `core/formato_numerico.py`,
`ui/interfaz.py`, `ui/dashboard.py`, `ui/inventario_ui.py`, `ui/analisis_ui.py`,
`ui/anomalias_ui.py`, `ui/prediccion_ui.py`, `integrations/reporting/reportes_ui.py`, `ui/estado_ui.py`,
`ui/configuracion_ui.py`, `surveillance/vigilancia_ui.py` y `inventory/mapa_almacen.py`.
Se adaptó la comprobación visual de `tests/probar_system_state.py` al nuevo
encabezado y a la tabla Estado. Se crearon `tests/probar_ux_global.py` y
`tools/verificacion_ui/revision_global.py`. Esta documentación permanece en el README
consolidado.

Para repetir las comprobaciones desde el directorio del proyecto:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.verificar_eventos
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.probar_ux_global -v
.\.venv\Scripts\python.exe -X utf8 -m tools.verificacion_ui.revision_global
```

La última orden requiere acceso local de lectura a SQL Server y un escritorio
de al menos 1920×1080. La revisión bloquea escrituras SQL antes de enviarlas y
desactiva el arranque de audio, notificaciones y monitor de salud. No sustituye
la validación de una sesión operativa con dispositivos físicos.

## Automatización de Alertas, Anomalías y Predicción

### Disparadores encontrados y sustituidos

| Antes | Ahora |
|---|---|
| La salida evaluaba anomalías recorriendo el historial dentro de la transacción del movimiento. | Tras confirmar SQL, el consumidor del bus evalúa solamente los detalles nuevos y su contexto anterior. |
| El observador de Telegram recorría movimientos y lanzaba análisis y predicciones. | Telegram transporta notificaciones; no es el ejecutor de los motores. |
| Predicción calculaba todos los productos desde su botón y durante la construcción de la pantalla. | La pantalla lee resultados disponibles; los movimientos programan el producto afectado. |
| Consultas de JARVIS, fichas, reportes y Dashboard podían volver a calcular. | Leen predicciones persistidas o hallazgos existentes; sin resultado muestran indisponibilidad. |
| Consultar anomalías sin hallazgos podía disparar un análisis completo. | Consultar es una lectura; el análisis completo queda como acción explícita. |

1. **Disparadores anteriores.** Se revisaron `inventory/movimientos.py`,
   `integrations/telegram/telegram_service.py`, `ui/prediccion_ui.py`, `jarvis/agente_inventario.py`,
   `jarvis/herramientas_jarvis.py`, `inventory/inventario_service.py`, `integrations/reporting/reportes.py`,
   `ui/dashboard.py` y `ai/anomalies/deteccion_anomalias.py`. La tabla anterior identifica
   ejecución transaccional, observador periódico, apertura de pantalla y consultas.
2. **Nuevo disparador.** `MOVIMIENTO_REGISTRADO` se mantiene en el outbox local
   existente y se publica únicamente después de `commit`. Incluye movimiento,
   detalle, producto, código, empleado, fecha SQL, cantidad, referencia,
   ubicaciones y stock total anterior/posterior. Una transferencia mantiene el
   total; los saldos por ubicación y las validaciones siguen en el movimiento.
3. **Eventos.** Se reutilizan `STOCK_BAJO`, `STOCK_AGOTADO`,
   `STOCK_NORMALIZADO`, `ANOMALIA_DETECTADA`, `PREDICCION_GENERADA`,
   `RIESGO_ALTO`, `RIESGO_CRITICO`, `ALERTA_CREADA`, `ALERTA_ACTUALIZADA` y
   `ALERTA_RESUELTA`. Se añadieron `ANOMALIAS_ERROR` y `PREDICCION_ERROR` para
   fallos secundarios. Los eventos faciales y de intrusión conservan sus consumidores.
4. **Bus existente.** `core/automatizacion_inventario.py` usa el singleton del bus.
   Reutiliza un consumidor FIFO asíncrono del bus para movimientos y un solo
   worker de predicción. No crea otro bus ni un hilo por movimiento. El arranque
   de la aplicación inicia el servicio y el cierre de integraciones lo detiene.
5. **Stock automático.** La operación de inventario confirma los saldos en SQL;
   el consumidor evalúa el cambio de estado con el stock global confirmado. El
   consumidor de Alertas aplica las reglas existentes para crear/atender alertas.
   Esa persistencia secundaria ya no puede deshacer el movimiento confirmado.
6. **Anomalía incremental.** Se consulta el detalle nuevo y únicamente los
   movimientos anteriores del mismo producto y tipo dentro del período configurado.
   La fecha y el identificador del detalle desempatan el orden. La operación
   nueva no entra en su propio historial. Se extrajo la comparación existente a
   un helper compartido por el análisis incremental y el completo: promedio,
   desviación, razón, score, umbrales y niveles mantienen la misma matemática.
   Se preservan los tipos que el motor ya admite; un ajuste no se convierte
   artificialmente en consumo o en candidato de otro tipo.
7. **Predicción incremental.** Salidas, entradas y ajustes programan el producto
   afectado; transferencias no programan consumo global. Se conservan los motores
   y las ventanas 7/30/60/90. Cada producto se recalcula en esas cuatro ventanas,
   para que cambiar el selector de ventana sea una lectura. La coalescencia
   espera 1,5 segundos y limita a cinco segundos la espera por una secuencia
   continua. La reconciliación inicial se ejecuta en segundo plano y es
   silenciosa; después hay una revisión horaria.
8. **Transiciones.** El tracker de dominio es el que ya proporciona el bus,
   separado de `SystemStateManager`. Se compara estado anterior/nuevo por
   producto. `BAJO → BAJO` y `CRÍTICO → CRÍTICO` no vuelven a emitir su transición.
   La primera predicción de arranque establece la línea base de riesgo, sin
   transformarla en una notificación nueva. Un movimiento más antiguo que otro
   ya procesado no revierte la transición de stock del producto.
9. **Deduplicación y persistencia.** Las anomalías usan la restricción existente
   de detalle/tipo y su inserción idempotente; el evento se publica tras confirmar
   la inserción. Las alertas reutilizan sus comprobaciones de equivalencia y
   bloqueo SQL. La condición desaparecida se atiende, sin borrar el historial.
   La alerta predictiva mantiene la regla vigente de cobertura; no se añadió
   otra fórmula para decidir el riesgo.
10. **Telegram.** Solo las transiciones notificables llegan al consumidor,
    conservando categorías, nivel mínimo y deduplicación del servicio actual.
    `PREDICCION_GENERADA` es interno. `ALERTA_CREADA` derivada de un evento no
    produce un segundo envío. El puente de SQL ya no ejecuta modelos y evita
    renotificar la alerta correspondiente a un hallazgo persistido.
11. **Acciones manuales.** Anomalías conserva **Reanalizar histórico** como
    operación explícita. Predicción ofrece **Avanzado → Recalcular resultados**;
    **Actualizar vista**, filtros y selección leen el resultado existente.
    Cambiar de módulo, consultar JARVIS o abrir Reportes no lanza los motores.
12. **Pantallas cerradas.** El servicio pertenece a la aplicación, no a sus
    pestañas. Destruir una vista cancela su suscripción visual, no el worker.
    `EventBinding` utiliza un buzón y `Tk.after`; ningún callback del worker
    modifica widgets. Alertas consulta en un worker de UI y las vistas agrupan
    refrescos pendientes. Dashboard mantiene su suscripción existente y ahora
    cuenta anomalías persistidas, sin analizar el historial al refrescar.
13. **Fallo de Anomalías.** Se registra el error, se publica `ANOMALIAS_ERROR`
    y el estado técnico refleja la indisponibilidad. El movimiento y el stock
    confirmados permanecen; la predicción sigue programándose. El reanálisis
    histórico permite recuperar evaluaciones fallidas; no se marca el movimiento
    como anómalo por falta de evidencia.
14. **Fallo de Predicción.** Se publica `PREDICCION_ERROR`, se conserva el último
    resultado disponible y se programa un reintento a los 30 segundos. No se
    revierte inventario ni se detiene el consumidor de anomalías. No hay evento
    de nueva predicción antes de que su resultado haya quedado persistido.
15. **Comprobaciones.** La regresión ejecutó 362 casos: 361 correctos y uno
    omitido por FastAPI opcional ausente. Incluye doce casos de automatización:
    stock/alerta/Telegram, anomalía incremental idempotente a partir del evento,
    predicción/riesgo, transiciones repetidas, recuperación del stock, arranque
    silencioso, worker sin UI, coalescencia, transferencia, lectura sin motores,
    historial insuficiente y fallos aislados. SQL y HTTP reales están bloqueados
    en la regresión; no hubo intentos no sustituidos. El contraste adicional de
    solo lectura en SQL comparó una operación real con el análisis completo y
    comprobó las cuatro ventanas de predicción del producto 14, con resultado
    MEDIO y datos suficientes. Se abrieron las seis vistas afectadas con SQL de
    lectura y sin errores de callbacks. No se enviaron notificaciones reales.

### Almacenamiento y puesta en marcha

Se comprobó el catálogo de SQL Server: no hay una tabla de predicciones. No se
crearon tablas duplicadas ni se cambió el esquema. Alertas y anomalías siguen
persistiendo en sus tablas SQL existentes. Los últimos resultados de predicción
se guardan por producto/ventana en `outputs/predicciones/resultados.json`, mediante
archivo sincronizado y sustitución atómica, conservando fechas y decimales. Este
archivo es estado operativo calculado; no contiene cantidades o fechas inventadas.
Si no existe un resultado, la lectura devuelve explícitamente indisponibilidad.

La aplicación arranca normalmente con `main.py`; no hace falta abrir los tres
módulos para activar su procesamiento. La primera ejecución prepara los
resultados desde SQL en segundo plano. No se ejecutó el servicio contra SQL con
escrituras durante la verificación: su funcionamiento operativo comienza al abrir
normalmente la aplicación. Las pruebas usan persistencia y Telegram sustituidos.

El servicio debe permanecer ejecutándose para atender eventos. El bus continúa
siendo local y en memoria: no es una cola distribuida ni un outbox durable en SQL.
Una terminación abrupta puede requerir **Reanalizar histórico** para recuperar una
evaluación de anomalía en vuelo. La caché de predicción sí sobrevive al reinicio;
la reconciliación vuelve a calcular desde SQL sin reenviar riesgos antiguos.
Escrituras directas externas a la aplicación no generan por sí mismas
`MOVIMIENTO_REGISTRADO`; la automatización inmediata corresponde a los comandos
de movimiento existentes. La revisión horaria reconcilia stock y predicción.
El archivo de resultados está pensado para una instancia local de la aplicación.

Archivos nuevos: `core/automatizacion_inventario.py`,
`tests/probar_automatizacion.py` y `tools/verificacion_ui/validar_automatizacion.py`.
Se adaptaron los publicadores/consumidores, movimientos, alertas, motores en sus
puntos de ejecución, lectores de JARVIS/Reportes/fichas/Dashboard y las vistas
afectadas. No se añadieron dependencias, login, usuarios, roles ni auditoría.

Evidencia: `outputs/eventos/regresion.json`, `outputs/eventos/ejecucion.txt`,
`outputs/automatizacion/sql_lectura.json` y `outputs/automatizacion/ui_lectura.json`.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.verificar_eventos
.\.venv\Scripts\python.exe -X utf8 -m tools.verificacion_ui.validar_automatizacion
```

La segunda orden requiere SQL Server accesible. Bloquea escrituras antes de
enviarlas, sustituye la persistencia de hallazgos y guarda la predicción en una
carpeta aislada; no prepara datos operativos ni modifica registros del almacén.

## Trazabilidad técnica interna

Esta infraestructura observa las operaciones existentes. No tiene pantalla,
cuentas, permisos ni tablas propias. No modifica las reglas de stock, los
umbrales faciales, los modelos, la política de Telegram ni el motor de voz.

1. **Archivos creados.** `core/audit_service.py`,
   `tools/consultar_auditoria.py` y
   `tests/probar_auditoria_tecnica.py`.
2. **Archivos modificados.** `core/system_event.py`, `core/event_bus.py`,
   `core/event_logger.py`, `jarvis/jarvis.py`, `jarvis/jarvis_router.py`,
   `jarvis/herramientas_jarvis.py`, `inventory/movimientos.py`,
   `core/automatizacion_inventario.py`, `ai/anomalies/deteccion_anomalias.py`, `inventory/alertas.py`,
   `inventory/conteo_inventario.py`, `ui/inventario_ui.py`, `integrations/arduino/led_service.py`,
   `surveillance/vigilancia_yolo.py`, `core/eventos_servicios.py`, `integrations/telegram/telegram_service.py`,
   `integrations/telegram/telegram_bot_service.py`, `ui/interfaz.py`,
   `tools/verificar_eventos.py` y este README.
3. **Formato.** `logs/audit.jsonl` contiene un objeto JSON por línea,
   UTF-8 con `ensure_ascii=False`. `logs/system.log` presenta un resumen
   humano, sin el detalle DEBUG; `logs/errors.log` contiene los fallos y las
   trazas de excepciones disponibles, saneadas y limitadas. Los decimales
   se conservan como cadenas para preservar su precisión. El antiguo
   `EventLogger` solo exporta otro archivo cuando recibe una ruta explícita;
   su configuración predeterminada no duplica el registro del bus.
4. **Campos.** Cada registro contiene `timestamp`, `correlation_id`,
   `operation_id`, `parent_operation_id`, `source`, `origin`, `action`,
   `category`, `entity_type`, `entity_id`, `entity_code`, `status`, `before`,
   `after`, `data`, `duration_ms`, `error_type`, `error_message`, `thread`,
   `session_id`, `user_context` y `level`. Los datos no disponibles quedan
   en `null` o vacíos. No se inventa una identidad de acceso: `user_context`
   permanece en `null`. Niveles: DEBUG, INFO, WARNING, ERROR y CRITICAL.
   Estados: STARTED, SUCCESS, FAILED, CANCELLED, SKIPPED,
   CONFIRMATION_REQUIRED, CONFIRMED y REJECTED.
5. **Identificadores.** `AuditContext` utiliza UUID y un contexto local de
   ejecución. Una operación genera un `operation_id`; su inicio y desenlace
   conservan ese mismo ID y registran la duración. Cada paso hijo enlaza
   `parent_operation_id` y conserva `correlation_id`. Una solicitud independiente
   inicia otra correlación. `source` identifica al componente; `origin` al canal
   o modo de inicio, por ejemplo JARVIS/telegram o MOVIMIENTOS/desktop.
6. **Propagación.** JARVIS conserva el contexto en la acción pendiente y en las
   aclaraciones, y lo recupera al confirmar, cancelar o vencer. Texto y voz
   usan la misma memoria; el canal de voz se registra como `voice`.
   `SystemEvent` transporta los IDs y el bus restaura el contexto para cada
   suscriptor, incluidos los asíncronos. Los eventos de movimientos se
   observan después del commit existente, nunca como cambios confirmados si
   hubo rollback. La cola de predicción conserva contexto por producto y por
   lote retirado de la cola. Si agrupa varias operaciones, registra una
   correlación principal y enlaces desde las demás; no realiza cálculos
   repetidos para obtener una relación artificial de uno a uno.
   Telegram conserva `_audit_context` en su cola, su respaldo local y el
   contenido JSON de la tabla de notificaciones existente. Al recuperar una
   entrega, restaura ese contexto durante el transporte y la actualización
   del resultado en SQL. No necesita una migración.
7. **Módulos integrados.**

   | Componente | Información observada |
   | --- | --- |
   | JARVIS | Recepción sin texto completo, intención, confirmación, herramienta, cancelación, rechazo y resultado |
   | Movimientos | Transacción y eventos confirmados; producto, cantidad, empleado, ubicaciones y stock global anterior/posterior |
   | Conteo | Inicio, guardado, diferencias, revisión preparada, confirmación/cancelación en UI, aplicación y finalización |
   | Anomalías | Inicio, resultado normal en DEBUG, hallazgos y fallos |
   | Predicción | Solicitud, agrupación, producto, riesgo anterior/nuevo de la ventana configurada, persistencia y fallos/reintentos |
   | Alertas | Eventos existentes de creación/resolución/actualización; duplicado evitado y actualización del stock después del commit propio |
   | Telegram | Recepción, cola, deduplicación, procesamiento, entrega y sendMessage/sendPhoto/sendVideo con resultado real |
   | Vigilancia | Solicitud de inicio/parada, incidente confirmado, captura/clip generado, enriquecimiento facial y fallos |
   | SFace/YOLO | Eventos significativos existentes de reconocimiento, desconocido confirmado y disponibilidad/error del modelo |
   | Arduino | Encendido, apagado, apagado total, modo de simulación/hardware y errores de comando |
   | Estado de servicios | Transiciones significativas, estado anterior/posterior y errores; no actividad continua |
   | Bus | Publicación en DEBUG, referencia, consumidores coincidentes, errores de consumidor y saturación |

8. **Exclusiones por frecuencia.** No se generan registros de auditoría por
   frame, token de voz, ciclo de Tkinter, lectura de cámara o cada health check
   exitoso. No se registran las imágenes, audio, embeddings, landmarks ni
   vectores; solo referencias necesarias a evidencias ya generadas. El
   registro normal no incluye el mensaje completo ni los parámetros completos
   de las herramientas de JARVIS.
9. **Saneamiento.** `sanitize_sensitive_data` procesa recursivamente los datos
   antes de encolarlos. Oculta claves sensibles y secretos conocidos del
   entorno/configuración, patrones de credenciales, URLs completas y cadenas
   de conexión. Reduce rutas del proyecto y oculta el nombre personal de
   rutas de Windows externas. Limita profundidad, colecciones y longitud;
   los tipos no previstos no se convierten indiscriminadamente a texto.
   Si se cambian credenciales durante una sesión, reiniciar la aplicación
   actualiza la lista de valores conocidos. Las reglas por nombre de clave
   siguen aplicándose sin reinicio. Los archivos de log deben mantenerse en
   una carpeta local con acceso limitado y no publicarse sin revisión.
10. **Rotación y fallos.** Un único worker escribe los tres archivos mediante
    `RotatingFileHandler`: 10 MiB por archivo y cinco respaldos numerados.
    La cola admite 4096 entradas sin esperar por espacio. Ante saturación o
    fallo de disco, conserva hasta 100 registros saneados en memoria y cuenta
    los no escritos mediante `audit.diagnostics()`. Reintenta abrir archivos
    al recibir registros posteriores, con una pausa mínima de cinco segundos.
    Esa reserva no es persistente ni se reproduce automáticamente: un cierre
    inesperado o un disco inaccesible puede dejar una traza parcial. El error
    del log no impide ejecutar la operación del inventario. La garantía de
    concurrencia corresponde a los hilos de una instancia de la aplicación;
    no se implementó escritura compartida entre procesos independientes.
11. **Consulta.** La herramienta es de solo lectura. Incluye respaldos rotados,
    ordena por fecha/hora y permite combinar filtros exactos. Los límites de
    fecha se proporcionan con fecha y hora en formato ISO y el mismo huso
    horario de los registros. `--json`
    conserva el formato estructurado. Para seguir una predicción agrupada,
    consultar también el ID indicado en `executing_correlation_id`.

    ```powershell
    .\.venv\Scripts\python.exe -X utf8 -m tools.consultar_auditoria --source JARVIS
    .\.venv\Scripts\python.exe -X utf8 -m tools.consultar_auditoria --correlation UUID
    .\.venv\Scripts\python.exe -X utf8 -m tools.consultar_auditoria --status FAILED
    .\.venv\Scripts\python.exe -X utf8 -m tools.consultar_auditoria --entity-code TOR-001 --json
    .\.venv\Scripts\python.exe -X utf8 -m tools.consultar_auditoria --category MOVIMIENTOS --desde 2026-10-19T00:00:00-06:00
    ```

12. **Validación y alcance.** Las pruebas dedicadas cubren JSON/UTF-8, campos,
    duración, padres, stock anterior/posterior, rollback, concurrencia,
    rotación, apertura/escritura fallida, saneamiento, consulta, consumidor
    fallido, predicción fallida, coalescencia, confirmación real de JARVIS,
    continuidad texto/voz, contexto durable de Telegram y fallo de commit
    posterior al transporte. Un flujo integrado verifica la misma correlación
    desde la confirmación por Telegram hasta movimiento, stock, anomalía,
    predicción y envío, con persistencia y transporte sustituidos.
    La regresión completa se ejecuta con SQL y HTTP reales bloqueados; sus
    registros técnicos se separan en `outputs/eventos/auditoria_regresion`.
    No constituye una validación con cámara, Arduino físico ni Telegram real.
    Las notificaciones o evidencias anteriores a esta integración no contienen
    un contexto histórico recuperable: cuando no existe, se inicia uno nuevo.
    No se agregaron dependencias ni cambios de esquema. Resultados reproducibles
    en `outputs/eventos/regresion.json` y `outputs/eventos/ejecucion.txt`.
    Resultado de esta integración: **382 ejecutadas, 381 correctas, cero
    fallos/errores y una omitida** porque FastAPI opcional no está instalado.
    Incluye **20 pruebas dedicadas de trazabilidad**. La revisión de
    codificación examinó 274 archivos sin hallazgos.

    ```powershell
    .\.venv\Scripts\python.exe -X utf8 -m tools.verificar_eventos
    .\.venv\Scripts\python.exe -X utf8 -m unittest tests.probar_auditoria_tecnica
    ```

## Organización del código por dominio

El punto de entrada continúa siendo `python main.py`. El código Python se
organiza por responsabilidad; las funciones, modelos y reglas de negocio se
mantienen. Los recursos conservan su ubicación física y se resuelven desde
`core.paths.PROJECT_ROOT` cuando el módulo antes se encontraba en la raíz.

```text
main.py
core/                      Base de datos, configuración, eventos, estado y trazabilidad
inventory/                 Productos, empleados, movimientos, alertas, conteo y mapa
jarvis/                    Conversación, NLP, voz y API opcional
  tools/                   Adaptadores de herramientas de JARVIS
ai/
  prediction/              Predicción de stock
  anomalies/               Detección de anomalías
  facial/                  CNN, SFace, dataset, captura y calibración
surveillance/              Cámaras, seguimiento e intrusión
integrations/
  telegram/                Bot y servicio de notificaciones
  arduino/                 LEDs y configuración del dispositivo
  reporting/               Reportes y exportación
ui/                        Interfaz y componentes visuales
tools/                     Comandos de mantenimiento y diagnóstico
  verificacion_ui/         Verificadores de interfaz
tests/                     Pruebas automatizadas
```

Los archivos `config_sistema.json`, `intenciones_jarvis.json` y
`reconocimiento_facial_config.json` permanecen en la raíz. También se conservan
los modelos, datasets, SQL, migraciones, caché de voz, registros, respaldos y
salidas anteriores. Las carpetas `herramientas/`, `pruebas/` y
`verificacion_ui/` pueden seguir conteniendo recursos no Python, requisitos o
evidencias históricas; sus scripts se encuentran ahora en `tools/` y `tests/`.

Para ejecutar módulos de forma explícita desde la raíz:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 main.py
.\.venv\Scripts\python.exe -B -X utf8 -m tools.verificar_eventos
.\.venv\Scripts\python.exe -B -X utf8 -m tools.verificar_codificacion
.\.venv\Scripts\python.exe -B -X utf8 -m unittest tests.probar_auditoria_tecnica
.\.venv\Scripts\python.exe -B -X utf8 -m tools.consultar_auditoria --source JARVIS
```

Los imports usan las rutas de dominio, por ejemplo `core.database`,
`inventory.movimientos` y `jarvis.jarvis`. No se dejaron copias de compatibilidad
en la raíz ni se añadió un cargador global de módulos. Los scripts que ya tenían
un arranque directo mantienen su ajuste local de ruta; los comandos nuevos se
documentan con `python -m paquete.modulo`.

La reorganización movió 169 archivos Python en ocho fases. La suite principal
mantuvo 381 casos correctos y uno omitido por FastAPI opcional; otros 73 casos
faciales pasaron. Se comprobó el arranque desde `main.py` y la apertura de las
16 pantallas con SQL de solo lectura y efectos externos desactivados.
El inventario de movimientos, respaldos, correcciones de referencias y resultados
se encuentra en `outputs/reorganizacion_dominios/20261020/`. Esta validación no
equivale a operar cámaras, Arduino físico, audio o Telegram reales.

## Vigilancia con dos cámaras

Dentro de Vigilancia hay dos pestañas: **Intrusión** y **Presencia de empleados**.
La primera conserva las zonas, YOLOv8, ByteTrack, SFace, snapshots, clips y sus
consumidores SQL/Telegram. La segunda observa presencia y no crea intrusiones.
Ambas se inician y detienen por separado. No se activan al abrir el programa.

En Configuración → Vigilancia se definen fuente y nombre de cada cámara,
habitación, intervalo facial, tiempo para declarar una salida y notificaciones.
La fuente anterior de intrusión se conserva; presencia utiliza por defecto USB 1.
Seleccione dispositivos distintos. También se aceptan URLs HTTP/RTSP sin
credenciales. Para fuentes privadas utilice `VIGILANCIA_VIDEO_SOURCE` y
`VIGILANCIA_EMPLOYEES_VIDEO_SOURCE` en el entorno o `.env`.
Los cambios se aplican en la siguiente sesión de la cámara. Cambiar la fuente
de intrusión borra el polígono para que se configure sobre la nueva imagen.

`camera_source_intrusion` es el alias explícito de la fuente anterior
`camera_source`; `camera_source_employees` define la segunda fuente. Las opciones
nuevas se incorporan al cargar configuración sin sobrescribir el archivo hasta
que se pulse Guardar. Se rechaza abrir la misma fuente en ambos servicios.

Cada cámara tiene captura, worker YOLO, tracker ByteTrack, FPS y reconexión propios.
Se usan dos instancias YOLO: compartir el predictor actual mezclaría el estado
persistente del tracker entre streams. Presencia limita por defecto su análisis a
8 FPS y tamaño YOLO 480; intrusión mantiene su configuración. No se han medido
los FPS reales de dos cámaras físicas funcionando simultáneamente.

Presencia cuenta tracks confirmados, con tres observaciones de detección y una
tolerancia de tres segundos antes de declarar la salida. Un empleado puede
identificarse después de la entrada inicial de una persona; el historial distingue
ambos eventos. Una caída de vídeo invalida el conteo actual y no inventa salidas.
Cuando no hay vídeo disponible, JARVIS informa que no puede confirmar la ocupación,
en lugar de responder cero personas.

La identidad utiliza exclusivamente el adaptador SFace existente y sus controles
de calidad, calibración y consenso. No usa CNN. Se conserva por track y se revalida
al reaparecer o por intervalo. No se cuenta repetidamente una respuesta facial
copiada entre frames como si fueran nuevas evaluaciones. El estado DESCONOCIDO
requiere tres evaluaciones faciales válidas sin coincidencia; rostro no visible,
calidad insuficiente o motor sin calibración no son identidades desconocidas.
Las similitudes SFace son puntuaciones del modelo, no probabilidades de identidad.

El historial local está en `outputs/presencia/historial.jsonl`, con rotación de
2 MB y tres archivos anteriores. Los snapshots reales de desconocidos se guardan
en esa misma carpeta. La trazabilidad técnica reutiliza Audit Service. No hay
tablas SQL ni migraciones nuevas. El historial no equivale a una marcación de
asistencia: solo refleja apariciones y pérdidas dentro del campo de visión.

Los eventos de presencia pasan por el bus central y su único consumidor Telegram.
Desconocidos y errores se notifican por defecto, sujetos a los filtros globales.
Entradas y salidas de empleados están desactivadas por defecto; el conteo nunca
envía un mensaje por frame. La foto de desconocido corresponde al frame completo.
Los estados independientes son `CAMARA_1` y `CAMARA_2`; la cámara del escáner
facial mantiene su estado histórico `CAMARA` para compatibilidad.

JARVIS acepta consultas sobre ocupación, empleados presentes, desconocidos,
estado de Cámara 2 y últimas entradas/salidas. Sus herramientas consultan el
servicio de presencia; no abren cámaras ni calculan identidades nuevas.
Telegram agrega `/presentes`, botones y mensajes de bienvenida/conversación
redactados con la personalidad compartida de JARVIS. Se mantiene el control de
chat autorizado, la cola de notificaciones y las confirmaciones existentes.

Validación: 404 casos ejecutados, 403 correctos y uno omitido por FastAPI opcional
no instalado; incluyen 22 casos de presencia y una simulación completa con dos
empleados identificados, una persona desconocida, snapshot, bus, Telegram
sustituido y consulta JARVIS. Se comprobó el arranque con las 16 pantallas y las
dos pestañas de Vigilancia, SQL de solo lectura y efectos externos desactivados.
No hubo envíos Telegram reales ni capturas físicas. Evidencias e informe:
`outputs/vigilancia_dos_camaras/`. Sin dependencias nuevas.
