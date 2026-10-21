# Auditoría técnica de la fase 3.6: Implementación de CRISP-DM

**Proyecto:** Sistema inteligente de inventario para un taller mecánico.  
**Finalidad:** demostración académica.  
**Contenido:** las 50 preguntas completas y sus respuestas, organizadas en los once entregables solicitados.

## Alcance y criterios de evidencia

Este documento reúne la inspección técnica realizada en esta conversación y las aclaraciones del desarrollador. No representa una certificación de despliegue en producción. Las cantidades y versiones corresponden a la revisión anterior; no se realizó una nueva carga de registros para elaborar este archivo.

El desarrollador confirmó que todos los registros de inventario fueron preparados para el desarrollo y la demostración, que las imágenes corresponden a las personas vinculadas y que los integrantes del equipo autorizaron el registro de sus rostros. También confirmó que no se utilizan cuentas, roles ni login en la aplicación, que las condiciones de cámara, iluminación y distancia siguen en evaluación y que los resultados de la CNN son aceptables para la etapa académica actual.

Las respuestas distinguen tres fuentes: **código existente**, **ejecución previamente comprobada** y **confirmación del desarrollador**. Las propuestas de mantenimiento, recuperación y protección se identifican como recomendaciones, no como procedimientos ya ejecutados. No se incluyen secretos ni se modificaron funciones o datos para elaborar este documento.

## 1. Plan de implementación

**Estado actual:** parcial; ejecución local disponible, despliegue operativo pendiente.  
**Evidencia:** `README.md`, `main.py`, `requirements.txt`, `core/database.py`, `core/config_manager.py` y `migrations/`.  
**Implementado:** punto de entrada, entorno Python, conexión central a SQL Server y configuración de recursos.  
**Información faltante:** hardware mínimo medido, instalador reproducible del esquema completo y validación en otro equipo.  
**Próximas acciones:** documentar el equipo utilizado y comprobar una instalación limpia con los recursos necesarios.

### 1. ¿Qué requisitos de hardware y software necesita el sistema?

Necesita un equipo capaz de ejecutar Python, la interfaz de escritorio y los modelos locales; una cámara para reconocimiento facial y un micrófono y salida de audio para JARVIS por voz. La ejecución revisada utiliza Windows, Python 3.9.13, SQL Server 2022 y ODBC Driver 17. No se han establecido mediante mediciones requisitos mínimos de RAM, CPU, GPU o resolución de cámara. Internet puede ser necesario para Edge TTS; el reconocimiento Vosk y la síntesis local permiten trabajar sin ese servicio.

### 2. ¿Qué pasos se requieren para instalar, configurar y ejecutar el proyecto?

El README indica crear el entorno virtual, activarlo, instalar `requirements.txt` y ejecutar `python main.py`. Antes del inicio deben estar disponibles SQL Server, la base `InventarioIA2`, el controlador ODBC y los permisos de Windows correspondientes. También deben colocarse los modelos faciales y de voz en las rutas configuradas. Para una instalación nueva falta verificar un script completo del esquema actual; las migraciones complementarias no sustituyen ese esquema base.

### 3. ¿Qué dependencias y configuraciones son obligatorias?

La operación de escritorio requiere Tkinter/ttkbootstrap, pyodbc y las bibliotecas utilizadas por sus módulos. Reconocimiento facial necesita OpenCV y los archivos YuNet/SFace; la CNN necesita TensorFlow y sus etiquetas. Predicción y análisis utilizan NumPy, pandas, scikit-learn y Matplotlib según la función. Voz necesita Vosk y su modelo español, sounddevice y un motor de síntesis disponible. Deben revisarse `core/database.py`, `config_sistema.json` y las rutas de modelos.

### 4. ¿Qué pasos de integración están completados y cuáles siguen pendientes?

Están conectados inventario, movimientos, mapa, empleados, análisis, reportes y JARVIS con la interfaz y los servicios de SQL. Texto y voz utilizan la misma entrada conversacional en la sesión de escritorio. Siguen pendientes la validación integral en un segundo equipo, la evaluación facial independiente, la validación predictiva con períodos no usados para construir la estimación y una recuperación comprobada de la base.

### 5. ¿Existen instrucciones de despliegue o solamente de ejecución local?

Existen instrucciones de instalación y ejecución local en `README.md`. No se verificó un despliegue productivo con instalador, servicio administrado, monitoreo continuo o procedimiento de recuperación aprobado. La finalidad confirmada es una demostración académica.

