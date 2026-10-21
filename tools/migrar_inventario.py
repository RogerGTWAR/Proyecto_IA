"""Migración aditiva de inventario; GO se ejecuta en una sola transacción."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import re
from pathlib import Path
from core.database import conectar

def migrar():
    c=conectar()
    try:
        q=c.cursor()
        sql=_RAIZ_PROYECTO.joinpath('migrations/004_mejoras_inventario.sql').read_text(encoding='utf-8')
        for lote in re.split(r'^GO\s*$',sql,flags=re.M|re.I):
            if lote.strip():
                q.execute(lote)
                while q.nextset(): pass
        c.commit()
        print('Migración 004 aplicada sin eliminar datos.')
    except Exception:
        c.rollback()
        raise
    finally: c.close()

if __name__=='__main__': migrar()
