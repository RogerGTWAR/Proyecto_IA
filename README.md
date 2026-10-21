# Sistema Inteligente de Inventario

**Gestión y análisis de inventario para el almacén de un taller mecánico mediante inteligencia artificial.**

Aplicación de escritorio desarrollada en Python que integra inventario por ubicación, movimientos, reconocimiento facial, análisis de consumo, vigilancia y un asistente conversacional llamado **JARVIS**. Incluye un bot de Telegram para consultas y notificaciones.

El proyecto tiene una finalidad académica y representa un taller mecánico hipotético. Los registros operativos fueron preparados para su desarrollo y demostración; no deben interpretarse como información recolectada de un taller en funcionamiento.

## Funcionalidades

| Módulo | Función |
| --- | --- |
| Dashboard | Resume existencias, productos críticos, movimientos y estado de los servicios. |
| Productos | Administra productos, categorías, unidades de medida y datos del catálogo. |
| Movimientos e historial | Registra entradas, salidas, transferencias y ajustes con su responsable. |
| Mapa del almacén | Localiza productos y permite consultar su distribución entre ubicaciones y posiciones. |
| Conteo físico | Organiza el conteo por ubicación, conserva borradores y permite revisar diferencias antes de aplicar ajustes. |
| Alertas | Presenta condiciones relevantes del inventario y eventos del sistema. |
| Empleados y reconocimiento facial | Relaciona empleados con identidades faciales y permite utilizar los motores disponibles. |
| Predicción de stock | Estima consumo, cobertura y riesgo de agotamiento a partir del historial de salidas. |
| Anomalías | Detecta movimientos que se apartan del comportamiento registrado. |
| JARVIS | Atiende consultas por texto o voz, conserva contexto y coordina herramientas del sistema. |
| Vigilancia | Separa intrusión en una cámara y presencia de empleados en una segunda cámara. |
| Telegram | Entrega notificaciones y permite conversar con JARVIS desde el chat autorizado. |
| Reportes | Genera vistas de información y exportaciones en PDF y Excel. |
| Estado y configuración | Centraliza disponibilidad de servicios y ajustes de funcionamiento. |
| Arduino | Integra señalización mediante LEDs, con simulación y conexión física opcional. |

Los responsables de los movimientos son empleados del almacén. La aplicación de escritorio abre directamente: no implementa cuentas de acceso, roles ni login.

## Tecnologías

- **Aplicación:** Python, Tkinter y ttkbootstrap.
- **Base de datos:** SQL Server, pyodbc y ODBC Driver 17 for SQL Server.
- **Procesamiento de imágenes:** OpenCV y NumPy.
- **Reconocimiento facial:** YuNet/SFace con embeddings y una CNN con TensorFlow/Keras.
- **Vigilancia:** YOLOv8 y ByteTrack.
- **Voz:** Vosk para reconocimiento; Edge TTS y pyttsx3 para síntesis.
- **Análisis:** pandas, scikit-learn y Matplotlib, según el módulo.
- **Reportes:** ReportLab y openpyxl.
- **Integraciones:** Telegram Bot API y comunicación serial opcional con Arduino.

## Organización del proyecto

```text
main.py                 Inicio de la aplicación
core/                   Conexión, configuración, eventos y estado de servicios
inventory/              Productos, movimientos, ubicaciones y conteo físico
jarvis/                 Conversación, herramientas y voz del asistente
ai/
  facial/               Reconocimiento, datos y entrenamiento facial
  prediction/           Predicción de stock
  anomalies/            Detección de anomalías
surveillance/           Intrusión, presencia y captura de cámaras
integrations/
  telegram/             Bot y notificaciones
  arduino/              Señalización y comunicación serial
  reporting/            Generación de reportes
ui/                     Pantallas y componentes de la interfaz
tools/                  Herramientas de preparación y mantenimiento
tests/                  Pruebas automatizadas
sql/                    Scripts SQL y cargas de registros
migrations/             Cambios de esquema conservados por el proyecto
docs/                   Documentación y entregables
modelos/                Recursos locales de los modelos
modelos_voz/            Modelo local de reconocimiento de voz
```

