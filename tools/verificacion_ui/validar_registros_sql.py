"""Comprobar la carga SQL con reversión de la transacción."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.database import conectar

base = Path(__file__).resolve().parents[2]
sql = (base / 'sql' / 'registros_inventario.sql').read_text(encoding='utf-8-sig')
if sql.count('    COMMIT TRANSACTION;') != 1:
    raise ValueError('No se encontró el cierre esperado de la transacción.')
sql = sql.replace('    COMMIT TRANSACTION;', '    ROLLBACK TRANSACTION;')
c = conectar()
try:
    q = c.cursor()
    q.execute(sql)
    while q.description is None:
        if not q.nextset():
            raise ValueError('No se obtuvo el resultado de la carga.')
    r = q.fetchone()
    if r[0] != 0:
        raise ValueError('La base actual difiere de los registros exportados.')
    print('SQL ejecutado con reversión: cero registros duplicados y ninguna modificación guardada.')
finally:
    c.rollback()
    c.close()