## 2. Modelo implementado

**Estado actual:** parcial; componentes integrados, validación operativa limitada.  
**Evidencia:** `ai/facial/pipeline_facial.py`, `ai/facial/reconocimiento_embeddings.py`, `ai/facial/reconocimiento_cnn.py`, `ai/prediction/prediccion_stock.py`, `ai/anomalies/deteccion_anomalias.py`, `jarvis/agente_inventario.py`, `jarvis/nlp_jarvis.py` y `jarvis/asistente_voz.py`.  
**Implementado:** reconocimiento mediante embeddings y CNN, estimaciones de consumo, detección de movimientos inusuales y conversación por texto y voz.  
**Información faltante:** evaluación independiente y criterios de aceptación medidos para cada componente.  
**Próximas acciones:** separar las pruebas de integración de la evaluación de calidad de los modelos.

### 6. ¿Cómo se ejecuta cada componente de inteligencia artificial?

- **Reconocimiento facial:** captura vídeo, detecta rostros, evalúa calidad, obtiene embeddings y compara con la galería registrada. La decisión incorpora evidencia de varios frames. El motor principal revisado utiliza YuNet y SFace; existe además una CNN propia y un modo de comparación técnica.
- **Predicción del inventario:** consulta salidas históricas y stock total, incluye días sin consumo y calcula promedio diario, cobertura, tendencia y riesgo. Rechaza o limita la interpretación cuando faltan datos.
- **Detección de anomalías:** analiza cantidades y características de movimientos mediante reglas estadísticas y funciones con Isolation Forest. La interpretación depende de la ruta de análisis utilizada; un hallazgo no demuestra por sí mismo una irregularidad real.
- **JARVIS y NLP:** interpreta la intención, resuelve entidades, conserva contexto y consulta servicios del inventario. Vosk convierte voz en texto y la respuesta se presenta en el chat y se reproduce con el motor TTS configurado.

### 7. ¿Qué archivos, bibliotecas, parámetros y datos utiliza cada componente?

Facial utiliza `ai/facial/pipeline_facial.py`, `ai/facial/reconocimiento_embeddings.py`, OpenCV, modelos ONNX, `modelos/facial_embeddings/galeria.npz` y calibración asociada. La galería revisada contiene 192 embeddings de dimensión 128 para 16 identidades; los umbrales revisados son aproximadamente 0.5119 de similitud y 0.2201 de margen entre candidatos. La CNN usa `ai/facial/reconocimiento_cnn.py`, TensorFlow, modelo Keras, etiquetas y preprocesamiento de escala de grises 100 × 100.

Predicción utiliza `ai/prediction/prediccion_stock.py`, movimientos de tipo Salida y stock consultado en SQL. Anomalías utiliza `ai/anomalies/deteccion_anomalias.py`, NumPy, pandas y scikit-learn. JARVIS usa `jarvis/agente_inventario.py`, `jarvis/nlp_jarvis.py`, `intenciones_jarvis.json` y servicios compartidos. Voz utiliza `jarvis/asistente_voz.py`, Vosk español y Edge TTS o pyttsx3. Estos parámetros y cantidades son los observados en la revisión previa, no garantías de rendimiento.

### 8. ¿Cómo se comunican los modelos con la aplicación y con la base de datos?

La interfaz invoca funciones de los módulos y servicios; estos consultan SQL Server mediante la conexión central de `core/database.py`. El reconocimiento facial relaciona una identidad registrada con un empleado, sin convertirlo en cuenta de acceso. JARVIS utiliza los mismos servicios de consulta, mapa y predicción. Las tareas de cámara y audio emplean procesamiento fuera del hilo principal y mecanismos de actualización de la interfaz.

### 9. ¿Qué modelos están integrados en el flujo principal y cuáles se ejecutan de forma independiente?

Reconocimiento facial, predicción, anomalías y JARVIS están accesibles desde la aplicación. Entrenamiento de CNN, diagnóstico, evaluación y algunas tareas de mantenimiento también tienen scripts específicos. La API de JARVIS es una alternativa independiente y no comparte automáticamente la memoria del proceso de escritorio. Ollama es una integración opcional cuya disponibilidad real no se confirmó.

### 10. ¿Qué limitaciones técnicas impiden considerar algún modelo listo para su uso operativo?

