"""Aplica fechas de eventos nuevos; no envía notificaciones ni modifica históricos."""
import sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from core.database import conectar


def migrar():
    c=conectar()
    try:
        q=c.cursor()
        for nombre in ('008_notificaciones_telegram.sql','010_fecha_eventos_telegram.sql'):
            q.execute((BASE/'migrations'/nombre).read_text(encoding='utf-8'))
            while q.nextset():pass
        c.commit()
        print('Notificaciones y fecha de detección preparadas. Históricos conservados; ningún mensaje enviado.')
    except Exception:c.rollback();raise
    finally:c.close()


if __name__=='__main__':migrar()
