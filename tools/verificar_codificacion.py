"""Audita texto del proyecto sin modificar archivos ni mostrar secretos."""
import argparse
import io
import json
from pathlib import Path
import re
import tokenize

BASE = Path(__file__).resolve().parents[1]
EXTENSIONES = {'.py', '.json', '.sql', '.txt', '.md', '.ini', '.cfg', '.yaml', '.yml', '.toml'}
EXCLUIR = {'.git', '.venv', 'node_modules', '__pycache__', 'modelos_voz',
           'backups', 'respaldos_inventario', 'outputs'}
PALABRA = re.compile(r'[^\W\d_]\?[^\W\d_]', re.UNICODE)
INICIO_DANADO = re.compile(r'(?<!\w)\?(?:nic[oa]s?|nicamente|ltim[oa]s?|rea|rbol)\b', re.I)
URL = re.compile(r'(?:https?|wss?)://[^\s<>"\x27]+')
MARCADORES = ('\u00c3', '\u00c2', '\ufffd')


def problemas_texto(texto):
    """Conserva interrogaciones, parámetros SQL y consultas de URLs."""
    limpio = URL.sub('', texto)
    motivos = []
    if PALABRA.search(limpio) or INICIO_DANADO.search(limpio):
        motivos.append('interrogación dentro de palabra')
    if any(c in limpio for c in MARCADORES):
        motivos.append('posible mojibake o carácter de sustitución')
    return motivos


def revisar_archivo(ruta, base=BASE):
    nombre = ruta.relative_to(base).as_posix()
    datos = ruta.read_bytes()
    hallazgos = []
    try:
        texto = datos.decode('utf-8')
    except UnicodeDecodeError as error:
        return [{'archivo': nombre, 'linea': datos[:error.start].count(b'\n') + 1,
                 'motivo': 'archivo no válido como UTF-8'}]
    if datos.startswith(b'\xef\xbb\xbf'):
        hallazgos.append({'archivo': nombre, 'linea': 1, 'motivo': 'BOM UTF-8'})
    if ruta.suffix == '.py':
        # Buscar en literales/comentarios; nunca en operadores de Python.
        try:
            partes = [(t.start[0], t.string) for t in tokenize.generate_tokens(io.StringIO(texto).readline)
                      if t.type in (tokenize.STRING, tokenize.COMMENT)]
        except (tokenize.TokenError, IndentationError) as error:
            hallazgos.append({'archivo': nombre, 'linea': 1, 'motivo': str(error)})
            partes = []
    else:
        partes = [(1, texto)]
    for comienzo, parte in partes:
        for desplazamiento, linea in enumerate(parte.splitlines()):
            for motivo in problemas_texto(linea):
                item = {'archivo': nombre, 'linea': comienzo + desplazamiento, 'motivo': motivo}
                # No guardar líneas: podrían contener credenciales o datos personales.
                if item not in hallazgos:
                    hallazgos.append(item)
    if ruta.suffix == '.json':
        try:
            json.loads(texto)
        except ValueError as error:
            hallazgos.append({'archivo': nombre, 'linea': getattr(error, 'lineno', 1),
                             'motivo': 'JSON no válido'})
    return hallazgos


def auditar(base=BASE):
    archivos = sorted(p for p in base.rglob('*') if p.is_file()
                      and not any(x in EXCLUIR for x in p.relative_to(base).parts)
                      and (p.suffix.lower() in EXTENSIONES or p.name.startswith('.env')
                           or p.name == '.editorconfig'))
    hallazgos = [h for p in archivos for h in revisar_archivo(p, base)]
    return {'archivos_revisados': len(archivos), 'hallazgos': hallazgos,
            'correcto': not hallazgos,
            'alcance': 'Fuentes y configuración; excluye binarios, dependencias, respaldos y salidas generadas.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reporte', type=Path, default=BASE / 'outputs/codificacion/fuentes.json')
    args = parser.parse_args()
    resultado = auditar()
    args.reporte.parent.mkdir(parents=True, exist_ok=True)
    args.reporte.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado['correcto'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