La calibración facial con imágenes registradas no sustituye una evaluación con desconocidos, nuevas sesiones y distintas condiciones. La precisión de CNN disponible corresponde a una partición de clases conocidas, no al rendimiento del motor SFace ni a cualquier cámara. Los históricos preparados permiten demostrar predicción y anomalías, pero no validar su eficacia en operaciones reales. No se han confirmado distancias en metros, rendimiento sostenido ni aceptación operativa independiente.

## 3. Sistema o producto final

**Estado actual:** realizado para integración académica; parcial para operación real.  
**Evidencia:** `ui/interfaz.py`, `inventory/inventario_service.py`, `inventory/mapa_almacen.py`, `integrations/reporting/reportes_ui.py`, `core/database.py` y revisión SQL anterior.  
**Implementado:** aplicación de escritorio con módulos conectados y persistencia SQL.  
**Información faltante:** verificación completa de todas las pantallas en una instalación nueva.  
**Próximas acciones:** ejecutar y documentar un recorrido funcional de demostración.

### 11. ¿Qué módulos y funcionalidades contiene actualmente el sistema?

Contiene dashboard, productos e inventario, movimientos, historial, alertas, empleados, mapa del almacén, reconocimiento facial, análisis y predicción de stock, anomalías, JARVIS, reportes y configuración/estado del sistema. Existen servicios de lotes y conteos vinculados al inventario. No utiliza login, administración de usuarios, roles ni auditoría de acceso como parte del flujo actual.

### 12. ¿Qué funcionalidades pueden utilizarse desde una interfaz y cuáles requieren ejecutar scripts?

Las consultas y operaciones cotidianas, mapa, reconocimiento, JARVIS, análisis y reportes se presentan mediante la interfaz. La instalación de ampliaciones SQL, la inspección del esquema y algunas evaluaciones o tareas de entrenamiento se realizan mediante scripts. La API requiere ejecución independiente y dependencias adicionales. La disponibilidad de un botón no demuestra que todos sus casos hayan sido comprobados manualmente.

### 13. ¿Qué componentes están integrados y cuáles están incompletos?

La integración de los módulos principales está implementada. Permanecen incompletos como proceso de puesta en operación: distribución reproducible del esquema, evaluación independiente de modelos, monitoreo persistente, recuperación ensayada y documentación de aceptación. La API opcional no estaba ejecutable en el entorno revisado por ausencia de FastAPI/Uvicorn.

### 14. ¿Cómo se conecta el sistema con SQL Server y con la base de datos InventarioIA2?

`core/database.py` centraliza la conexión mediante pyodbc y ODBC Driver 17. Utiliza la instancia configurada `MSI\SQLSERVER`, la base `InventarioIA2` y autenticación integrada de Windows. No necesita una contraseña de aplicación en esa cadena. Los permisos efectivos dependen de la identidad de Windows que ejecuta el proceso.

### 15. ¿Qué errores o dependencias faltantes podrían impedir su ejecución?

Pueden impedirla un servidor o base inaccesible, controlador ODBC ausente, permisos insuficientes, esquema incompleto o modelos no disponibles. FastAPI/Uvicorn faltaban para la API opcional; spaCy/RapidFuzz no estaban instalados, aunque el NLP tiene alternativas. Se identificó una importación de `inspeccionar_esquema` en `cargar_datos_inventario.py` incompatible con su ubicación actual en `herramientas/`. No se corrigió durante la auditoría de solo lectura.

## 4. Manual de usuario

**Estado actual:** parcial.  
**Evidencia:** `README.md`, `main.py`, `ui/interfaz.py`, `ui/ventanas_camara.py`, `ui/prediccion_ui.py` y `integrations/reporting/reportes_ui.py`.  
**Implementado:** navegación y operaciones desde escritorio con mensajes de estado.  
**Información faltante:** manual ilustrado validado paso a paso.  
**Próximas acciones:** capturar el flujo actual y comprobar manualmente periféricos, exportaciones y errores recuperables.

### 16. ¿Qué interfaces y operaciones están disponibles para el usuario?

El usuario puede consultar existencias, administrar catálogo y empleados, registrar movimientos, revisar historial y alertas, localizar productos en el mapa, utilizar reconocimiento facial, consultar JARVIS y generar análisis/reportes. Las opciones concretas dependen del estado de la base y de los recursos disponibles. No se requiere iniciar sesión en una cuenta de aplicación.

### 17. ¿Cómo se inicia la aplicación y cómo se accede a sus módulos?

