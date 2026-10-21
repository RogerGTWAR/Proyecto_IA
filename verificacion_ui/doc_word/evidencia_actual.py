import sys, json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from database import conectar
from inspeccionar_esquema_demo import inspeccionar
base=Path(__file__).resolve().parent
c=conectar()
try:
    datos=inspeccionar(c); q=c.cursor()
    def query(sql):
        q.execute(sql); names=[d[0] for d in q.description]
        return [dict(zip(names,r)) for r in q.fetchall()]
    datos['resumen_movimientos']=query('SELECT tm.nombre tipo,COUNT(*) cantidad FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento GROUP BY tm.nombre')
    datos['periodo']=query('SELECT MIN(fecha_movimiento) primera,MAX(fecha_movimiento) ultima FROM movimientos')
    datos['calidad']={}
    tests={
      'existencias_negativas':'SELECT COUNT(*) FROM existencias WHERE cantidad<0',
      'codigos_producto_duplicados':'SELECT COUNT(*) FROM (SELECT codigo FROM productos GROUP BY codigo HAVING COUNT(*)>1) x',
      'pares_existencia_duplicados':'SELECT COUNT(*) FROM (SELECT id_producto,id_ubicacion FROM existencias GROUP BY id_producto,id_ubicacion HAVING COUNT(*)>1) x',
      'movimientos_futuros':'SELECT COUNT(*) FROM movimientos WHERE fecha_movimiento>SYSDATETIME()',
      'movimientos_sin_empleado':'SELECT COUNT(*) FROM movimientos WHERE id_empleado IS NULL',
      'cantidades_no_positivas':'SELECT COUNT(*) FROM detalle_movimientos WHERE cantidad<=0',
      'alertas_pendientes':'SELECT COUNT(*) FROM alertas WHERE atendida=0 AND fecha_eliminacion IS NULL',
    }
    for key,sql in tests.items(): datos['calidad'][key]=q.execute(sql).fetchone()[0]
    datos['nulos']={}
    for tabla,col in [('productos','codigo_barras'),('productos','codigo_qr'),('productos','imagen'),('ubicaciones','almacen'),('ubicaciones','zona')]:
        if any(x['tabla']==tabla and x['columna']==col for x in datos['columnas']):
            datos['nulos'][tabla+'.'+col]=q.execute(f'SELECT COUNT(*) FROM dbo.[{tabla}] WHERE [{col}] IS NULL').fetchone()[0]
    datos['integridad_foranea']=[]
    for f in datos['foraneas']:
        sql=f"SELECT COUNT(*) FROM [{f['tabla']}] p LEFT JOIN [{f['referencia_tabla']}] r ON p.[{f['columna']}]=r.[{f['referencia_columna']}] WHERE p.[{f['columna']}] IS NOT NULL AND r.[{f['referencia_columna']}] IS NULL"
        datos['integridad_foranea'].append({'relacion':f['restriccion'],'huerfanos':q.execute(sql).fetchone()[0]})
finally: c.close()
datos['calibracion_existe']=(base.parents[1]/'modelos/facial_embeddings/calibracion.json').exists()
(base/'evidencia_sql.json').write_text(json.dumps(datos,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps({k:datos[k] for k in ['registros','resumen_movimientos','periodo','calidad','nulos','calibracion_existe']},ensure_ascii=False,default=str))
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
for name in ('Primer Entregable IA 1.0.docx','Borrador del segundo entregable (1) (1).docx'):
    with ZipFile(Path('C:/Users/rpere/Downloads')/name) as z:
        for n in z.namelist():
            if n.startswith(('word/header','word/footer')) and n.endswith('.xml'):
                t=' '.join(e.text or '' for e in ET.fromstring(z.read(n)).findall('.//w:t',ns))
                print(name,n,t)
