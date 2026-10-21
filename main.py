import os
from pathlib import Path
import subprocess
import sys


def main():
    # Evitar que una consola con otra página de códigos degrade los mensajes.
    for salida in (sys.stdout, sys.stderr):
        if hasattr(salida, 'reconfigure'):
            salida.reconfigure(encoding='utf-8', errors='backslashreplace')
    entorno = Path(__file__).resolve().parent / '.venv'
    python_proyecto = entorno / 'Scripts' / 'python.exe'
    if (python_proyecto.is_file()
            and os.path.normcase(os.path.realpath(sys.prefix))
            != os.path.normcase(os.path.realpath(entorno))):
        # Usar las dependencias del proyecto antes de importar la interfaz.
        entorno_proceso = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        return subprocess.call(
            [str(python_proyecto), '-X', 'utf8', str(Path(__file__).resolve()), *sys.argv[1:]],
            env=entorno_proceso)

    from ui.interfaz import iniciar_aplicacion
    iniciar_aplicacion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