Desde la raíz del proyecto se activa el entorno Python y se ejecuta `python main.py`. La aplicación abre directamente su interfaz y permite navegar por los módulos disponibles. La conexión SQL y los archivos de modelos deben prepararse antes. El recorrido exacto de botones debe ilustrarse con capturas de la versión actual.

### 18. ¿Qué operaciones de inventario pueden realizarse?

Se pueden consultar productos y saldos por ubicación, registrar entradas, salidas y transferencias y trabajar con las ampliaciones de lotes y conteos según su flujo. Los servicios validan cantidades, disponibilidad y referencias, y utilizan transacciones para mantener consistencia. Una transferencia debe redistribuir existencias sin reducir el stock total del producto.

### 19. ¿Cómo se utilizan las funciones de inteligencia artificial?

En empleados se abre el reconocimiento con la cámara configurada y se observa si el resultado es reconocido, desconocido o en verificación. En análisis se selecciona el producto o período para consultar consumo y cobertura. En anomalías se revisan hallazgos y sus motivos. En JARVIS se escribe o se pulsa Hablar; ambos canales procesan consultas con el mismo contexto de la sesión de escritorio.

### 20. ¿Qué errores frecuentes y mensajes de respuesta aparecen en la aplicación?

Los módulos contemplan mensajes por datos insuficientes, producto no encontrado o inactivo, rostro de baja calidad, desconocido, cámara no disponible y problemas de micrófono o modelo Vosk. Edge TTS puede responder HTTP 403; el sistema lo desactiva durante la sesión después del primer fallo y usa síntesis local. La redacción exacta de cada diálogo debe copiarse de su ejecución actual. El código permite documentar los flujos previstos; audio real, cámara, exportaciones y recuperación de errores requieren comprobación manual.

## 5. Documentación técnica

**Estado actual:** parcial.  
**Evidencia:** `README.md`, `requirements.txt`, `herramientas/`, `migrations/`, `modelos/` y archivos de configuración.  
**Implementado:** documentación unificada y recursos organizados por función.  
**Información faltante:** inventario reproducible de dependencias y guía completa del esquema actual.  
**Próximas acciones:** distinguir antecedentes del README de las instrucciones vigentes.

### 21. ¿Cuál es la estructura de carpetas y archivos principales?

En la raíz están el punto de entrada, interfaz, conexión y módulos funcionales. `herramientas/` agrupa inspección y mantenimiento; `migrations/` conserva ampliaciones SQL; `pruebas/` contiene verificaciones; `modelos/` conserva recursos faciales; `modelos_voz/` contiene Vosk. También existen directorios de evaluación, respaldos, salidas y verificación visual. El README reúne la documentación principal.

### 22. ¿Qué tecnologías, bibliotecas y versiones utiliza el proyecto?

El entorno revisado utiliza Python 3.9.13, SQL Server 16.0.1200.5 Developer Edition, pyodbc 5.3.0, opencv-contrib-python 4.14.0.94 y TensorFlow 2.20.0. También se comprobaron NumPy 2.0.2, pandas 2.3.3, scikit-learn 1.6.1, Matplotlib 3.9.4, ttkbootstrap 1.18.2, Vosk 0.3.45, sounddevice 0.5.6, pyttsx3 2.99 y edge-tts 7.2.8. Reportes utiliza, entre otras, ReportLab 5.0.1 y openpyxl 3.1.5. Son versiones observadas, no un archivo de bloqueo completo de dependencias.

### 23. ¿Dónde se configuran la base de datos, los modelos y las variables de entorno?

La conexión SQL está en `core/database.py`. `core/config_manager.py` administra `config_sistema.json`; `reconocimiento_facial_config.json` mantiene compatibilidad facial. Los modelos y calibraciones residen en sus directorios configurados y `intenciones_jarvis.json` contiene el catálogo del NLP. Existen lecturas de variables de entorno para ciertas opciones, pero no se verificó un mecanismo general de carga automática de `.env` ni se inspeccionaron sus secretos.

### 24. ¿Qué archivos son necesarios para ejecutar cada componente?

Escritorio requiere `main.py`, la interfaz, servicios, configuración, dependencias y base SQL. Facial necesita el pipeline, detector YuNet, extractor SFace, galería y relaciones de empleados; CNN requiere modelo y etiquetas compatibles. Voz necesita `jarvis/asistente_voz.py` y el modelo Vosk español. Predicción y anomalías requieren sus módulos y datos SQL. Los recursos de modelos excluidos del control de versiones deben distribuirse por un procedimiento documentado.

### 25. ¿Qué documentación técnica existe y qué información falta?

