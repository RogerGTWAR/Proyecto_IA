"""Aplicar la carga respaldada y ejecutar los motores reales en una sola transacción."""
import argparse
import json
from pathlib import Path
import sys

RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ))
from core.database import conectar
from tools.actualizar_desde_exportacion_sql import respaldar
from tools.verificar_inventario import validar_integridad
from inventory.alertas import verificar_alertas_stock
from ai.prediction.prediccion_stock import predecir_agotamiento
from ai.anomalies.deteccion_anomalias import datos_movimientos,analizar_datos_movimientos,guardar_hallazgos,_insertar_alerta
from inventory.tipos_alerta import obtener_tipo_alerta


def consumir(q):
    grupos=[]
    while True:
        if q.description:
            campos=[c[0] for c in q.description]
            grupos.append([dict(zip(campos,r)) for r in q.fetchall()])
        if not q.nextset():return grupos


def validar(c):
    q=c.cursor()
    detalles=validar_integridad(q)
    q.execute((RAIZ/'sql/verificar_historial_inventario.sql').read_text(encoding='utf-8'))
    grupos=consumir(q)
    controles=next(g[0] for g in grupos if g and 'productos_activos' in g[0])
    if controles['productos_activos']!=24 or controles['ubicaciones_activas']!=12 or controles['posiciones_ocupadas']!=24:
        raise ValueError('La estructura física no coincide.')
    if any(v for k,v in controles.items() if k not in ('productos_activos','ubicaciones_activas','posiciones_ocupadas')):
        raise ValueError('La validación operativa encontró inconsistencias: '+str(controles))
    if any(r['resultado']!='COINCIDE' for r in grupos[0]):raise ValueError('Stock final inconsistente.')
    if q.execute('''SELECT COUNT(*) FROM respaldo_existencias_estantes b JOIN existencias e ON e.id_existencia=b.id_existencia
        WHERE e.cantidad<>b.cantidad OR e.id_ubicacion<>b.id_ubicacion_nueva OR e.posicion<>b.posicion_nueva''').fetchone()[0]:
        raise ValueError('Se alteró el stock o la posición física.')
    return dict(controles=controles,detalles_conciliados=detalles,control_stock=grupos[0],diagnosticos_sql=grupos[1:])


def normalizar(aplicar=False):
    c=conectar()
    try:
        q=c.cursor()
        aplicada=bool(q.execute("SELECT 1 FROM inventario_migraciones WHERE version='007_normalizacion_historial'").fetchone())
        if not aplicar:
            print(json.dumps(validar(c),ensure_ascii=False,indent=2,default=str));return
        if aplicada:
            r=validar(c);c.rollback()
            print('Migración 007 ya aplicada; el historial no se duplicó.')
            print(json.dumps(r['controles'],ensure_ascii=False,indent=2));return
        respaldo=respaldar(c)
        c.autocommit=True
        q=c.cursor();q.execute("EXEC sys.sp_set_session_context @key=N'inventario_respaldo_coherencia',@value=?",respaldo)
        c.autocommit=False
        q=c.cursor()
        if q.execute('SELECT @@TRANCOUNT').fetchone()[0]!=1:raise RuntimeError('No existe la transacción externa esperada.')
        q.execute((RAIZ/'sql/normalizar_historial_inventario.sql').read_text(encoding='utf-8'))
        resultados_carga=consumir(q)
        if q.execute('SELECT @@TRANCOUNT').fetchone()[0]!=1:raise RuntimeError('La carga no conservó su transacción externa.')
        ids=[r[0] for r in q.execute('SELECT id_producto FROM productos WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY id_producto').fetchall()]
        predicciones=[]
        for ident in ids:
            verificar_alertas_stock(ident,conexion=c,cursor=q)
            p=predecir_agotamiento(ident,conexion=c)
            if p.get('advertencia_alerta'):raise RuntimeError(p['advertencia_alerta'])
            predicciones.append(p)
        if sum(p['datos_suficientes'] for p in predicciones)<15:
            raise ValueError('Menos de quince productos cuentan con historial predictivo suficiente.')
        analisis=analizar_datos_movimientos(datos_movimientos(q))
        guardar_hallazgos(analisis['resultados'],q)
        tipo_cantidad=obtener_tipo_alerta('cantidad_inusual',cursor=q)
        for a in analisis['resultados']:
            pendiente=q.execute('SELECT 1 FROM alertas WHERE id_producto=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL',a['id_producto'],tipo_cantidad).fetchone()
            if not pendiente:
                _insertar_alerta(q,'Cantidad inusual',a['id_producto'],a['id_movimiento'],a['id_empleado'],a['id_ubicacion_origen'] or a['id_ubicacion_destino'],
                                'Critica' if a['nivel']=='CRÍTICA' else a['nivel'].title(),a['motivo'][:500])
        resultado=validar(c)
        resultado.update(respaldo_sql=respaldo,migracion='007_normalizacion_historial',predicciones=predicciones,
                         analisis=analisis,resultados_carga=resultados_carga)
        destino=RAIZ/'outputs/validaciones/normalizacion_historial.json'
        resultado['estado']='VALIDADO_ANTES_DE_COMMIT'
        destino.write_text(json.dumps(resultado,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        c.commit()
        resultado['estado']='APLICADO'
        destino.write_text(json.dumps(resultado,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'estado':'APLICADO','migracion':resultado['migracion'],'respaldo':respaldo,
                         'controles':resultado['controles'],'predicciones_suficientes':sum(p['datos_suficientes'] for p in predicciones),
                         'hallazgos_calculados':analisis['anomalias_detectadas']},ensure_ascii=False,indent=2,default=str))
    except Exception:
        c.rollback()
        raise
    finally:c.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar',action='store_true')
    args=parser.parse_args();normalizar(args.aplicar)
