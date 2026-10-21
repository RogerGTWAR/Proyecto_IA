"""Instalación opcional de YOLO CPU sin sustituir NumPy, OpenCV ni TensorFlow.

Windows x64 / Python 3.9 del proyecto. Solo descarga desde PyTorch, PyPI y
Ultralytics; las ruedas se verifican contra SHA-256 del índice oficial.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit

import requests
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

BASE=Path(__file__).resolve().parents[1]
SALIDA=BASE/'outputs'/'instalacion_vigilancia'


def sha256(ruta):
    h=hashlib.sha256()
    with Path(ruta).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def descargar(url,destino,esperado=None,workers=32):
    destino=Path(destino);destino.parent.mkdir(parents=True,exist_ok=True)
    if destino.is_file() and (esperado is None or sha256(destino)==esperado):return destino
    inicio=requests.get(url,headers={'Range':'bytes=0-0'},stream=True,timeout=(15,30))
    if inicio.status_code==206 and 'Content-Range' in inicio.headers:
        total=int(inicio.headers['Content-Range'].split('/')[-1]);inicio.close()
        parcial=destino.with_suffix(destino.suffix+f'.{os.getpid()}.part')
        with parcial.open('wb') as f:f.truncate(total)
        tamano=256*1024;contador=[0];lock=threading.Lock()
        def segmento(a):
            b=min(total-1,a+tamano-1)
            for intento in range(3):
                try:
                    separador='&' if '?' in url else '?'
                    respuesta=requests.get(url+separador+f'inventario_segment={a}',
                        headers={'Range':f'bytes={a}-{b}'},timeout=(15,45))
                    if respuesta.status_code!=206 or respuesta.headers.get('Content-Range')!=f'bytes {a}-{b}/{total}' or len(respuesta.content)!=b-a+1:
                        raise ValueError('Segmento incompleto.')
                    with parcial.open('r+b') as f:f.seek(a);f.write(respuesta.content)
                    with lock:
                        contador[0]+=len(respuesta.content)
                        if contador[0]//(10*1024*1024)!=(contador[0]-len(respuesta.content))//(10*1024*1024):
                            print(f'{destino.name}: {contador[0]/1024/1024:.0f}/{total/1024/1024:.0f} MB',flush=True)
                    return
                except Exception:
                    if intento==2:raise
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for futuro in as_completed(pool.submit(segmento,a) for a in range(0,total,tamano)):futuro.result()
    else:
        inicio.close();respuesta=requests.get(url,timeout=(15,60));respuesta.raise_for_status()
        parcial=destino.with_suffix(destino.suffix+f'.{os.getpid()}.part');parcial.write_bytes(respuesta.content)
    if esperado and sha256(parcial)!=esperado:raise ValueError('El SHA-256 del archivo no coincide con su índice oficial.')
    os.replace(parcial,destino)
    print('Verificado:',destino.name,flush=True)
    return destino


def rueda_pypi(paquete,ver,workers):
    r=requests.get(f'https://pypi.org/pypi/{paquete}/{ver}/json',timeout=30);r.raise_for_status()
    tags=set(sys_tags())
    for f in r.json()['urls']:
        if f['filename'].endswith('.whl') and parse_wheel_filename(f['filename'])[3]&tags:
            return descargar(f['url'],SALIDA/f['filename'],f['digests']['sha256'],workers)
    raise ValueError('No hay rueda compatible para '+paquete)


def rueda_torch(paquete,archivo,workers):
    indice=requests.get(f'https://download.pytorch.org/whl/cpu/{paquete}/',timeout=30);indice.raise_for_status()
    enlace=next(x for x in re.findall(r'href="([^"]+)"',indice.text) if archivo in x and '#sha256=' in x)
    esperado=enlace.split('#sha256=')[1].split('&')[0]
    return descargar('https://download.pytorch.org/whl/cpu/'+archivo,
                     SALIDA/unquote(archivo),esperado,workers)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instalar',action='store_true',help='Instalar dependencias y descargar el modelo oficial.')
    parser.add_argument('--workers',type=int,default=32)
    args=parser.parse_args()
    if not args.instalar:parser.print_help();return
    if sys.version_info[:2]!=(3,9) or sys.platform!='win32':
        raise ValueError('Este instalador está fijado para Windows x64 y Python 3.9; revise versiones antes de usar otro entorno.')
    if not 1<=args.workers<=64:raise ValueError('Workers debe estar entre 1 y 64.')
    protegidos={p:version(p) for p in ('numpy','opencv-contrib-python','tensorflow')}
    SALIDA.mkdir(parents=True,exist_ok=True)
    ruedas=[rueda_torch('torch','torch-2.5.1%2Bcpu-cp39-cp39-win_amd64.whl',args.workers),
            rueda_torch('torchvision','torchvision-0.20.1%2Bcpu-cp39-cp39-win_amd64.whl',args.workers)]
    requeridos={'ultralytics':'8.3.228','ultralytics-thop':'2.0.18','lap':'0.5.12',
        'python-dotenv':'1.2.1','polars':'1.35.2','polars-runtime-32':'1.35.2','psutil':'7.2.2','pyyaml':'6.0.3',
        'sympy':'1.13.1','mpmath':'1.3.0','filelock':'3.19.1','networkx':'3.2.1','fsspec':'2025.9.0','jinja2':'3.1.6'}
    for paquete,ver in requeridos.items():
        try:
            if version(paquete)==ver:continue
        except PackageNotFoundError:pass
        ruedas.append(rueda_pypi(paquete,ver,args.workers))
    subprocess.run([sys.executable,'-m','pip','install','--no-deps',*[str(x) for x in ruedas]],check=True)
    for p,v in protegidos.items():
        if version(p)!=v:raise RuntimeError('Cambió inesperadamente una dependencia protegida: '+p)
    modelo=BASE/'modelos/vigilancia/yolov8n.pt'
    descargar('https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt',modelo,workers=args.workers)
    (SALIDA/'instalacion.json').write_text(json.dumps({'protegidos':protegidos,
        'versiones':{p:version(p) for p in ('torch','torchvision',*requeridos)},
        'modelo_sha256':sha256(modelo)},indent=2),encoding='utf-8')
    print('YOLO CPU instalado; NumPy, OpenCV y TensorFlow conservaron sus versiones.',flush=True)


if __name__=='__main__':main()