Existe `README.md` con instalación, módulos, mantenimiento y antecedentes; también hay scripts SQL, verificaciones y resultados de evaluación. Falta consolidar un procedimiento de instalación independiente del equipo de desarrollo, una restauración comprobada, criterios de aceptación y versiones totalmente reproducibles. Parte de los antecedentes puede describir estados superados y debe interpretarse con esa precaución.

## 6. Plan de monitoreo

**Estado actual:** parcial.  
**Evidencia:** `core/estado_sistema.py`, `ui/estado_ui.py`, `ui/dashboard.py`, `ai/facial/diagnostico_facial_basico.py` y `evaluacion_facial/`.  
**Implementado:** estados de interfaz, diagnóstico y resultados de evaluación.  
**Información faltante:** registros durables centralizados y supervisión periódica.  
**Próximas acciones:** definir indicadores y registrar fallos técnicos sin almacenar datos sensibles innecesarios.

### 26. ¿Qué mecanismos existen para registrar errores y eventos?

Existen mensajes en interfaz, salidas de consola, trazas de error y resultados de diagnóstico/evaluación. Los movimientos y hallazgos funcionales se conservan en SQL según el módulo. No se verificó un sistema central de archivos rotativos y persistentes para todos los errores. Los registros funcionales no deben presentarse como una bitácora de auditoría de acceso.

### 27. ¿Se puede comprobar la disponibilidad de la aplicación y la conexión con la base de datos?

Sí: la interfaz de estado ofrece comprobaciones de componentes y la conexión SQL puede verificarse con una consulta simple como `SELECT 1`. Esto acredita disponibilidad en el momento de la comprobación, no supervisión continua. La ruta de salud de la API opcional no sustituye una comprobación real de todos los servicios.

### 28. ¿Existen indicadores o registros para supervisar las predicciones, las anomalías y el reconocimiento facial?

Predicción presenta consumo, cobertura y riesgo; anomalías muestra motivos y resultados. Facial dispone de diagnóstico, calibraciones, métricas de CNN y mediciones de etapas. Faltan series de seguimiento independiente que relacionen predicciones con resultados posteriores y errores faciales con identidades verificadas en nuevas sesiones.

### 29. ¿Qué mecanismos de monitoreo están implementados y cuáles habría que proponer?

Están implementados controles manuales de estado, diagnóstico y visualización de resultados. Se recomienda definir revisiones periódicas de SQL, modelos, cámara, audio y tiempos de respuesta, además de registros técnicos persistentes. Estas propuestas no implican agregar usuarios, roles o auditoría al sistema.

### 30. ¿Qué aspectos deberían supervisarse para detectar fallos o resultados poco fiables?

Disponibilidad SQL, consistencia de stock, cantidad y actualidad del historial, transferencias excluidas del consumo y predicciones sin evidencia suficiente. En facial: calidad, tamaño del rostro, falsos reconocimientos, desconocidos y estabilidad temporal. En JARVIS: resolución de entidades, contexto pendiente, respuestas basadas en SQL y fallos de audio. No debe confundirse una puntuación del modelo con una probabilidad garantizada de acierto.

## 7. Plan de mantenimiento

**Estado actual:** parcial.  
**Evidencia:** `herramientas/`, `migrations/`, `backups/inventario/`, `ai/facial/entrenar_cnn_rostros.py`, regeneración facial y `core/config_manager.py`.  
**Implementado:** herramientas de inspección, migraciones y respaldo de determinados recursos.  
**Información faltante:** restauración completa de SQL, calendario y responsables confirmados.  
**Próximas acciones:** preparar una copia nativa y ensayar recuperación en una base separada.

### 31. ¿Qué procedimientos de actualización de dependencias y componentes existen?

Las dependencias se instalan con pip a partir de `requirements.txt`. Existen migraciones SQL y scripts de entrenamiento/regeneración. No se verificó un procedimiento formal de actualización con versiones bloqueadas, comprobaciones previas y reversión ensayada. Se recomienda conservar el entorno que funciona y evaluar cambios en una copia separada antes de la demostración.

### 32. ¿Hay scripts de mantenimiento, respaldo y restauración de la base de datos?

Existen herramientas de inspección y migración y archivos JSON de respaldo de registros. También hay respaldos de recursos faciales y estructura del proyecto. No se encontró un procedimiento completo y comprobado de `BACKUP DATABASE`/`RESTORE DATABASE` para la base actual. Los JSON no acreditan por sí solos una recuperación integral del esquema y sus relaciones.

