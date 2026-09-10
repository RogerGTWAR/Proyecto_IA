# Sistema Inteligente de Inventario

Aplicación universitaria de inventario con SQL Server, análisis de stock,
asistente de voz y reconocimiento facial CNN.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

El modelo Vosk activo debe estar descomprimido en:
`modelos_voz/vosk-model-small-es-0.42/`.

## SQL Server

La conexión se configura en `database.py` mediante `SERVER`, `DATABASE` y
`DRIVER`. La base esperada es `InventarioIA`. Los scripts SQL incluidos crean
la estructura y los datos necesarios sin formar parte del inicio normal.

## Ejecución

Con `.venv` activado:

```powershell
python main.py
```

`main.py` es el único punto de entrada para el uso normal. El entrenamiento de
la CNN, la captura de rostros y el reconocimiento se ejecutan desde la interfaz.
