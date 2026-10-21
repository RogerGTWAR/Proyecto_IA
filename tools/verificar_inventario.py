"""Conciliación de existencias y validación de servicios del inventario."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import json
from pathlib import Path
from core.database import conectar
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
ZONA=timezone(timedelta(hours=-6))
def filas(q,sql,*args):
    q.execute(sql,*args); columnas=[c[0] for c in q.description]
    return [dict(zip(columnas,r)) for r in q.fetchall()]

def validar_integridad(q,incluir_apertura=False):
    ids=[r[0] for r in q.execute('SELECT id_producto FROM productos ORDER BY id_producto').fetchall()]
    marcas=','.join('?' for _ in ids)
    registros=filas(q,f'''SELECT m.id_movimiento,m.fecha_movimiento,t.nombre tipo,d.* FROM movimientos m
      JOIN tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento
      JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
      WHERE d.id_producto IN ({marcas}) AND m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL
      ORDER BY m.fecha_movimiento,d.id_detalle''',*ids)
    saldos=defaultdict(Decimal); lotes=defaultdict(Decimal); claves_iniciadas=set()
    ahora=q.execute('SELECT SYSDATETIME()').fetchone()[0]
    reubicaciones=[]
    if q.execute("SELECT OBJECT_ID('dbo.respaldo_existencias_estantes','U')").fetchone()[0]:
        reubicaciones=filas(q,'''SELECT id_producto,id_ubicacion,id_ubicacion_nueva,cantidad,fecha_respaldo
            FROM dbo.respaldo_existencias_estantes WHERE fecha_eliminacion IS NULL AND id_ubicacion_nueva IS NOT NULL
            ORDER BY fecha_respaldo,id_existencia''')
    def aplicar_reubicaciones(hasta):
        while reubicaciones and reubicaciones[0]['fecha_respaldo']<=hasta:
            cambio=reubicaciones.pop(0)
            antigua=(cambio['id_producto'],cambio['id_ubicacion'])
            nueva=(cambio['id_producto'],cambio['id_ubicacion_nueva'])
            if saldos.get(antigua,Decimal(0))!=cambio['cantidad']:
                raise ValueError('Saldo distinto del respaldo físico antes de la reorganización.')
            saldos.pop(antigua,None)
            saldos[nueva]+=cambio['cantidad'];claves_iniciadas.add(nueva)
    for r in registros:
        p=r['id_producto']; o=r['id_ubicacion_origen']; dest=r['id_ubicacion_destino']; cantidad=r['cantidad']
        clave=(p,o or dest)
        if r['fecha_movimiento']>ahora: raise ValueError('Existe un movimiento posterior a la fecha actual.')
        aplicar_reubicaciones(r['fecha_movimiento'])
        # El archivo puede comenzar con un saldo existente, anterior al período exportado.
        if clave not in claves_iniciadas:
            saldos[clave]=r['stock_anterior'];claves_iniciadas.add(clave)
        if r['stock_anterior']!=saldos[clave]: raise ValueError('Saldo anterior inconsistente: '+str(r['id_movimiento']))
        if o:
            saldos[p,o]-=cantidad
            if saldos[p,o]<0: raise ValueError('Existencias negativas en el historial.')
        if dest:saldos[p,dest]+=cantidad
        if r['stock_nuevo']!=saldos[clave]: raise ValueError('Saldo posterior inconsistente.')
        for l in filas(q,'SELECT dl.*,l.fecha_ingreso,l.fecha_vencimiento FROM detalle_movimiento_lotes dl JOIN lotes l ON l.id_lote=dl.id_lote WHERE dl.id_detalle=?',r['id_detalle']):
            if r['fecha_movimiento']<l['fecha_ingreso']:raise ValueError('Movimiento anterior al ingreso del lote.')
            if o:
                if l['fecha_vencimiento'] and r['fecha_movimiento'].date()>l['fecha_vencimiento']:raise ValueError('Movimiento posterior al vencimiento del lote.')
                lotes[l['id_lote'],o]-=l['cantidad']
                if lotes[l['id_lote'],o]<0:raise ValueError('Existencias negativas por lote.')
            if dest:lotes[l['id_lote'],dest]+=l['cantidad']
    aplicar_reubicaciones(ahora)
    actual={(r.id_producto,r.id_ubicacion):r.cantidad for r in q.execute(f'SELECT id_producto,id_ubicacion,cantidad FROM existencias WHERE id_producto IN ({marcas}) AND fecha_eliminacion IS NULL',*ids).fetchall()}
    if dict(saldos)!=actual:raise ValueError('El historial y las existencias no coinciden.')
    actual_lotes={(r.id_lote,r.id_ubicacion):r.cantidad for r in q.execute(f'SELECT e.* FROM existencias_lotes e JOIN lotes l ON l.id_lote=e.id_lote WHERE l.id_producto IN ({marcas})',*ids).fetchall()}
    if dict(lotes)!=actual_lotes:raise ValueError('El historial de lotes y sus existencias no coinciden.')
    return len(registros)
from ai.prediction.prediccion_stock import predecir_agotamiento
from integrations.reporting.reportes import TIPOS,obtener_datos_reporte
from ui.dashboard import cargar_datos
from jarvis.agente_inventario import procesar_consulta,reiniciar_contexto

def verificar():
    c=conectar()
    try:
        q=c.cursor();detalles=validar_integridad(q,True)
        productos=filas(q,'SELECT id_producto,codigo,nombre,estado_inventario,stock_actual FROM vw_inventario WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY codigo')
        responsables=filas(q,"SELECT e.codigo_empleado,CONCAT(e.nombres,' ',e.apellidos) nombre,COUNT(*) movimientos FROM empleados e JOIN movimientos m ON m.id_empleado=e.id_empleado GROUP BY e.codigo_empleado,e.nombres,e.apellidos")
        tipos=filas(q,'SELECT t.nombre tipo,COUNT(*) cantidad,MIN(m.fecha_movimiento) desde,MAX(m.fecha_movimiento) hasta FROM tipos_movimiento t JOIN movimientos m ON m.id_tipo_movimiento=t.id_tipo_movimiento GROUP BY t.nombre')
        categorias=filas(q,'SELECT nombre FROM categorias WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY nombre')
        ubicaciones=filas(q,'SELECT codigo_ubicacion,almacen,zona,pasillo,estante,nivel FROM ubicaciones WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY codigo_ubicacion')
        multiples=filas(q,'SELECT p.codigo,COUNT(*) ubicaciones FROM productos p JOIN existencias e ON e.id_producto=p.id_producto WHERE e.cantidad>0 AND e.fecha_eliminacion IS NULL GROUP BY p.codigo HAVING COUNT(*)>1')
        hallazgos=filas(q,'SELECT p.codigo,d.cantidad,a.nivel,a.score,a.motivo FROM anomalias_inventario a JOIN detalle_movimientos d ON d.id_detalle=a.id_detalle JOIN productos p ON p.id_producto=d.id_producto')
        tablas=filas(q,"SELECT name tabla FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo') ORDER BY name")
        cantidades={r['tabla']:q.execute('SELECT COUNT(*) FROM dbo.['+r['tabla']+']').fetchone()[0] for r in tablas}
        c.rollback()
    finally:c.close()
    predicciones={p['codigo']:predecir_agotamiento(p['id_producto'],False)['datos_suficientes'] for p in productos}
    reportes={t:len(obtener_datos_reporte(t)['filas']) for t in TIPOS}
    d=cargar_datos()
    if d['errores']:raise ValueError(str(d['errores']))
    consultas={}
    for pregunta in ('¿Cuántos tornillos quedan?','¿Dónde están los filtros?','¿Qué productos están agotados?','¿Qué productos tienen stock bajo?','¿Qué productos hay en Zona A?','¿Cuál producto puede agotarse primero?','¿Qué movimientos fueron inusuales?'):
        reiniciar_contexto();consultas[pregunta]=procesar_consulta(pregunta,True)['respuesta']
    return {'registros_por_tabla':cantidades,'detalles_conciliados':detalles,'productos':productos,'categorias':categorias,'ubicaciones':ubicaciones,
            'responsables':responsables,'movimientos':tipos,'productos_varias_ubicaciones':multiples,'historial_suficiente':predicciones,
            'hallazgos_calculados':hallazgos,'reportes':reportes,'dashboard':d['kpi'],'consultas_jarvis':consultas}

if __name__=='__main__':
    resultado=verificar();destino=_RAIZ_PROYECTO/'outputs/validaciones/resultado_validacion_inventario.json';destino.parent.mkdir(parents=True,exist_ok=True);destino.write_text(json.dumps(resultado,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in resultado.items() if k in ('registros_por_tabla','detalles_conciliados','historial_suficiente','dashboard','reportes')},ensure_ascii=False,indent=2,default=str))