### 33. ¿Cómo podrían recuperarse los datos ante una falla?

Como propuesta, realizar una copia nativa de SQL Server y conservar por separado configuración, imágenes autorizadas, modelos y galería compatibles. La restauración debe probarse en otra base antes de depender de ella. Después deben verificarse catálogo, saldos, relaciones y funciones principales. No se puede prometer un tiempo de recuperación porque no fue medido.

### 34. ¿Qué modelos necesitan actualización o reentrenamiento y bajo qué condiciones?

La galería SFace necesita regeneración cuando cambian extractor o pipeline, y ampliación con muestras autorizadas al registrar personas. Cambios de condiciones de captura pueden exigir nueva evaluación y calibración. La CNN requiere reentrenamiento al cambiar clases o dataset. El catálogo NLP debe mantenerse cuando se añaden intenciones; predicción y anomalías necesitan revisar suficiencia y distribución del historial, no necesariamente un reentrenamiento permanente.

### 35. ¿Qué tareas de mantenimiento están documentadas y cuáles están pendientes?

El README describe inspección, migraciones y recursos; hay herramientas de evaluación y regeneración facial. Están pendientes el calendario, la asignación explícita de responsables del equipo, una restauración ensayada y un procedimiento de actualización reproducible. La propuesta es que el equipo desarrollador mantenga estos componentes, sin crear roles de aplicación.

## 8. Plan de seguridad y privacidad

**Estado actual:** parcial; sin autenticación de aplicación por decisión del proyecto.  
**Evidencia:** `core/database.py`, `main.py`, `inventory/inventario_service.py`, `ai/facial/rostros_empleados.py`, galería facial y confirmaciones del desarrollador.  
**Implementado:** autenticación Windows para SQL, validaciones y transacciones; registro facial autorizado por el equipo según su confirmación.  
**Información faltante:** evidencia documental de consentimiento, conservación y protección de copias.  
**Próximas acciones:** documentar el alcance académico y revisar permisos del entorno y exposición de archivos.

### 36. ¿Qué mecanismos de autenticación y autorización existen?

No hay login, usuarios ni roles de aplicación, por decisión expresa del desarrollador. SQL utiliza autenticación integrada de Windows. La selección de un empleado en un movimiento o su reconocimiento facial no constituye autenticación de seguridad. La instancia y el sistema operativo siguen siendo responsables de permitir o rechazar la conexión.

### 37. ¿Cómo se gestionan las credenciales y la conexión con SQL Server?

La conexión central utiliza la identidad Windows y no contiene contraseña SQL de aplicación. En la conexión de auditoría se observaron privilegios `sysadmin` y `db_owner`; ese resultado corresponde a la identidad utilizada en esa revisión. La configuración observada incluye `Encrypt=no` y `TrustServerCertificate=yes`. Para otra instalación debe revisarse esa configuración y limitar los privilegios de la identidad SQL según sus necesidades.

### 38. ¿Qué datos personales o biométricos se almacenan y cómo se utilizan?

Se conservan datos de empleados, imágenes de rostros, etiquetas y embeddings asociados con identidades. Se utilizan para entrenamiento, regeneración y reconocimiento. El desarrollador confirmó correspondencia de las imágenes y autorización del equipo que registró sus rostros. Esa confirmación no demuestra por sí sola la existencia de formularios escritos, política de conservación o cifrado de recursos.

### 39. ¿Existen controles de acceso, validación de entradas, registros de actividad y copias de seguridad?

Existen permisos Windows/SQL externos a la aplicación, consultas parametrizadas, validaciones de cantidad y disponibilidad, claves foráneas y transacciones. Hay historial de movimientos y respaldos de determinados recursos. No hay autorización individual de aplicación ni auditoría de acceso, y no se verificó una restauración completa. El historial indica el empleado asociado al registro, pero no prueba quién utilizó físicamente el equipo.

### 40. ¿Qué riesgos técnicos y medidas de protección deberían documentarse?

Debe documentarse el acceso al equipo y a SQL, el uso de privilegios amplios, conservación de biometría, copias y sincronización del proyecto ubicado en OneDrive. El estado real de sincronización y compartición no se verificó. Edge TTS envía el texto que debe sintetizar al servicio externo; el modo local evita ese envío para la síntesis. Se recomienda limitar la difusión de recursos personales y documentar qué información se utiliza en la demostración.

## 9. Presentación final

