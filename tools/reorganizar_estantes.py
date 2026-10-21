"""Aplicar la organización física sobre InventarioIA2 y conservar su resultado."""
import json
from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from core.database import conectar


def reorganizar():
    c = conectar()
    c.autocommit = True
    conjuntos = []
    try:
        q = c.cursor()
        q.execute((RAIZ/'sql/reorganizar_estantes.sql').read_text(encoding='utf-8'))
        while True:
            if q.description:
                campos = [f[0] for f in q.description]
                conjuntos.append([dict(zip(campos, f)) for f in q.fetchall()])
            if not q.nextset():
                break
    finally:
        c.close()
    destino=RAIZ/'outputs/validaciones/reorganizacion_estantes.json'
    destino.parent.mkdir(parents=True,exist_ok=True)
    if len(conjuntos)>1 or not destino.exists():
        destino.write_text(json.dumps(conjuntos,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(conjuntos,ensure_ascii=False,indent=2,default=str))


if __name__ == '__main__':
    reorganizar()
