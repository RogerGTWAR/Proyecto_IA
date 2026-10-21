"""Diagnóstico del flujo central. --enviar publica un texto y una imagen local."""
import argparse
import json
import sys
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from integrations.telegram.telegram_service import estado_telegram,servicio_telegram,probar_envio_telegram_real


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enviar',action='store_true')
    parser.add_argument('--imagen',type=Path)
    args=parser.parse_args()
    if not args.enviar:
        print(json.dumps(estado_telegram(),ensure_ascii=False,indent=2));return
    ruta=args.imagen
    carpeta=BASE/'outputs'/'telegram'
    carpeta.mkdir(parents=True,exist_ok=True)
    if ruta is None:
        parser.error('--enviar requiere --imagen con una captura real existente; no se generan imágenes de sustitución.')
    try:
        resultados=probar_envio_telegram_real(ruta)
        informe=dict(resultados=resultados,worker_vivo=bool(servicio_telegram.hilo and servicio_telegram.hilo.is_alive()),
            cola_pendientes=servicio_telegram.cola.qsize(),configuracion=estado_telegram())
        (carpeta/'diagnostico_entregas.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(informe,ensure_ascii=False,indent=2))
        if not all(resultados.get(k,{}).get('enviado') for k in ('texto','foto')):sys.exit(1)
    finally:
        servicio_telegram.cerrar()
        if servicio_telegram.hilo:servicio_telegram.hilo.join(3)


if __name__=='__main__':main()