**Estado actual:** parcial; demostración preparada, validación integral pendiente.  
**Evidencia:** interfaz, registros SQL, reportes, `verificacion_ui/` y resultados faciales.  
**Implementado:** funciones y material de verificación disponibles.  
**Información faltante:** recorrido final grabado o documentado con la versión vigente.  
**Próximas acciones:** presentar funciones y límites con registros identificados como preparados para fines académicos.

### 41. ¿Qué funcionalidades pueden demostrarse con el sistema actual?

Consulta de inventario, distribución por ubicaciones, entradas, salidas y transferencias, alertas, mapa, reportes y análisis. También conversación JARVIS por texto/voz y reconocimiento de integrantes registrados. Los datos permiten explicar consumo y movimientos inusuales, pero fueron preparados para desarrollo y demostración; no representan operaciones verificadas de un taller real.

### 42. ¿Qué capturas, resultados de ejecución o pruebas pueden servir como evidencia?

Capturas actuales de módulos, reportes generados, consultas SQL y archivos de evaluación. `modelos/metricas_modelo_rostros.json` registra la evaluación CNN; `evaluacion_facial/verificacion_pipeline.json` muestra una comprobación del pipeline con imágenes registradas. Se reportó una ejecución anterior de 178 verificaciones con 177 aprobadas y una omitida por FastAPI; durante la auditoría se ejecutaron únicamente seis verificaciones en memoria, todas aprobadas. Estos resultados tienen alcances distintos.

### 43. ¿Qué limitaciones deben mencionarse para no exagerar las capacidades del producto?

Es una demostración académica local, con historial preparado. La CNN no garantiza reconocimiento de personas desconocidas y su métrica no acredita el desempeño de SFace. La prueba facial con imágenes registradas no valida cámaras, iluminación o distancias nuevas. Predicción ofrece estimaciones, anomalías ofrece indicios y no hay recuperación ni despliegue productivo certificado. SQL Server Developer Edition corresponde al entorno de desarrollo, no a una licencia para operación productiva.

## 10. Informe final del proyecto

**Estado actual:** parcial; evidencia de integración disponible.  
**Evidencia:** revisión SQL anterior, modelos/calibraciones, pruebas, `README.md` y respuestas del desarrollador.  
**Implementado:** solución local integrada con datos persistentes y recursos de IA.  
**Información faltante:** validación independiente, instalación reproducible y aceptación final documentada.  
**Próximas acciones:** presentar resultados medidos con su alcance y separar pendientes técnicos de funciones disponibles.

### 44. ¿Qué información verificable existe sobre el estado actual de la solución?

La revisión SQL anterior comprobó 24 productos, 16 empleados, 16 relaciones faciales, 253 movimientos y 30 registros de existencias. La galería revisada contenía 192 embeddings compatibles. Se verificaron módulos, versiones instaladas y resultados almacenados de evaluación. Estas cifras son una fotografía de aquella inspección; no deben interpretarse como una consulta actualizada al momento de abrir este documento.

### 45. ¿Qué componentes están terminados, parcialmente terminados o pendientes?

La interfaz y conexión entre los módulos principales están implementadas para la etapa académica. Reconocimiento facial, predicción y anomalías están funcionalmente integrados, pero parcialmente validados para nuevas condiciones o actividad real. Permanecen pendientes la recuperación comprobada, la instalación independiente del equipo y criterios de aceptación documentados. No existe requisito de agregar usuarios, roles o login.

### 46. ¿Qué resultados pueden respaldarse mediante pruebas o registros?

La evaluación CNN almacenada informa aproximadamente 92.31 % de acierto, equivalente a 36 de 39 imágenes de su partición de evaluación entre clases conocidas. La comprobación del pipeline con 16 imágenes registradas obtuvo 15 reconocimientos y rechazó una por tamaño facial insuficiente; no fue una evaluación independiente. Los archivos de calibración y verificaciones funcionales respaldan condiciones específicas, pero no permiten afirmar una precisión universal o una tasa de falsos positivos frente a desconocidos.

### 47. ¿Qué aspectos no pueden considerarse concluidos todavía?

Evaluación facial con desconocidos y sesiones nuevas, validación de cámara/iluminación/distancia, contrastación predictiva con datos posteriores, aceptación de hallazgos de anomalías y restauración completa de SQL. Tampoco se confirmó un despliegue productivo ni un procedimiento totalmente reproducible de instalación. Que el equipo considere aceptables los resultados CNN para la demostración no elimina esos pendientes.

