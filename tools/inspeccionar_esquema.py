"""Inventario de metadatos SQL y cantidades; no modifica la base."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import json
from pathlib import Path
from core.database import conectar

def inspeccionar(c):
    q=c.cursor()
    def filas(sql):
        q.execute(sql); nombres=[d[0] for d in q.description]
        return [dict(zip(nombres,r)) for r in q.fetchall()]
    datos={
      'columnas':filas("""SELECT s.name esquema,t.name tabla,c.name columna,ty.name tipo,
        c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity,dc.definition valor_default
        FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
        JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id
        LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id ORDER BY t.name,c.column_id"""),
      'indices':filas("""SELECT t.name tabla,i.name indice,i.is_primary_key,i.is_unique,c.name columna,ic.key_ordinal,i.filter_definition
        FROM sys.tables t JOIN sys.indexes i ON i.object_id=t.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.is_unique=1 ORDER BY t.name,i.name,ic.key_ordinal"""),
      'foraneas':filas("""SELECT fk.name restriccion,t.name tabla,c.name columna,rt.name referencia_tabla,rc.name referencia_columna
        FROM sys.foreign_keys fk JOIN sys.foreign_key_columns f ON f.constraint_object_id=fk.object_id
        JOIN sys.tables t ON t.object_id=f.parent_object_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=f.parent_column_id
        JOIN sys.tables rt ON rt.object_id=f.referenced_object_id JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=f.referenced_column_id"""),
      'checks':filas('SELECT OBJECT_NAME(parent_object_id) tabla,name,definition FROM sys.check_constraints'),
      'registros':{},
      'productos':filas('SELECT id_producto,codigo,nombre,stock_actual FROM vw_inventario'),
      'empleados':filas('SELECT id_empleado,codigo_empleado,nombres,apellidos,estado FROM empleados'),
      'ubicaciones':filas('SELECT * FROM ubicaciones'),
      'categorias':filas('SELECT * FROM categorias'),
      'unidades':filas('SELECT * FROM unidades_medida'),
      'tipos_movimiento':filas('SELECT * FROM tipos_movimiento')}
    for r in filas("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')"):
        nombre=r['name']; datos['registros'][nombre]=q.execute('SELECT COUNT(*) FROM dbo.['+nombre.replace(']',']]')+']').fetchone()[0]
    return datos

if __name__=='__main__':
    c=conectar()
    try: datos=inspeccionar(c)
    finally: c.close()
    salida=_RAIZ_PROYECTO/'outputs/validaciones/esquema_inventario.json'; salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps(datos,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(datos['registros'],ensure_ascii=False,indent=2))
