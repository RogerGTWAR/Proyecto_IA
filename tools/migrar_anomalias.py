"""Migración aditiva 005. No crea cuentas ni elimina información."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from pathlib import Path
from core.database import conectar
def migrar():
    c=conectar()
    try:
        c.cursor().execute((_RAIZ_PROYECTO/'migrations/005_anomalias_funcionales.sql').read_text(encoding='utf-8'))
        c.commit()
    except Exception: c.rollback(); raise
    finally: c.close()
if __name__=='__main__': migrar(); print('Migración 005 aplicada.')