## 11. Informe de lecciones aprendidas

**Estado actual:** parcial; correcciones identificadas, evaluación del proceso pendiente.  
**Evidencia:** `README.md`, módulos conversacionales, voz, pipeline facial, formato numérico y archivos de evaluación.  
**Implementado:** correcciones de contexto, síntesis, calibración y presentación.  
**Información faltante:** valoración del equipo sobre tiempo, organización y dificultades no registradas en código.  
**Próximas acciones:** documentar decisiones y conservar evidencia de cada evaluación independiente.

### 48. ¿Qué errores, incompatibilidades o problemas técnicos aparecen documentados?

Errores HTTP 403 de Edge TTS, pérdida de contexto de JARVIS, discrepancias entre preprocesamientos faciales y dificultades con calidad/tamaño de rostro. Se identificaron dependencias opcionales ausentes, importaciones afectadas por reorganización y un esquema histórico distinto de la base actual. Una exportación SQL localizada fuera del proyecto utilizaba compatibilidad 170 y rutas de otra instalación; no debe asumirse que puede ejecutarse sin adaptación en SQL Server 2022.

### 49. ¿Qué cambios o correcciones pueden identificarse en el repositorio?

Se incorporaron estado conversacional, resolución de entidades e intenciones pendientes compartidas entre texto y voz. Voz mantiene cola, cancelación y fallback local después del fallo de Edge. Facial incluye calibración ligada a recursos, evaluación de calidad, consenso temporal y una interfaz más limpia. La presentación numérica centraliza dos decimales sin modificar por ello el valor interno almacenado. También se documentaron servicios compartidos para mapa, inventario, predicción y JARVIS.

### 50. ¿Qué conclusiones técnicas pueden obtenerse de la implementación y cuáles requieren consultar al desarrollador?

El código y las verificaciones permiten concluir que existe una aplicación local integrada y que reutilizar servicios reduce contradicciones entre pantallas, voz y consultas. La calidad de un modelo necesita evaluación independiente, no solo calibración o demostraciones con registros conocidos. El desarrollador confirmó finalidad académica, preparación de los datos y autorización del equipo para rostros. Aún requieren su confirmación los responsables, criterios finales de aceptación, conservación de biometría y condiciones reales de presentación.

## Preguntas que solamente puede responder el equipo desarrollador

Las respuestas ya confirmadas no se solicitan nuevamente. Las siguientes decisiones no pueden deducirse de los archivos:

1. ¿En qué equipo, cámara, iluminación y distancia se realizará la presentación final?
2. ¿Qué criterios concretos aceptará el equipo para CNN y, por separado, para el reconocimiento SFace?
3. ¿Qué pruebas independientes con personas desconocidas y nuevas sesiones se compromete a completar antes de presentar resultados definitivos?
4. ¿Quién se encargará de mantener código, base de datos y recursos faciales después de la entrega académica?
5. ¿Durante cuánto tiempo conservará el equipo imágenes y embeddings, y cómo atenderá una solicitud de retiro de un participante?
6. ¿Existe evidencia documental del consentimiento y cuál es su alcance de uso y difusión?
7. ¿Está activada la sincronización o compartición de los archivos personales y biométricos en OneDrive?
8. ¿Dónde se conservará una copia completa de la base y quién comprobará su restauración?
9. ¿Qué resultados del recorrido de demostración considerará suficientes para aprobar la entrega?

## Conclusión para la fase 3.6

El proyecto cuenta con una implementación de escritorio integrada para una demostración académica, conectada a SQL Server y alimentada con registros preparados por el equipo. Incluye inventario, mapa, reconocimiento facial, JARVIS por texto y voz, predicción y análisis de anomalías. Existen evidencias de integración y evaluaciones con alcance limitado. La validación en nuevas condiciones, la recuperación de datos y la instalación reproducible siguen pendientes; por ello no se presenta como una solución ya desplegada y validada en operación productiva.

## Referencias técnicas de apoyo

- Microsoft: [Ediciones y componentes de SQL Server 2022](https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2022/). Developer Edition está orientada a desarrollo y evaluación, no a producción.
- Microsoft: [Nivel de compatibilidad de bases de datos](https://learn.microsoft.com/en-us/sql/t-sql/statements/alter-database-transact-sql-compatibility-level?view=sql-server-ver16). SQL Server 2022 admite hasta el nivel 160; una exportación con nivel 170 requiere revisar la versión de destino.