También se conservan carpetas auxiliares con recursos de verificación y dependencias complementarias. Los resultados, registros y respaldos se generan en carpetas locales.

## Requisitos

- Windows con Python y soporte para Tkinter. El entorno de desarrollo revisado utiliza **Python 3.9.13**.
- SQL Server con una base `InventarioIA2` compatible con el esquema actual.
- ODBC Driver 17 for SQL Server.
- Dependencias de [requirements.txt](requirements.txt).
- Cámara y micrófono para las funciones que los requieren.
- Dos fuentes de vídeo distintas para operar ambos paneles de Vigilancia simultáneamente.
- Modelos y recursos locales correspondientes a las funciones habilitadas.

Telegram y Edge TTS requieren Internet. Vosk y la voz local pueden funcionar sin conexión cuando sus recursos están instalados.

## Instalación

### 1. Preparar el entorno

Clona el repositorio o descarga su código. Abre PowerShell en la carpeta del proyecto:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

El archivo de dependencias utiliza rangos de versiones. La instalación en un equipo nuevo requiere comprobar compatibilidad; no se presenta como una distribución independiente del entorno de desarrollo.

### 2. Preparar SQL Server

Configura en [core/database.py](core/database.py) los valores `SERVER`, `DATABASE` y `DRIVER` correspondientes a tu instalación. Actualmente la conexión utiliza **autenticación integrada de Windows**.

La aplicación necesita una base con el esquema operativo actual. Los scripts de `sql/` y `migrations/` deben revisarse según el estado de esa base antes de aplicarlos. **`sql/Base de Datos.sql` es un esquema histórico de `InventarioIA1`; no es un instalador completo de la base actual `InventarioIA2`.**

Comprueba la conexión configurada con:

```powershell
.\.venv\Scripts\python.exe -m core.database
```

Clonar el código no copia ni crea automáticamente la base de datos local.

### 3. Preparar recursos opcionales

| Función | Recursos necesarios |
| --- | --- |
| Voz de entrada | Modelo Vosk en `modelos_voz/vosk-model-small-es-0.42/` y micrófono disponible. |
| Reconocimiento con embeddings | Pesos YuNet/SFace, galería facial y calibración compatibles. |
| Reconocimiento CNN | Modelo entrenado, etiquetas y configuración compatibles con el conjunto facial. |
| Vigilancia | Modelo YOLO local, dependencias de vigilancia y fuentes de vídeo configuradas. |
| Telegram | Token del bot y chat autorizado. |
| Arduino físico | Dispositivo, programa del microcontrolador y puerto serial configurados. |

La herramienta de preparación de Vigilancia está orientada al entorno Windows x64 con Python 3.9 del proyecto:

```powershell
.\.venv\Scripts\python.exe -m tools.preparar_vigilancia --instalar
```

Esta preparación puede descargar dependencias y recursos. No se realiza automáticamente al abrir el sistema. Evita instalar variantes de OpenCV que entren en conflicto con `opencv-contrib-python`.

### 4. Configurar Telegram

Crea un archivo `.env` local en la raíz con los valores de tu bot:

```dotenv
TELEGRAM_BOT_TOKEN=TU_TOKEN_DE_TELEGRAM
TELEGRAM_CHAT_ID=TU_CHAT_AUTORIZADO
```

Reemplaza los marcadores con tus valores. El archivo `.env` está excluido de Git y no debe publicarse con credenciales reales.

## Ejecución

Desde la raíz del proyecto:

```powershell
python main.py
```

El lanzador utiliza el entorno `.venv` del proyecto cuando está disponible. También puedes iniciarlo directamente:

```powershell
.\.venv\Scripts\python.exe main.py
```

Los ajustes generales, cámaras, voz y notificaciones se administran desde **Configuración**. Determinados cambios se aplican al iniciar una nueva sesión del servicio correspondiente.

## JARVIS y Telegram

JARVIS comparte su lógica conversacional entre texto y voz. Consulta los servicios del proyecto para responder sobre inventario, ubicaciones, movimientos, alertas, predicción y presencia. Las operaciones sensibles habilitadas requieren confirmación y utilizan los servicios existentes.

Ejemplos de consultas:

- «¿Qué productos tienen stock bajo?»
- «¿Dónde está este producto?»
- «¿Qué producto puede agotarse primero?»
- «¿Cuántas personas hay en la habitación?»

Los resultados dependen de la información disponible. La ausencia de datos, historial suficiente o servicios activos debe indicarse en la respuesta.

| Comando de Telegram | Uso |
| --- | --- |
| `/start` | Presentación del asistente y menú. |
| `/jarvis` | Activar el modo conversación. |
| `/estado` | Consultar el estado del sistema. |
| `/alertas` | Consultar el resumen de alertas. |
| `/presentes` | Consultar la presencia observada por la segunda cámara. |
| `/salir` | Salir de la conversación y mantener las notificaciones habilitadas. |
| `/help` | Mostrar ayuda. |

El bot restringe el acceso al chat autorizado. El envío de notificaciones depende también de las categorías y niveles configurados.

## Vigilancia con dos cámaras

- **Intrusión:** detección de personas, seguimiento, zona restringida, identidad facial cuando hay evidencia suficiente, snapshots, clips y alertas.
- **Presencia de empleados:** conteo de tracks activos, identificación con SFace, personas desconocidas y registro local de entradas y salidas observadas.

Cada cámara tiene fuente, ejecución, estado y FPS independientes. La segunda cámara no considera automáticamente una presencia como intrusión. Si el vídeo no está disponible, el sistema no debe interpretar esa ausencia como cero personas.

La presencia refleja lo observado dentro del campo de visión; no constituye un sistema de asistencia ni garantiza conocer la ocupación completa de una habitación.

## Verificación

La regresión principal sustituye las conexiones SQL y el transporte HTTP para comprobar funcionalidades sin modificar registros ni enviar notificaciones reales:

```powershell
.\.venv\Scripts\python.exe -m tools.verificar_eventos
```

Para revisar únicamente la presencia de empleados:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.probar_presencia_empleados
```

La validación registrada de la ampliación a dos cámaras ejecutó **404 casos: 403 correctos y uno omitido por FastAPI opcional no instalado**. Las pruebas con capturas sustituidas no acreditan los FPS ni el reconocimiento con cámaras físicas.

## Datos, privacidad y limitaciones

- No publiques credenciales, imágenes faciales, embeddings personales, respaldos de la base ni evidencias que identifiquen a personas.
- Los modelos, muestras y recursos locales pueden requerir preparación adicional; no todos están incluidos o versionados junto al código.
- La precisión facial depende de calibración, iluminación, resolución y calidad del rostro. Son posibles errores de identificación.
- Las predicciones necesitan historial suficiente y representan estimaciones.
- El uso simultáneo de cámaras requiere comprobar el rendimiento en el equipo destino.
- No se ha verificado una instalación completa desde cero en un equipo independiente.
- Las licencias de modelos y dependencias deben revisarse antes de redistribuirlos.

El proyecto está en desarrollo y validación académica. Las pruebas de ciertos módulos no implican que todo el sistema esté listo para uso operativo.

## Documentación adicional

El contenido íntegro del README anterior se conserva en [docs/HISTORIAL_DEL_PROYECTO.txt](docs/HISTORIAL_DEL_PROYECTO.txt). Incluye antecedentes técnicos, cambios y comprobaciones de distintas etapas; algunas descripciones corresponden a versiones anteriores del proyecto.

Los demás documentos y entregables están organizados en [docs/](docs/).
