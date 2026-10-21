from core.formato_numerico import format_numero
pass
import math
import logging
from inventory.tipos_alerta import PROXIMO_AGOTARSE, obtener_tipo_alerta

logger = logging.getLogger('prediccion_stock')

from core.database import conectar


MINIMO_DIAS_PREDICCION = 5
DIAS_ALERTA_AGOTAMIENTO = 7


def obtener_consumo_diario(id_producto,conexion=None):
    propia=conexion is None
    cursor = None

    try:
        conexion = conexion or conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                CAST(m.fecha_movimiento AS date) AS fecha,
                SUM(d.cantidad) AS cantidad

            FROM movimientos AS m

            INNER JOIN tipos_movimiento AS tm
                ON tm.id_tipo_movimiento = m.id_tipo_movimiento

            INNER JOIN detalle_movimientos AS d
                ON d.id_movimiento = m.id_movimiento

            WHERE
                tm.nombre = 'Salida'
                AND d.id_producto = ?
                AND m.fecha_eliminacion IS NULL
                AND d.fecha_eliminacion IS NULL
                AND tm.fecha_eliminacion IS NULL
                AND m.fecha_movimiento <= SYSDATETIME()

            GROUP BY
                CAST(m.fecha_movimiento AS date)

            ORDER BY
                fecha;
        """, id_producto)

        return [
            {
                "fecha": fila.fecha,
                "cantidad": fila.cantidad
            }
            for fila in cursor.fetchall()
        ]

    finally:
        if cursor is not None:
            cursor.close()

        if propia and conexion is not None:
            conexion.close()


def analizar_consumo_producto(id_producto,ventana=None,conexion=None):
    from datetime import timedelta
    from inventory.inventario_service import consultar
    p=consultar('SELECT nombre,stock_actual,stock_minimo FROM vw_inventario WHERE id_producto=? AND estado=1 AND fecha_eliminacion IS NULL',id_producto,conexion=conexion)
    if not p: raise ValueError('El producto no existe o está inactivo.')
    filas=obtener_consumo_diario(id_producto,conexion=conexion)
    c=conexion or conectar()
    try: hoy=c.cursor().execute('SELECT CAST(SYSDATETIME() AS DATE)').fetchone()[0]
    finally:
        if conexion is None:c.close()
    if ventana is not None and ventana not in (7,30,60,90): raise ValueError('Seleccione 7, 30, 60 o 90 días.')
    desde=hoy-timedelta(days=ventana-1) if ventana else None
    reales={f['fecha']:float(f['cantidad']) for f in filas if f['fecha']<=hoy and (desde is None or f['fecha']>=desde)}
    # Incluir días sin salidas evita exagerar el consumo de productos intermitentes.
    inicio=max(min(reales),desde) if reales and desde else min(reales) if reales else hoy
    dias=(hoy-inicio).days+1 if reales else 0
    serie=[{'fecha':inicio+timedelta(days=i),'cantidad':reales.get(inicio+timedelta(days=i),0.0)} for i in range(dias)]
    cantidades=[f['cantidad'] for f in serie]
    return {'producto':p[0]['nombre'],'stock_actual':p[0]['stock_actual'],'stock_minimo':p[0]['stock_minimo'],
            'fecha_analisis':hoy,'ventana':ventana,'dias_analizados':dias,'dias_con_salidas':len(reales),'consumo_diario':serie,
            'consumo_promedio_diario':sum(cantidades)/dias if dias else 0.0,
            'consumo_maximo':max(cantidades,default=0.0),'consumo_minimo':min(cantidades,default=0.0)}

def _actualizar_alerta(id_producto, producto, dias,conexion=None,resolver=False):
    """Actualizar una alerta pendiente sin duplicarla; cálculo y persistencia separados."""
    if not resolver and (dias is None or not math.isfinite(float(dias)) or dias < 0):
        return
    propia=conexion is None
    conexion = conexion or conectar()
    creada=False;resueltas=0
    try:
        cursor = conexion.cursor()
        riesgo = not resolver and 0 < dias <= DIAS_ALERTA_AGOTAMIENTO
        tipo_id = obtener_tipo_alerta(PROXIMO_AGOTARSE, cursor=cursor, obligatorio=riesgo)
        if tipo_id is None:
            return
        cursor.execute("DECLARE @r INT; EXEC @r=sp_getapplock @Resource=?,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; SELECT @r",
                       'InventarioIA_alerta_prediccion_'+str(id_producto))
        if cursor.fetchone()[0] < 0:
            raise RuntimeError('No se pudo bloquear la actualización de la alerta.')
        if riesgo:
            pendiente = cursor.execute("""SELECT TOP 1 id_alerta FROM dbo.alertas WITH(UPDLOCK,HOLDLOCK)
                WHERE id_producto=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL""",
                id_producto, tipo_id).fetchone()
            if pendiente is None:
                mensaje = f'El producto {producto} podría agotarse en aproximadamente {math.ceil(dias)} días.'
                cursor.execute("""INSERT dbo.alertas(id_tipo_alerta,id_producto,mensaje,nivel,atendida,fecha_creacion)
                    VALUES(?,?,?,'Alta',0,SYSDATETIME())""", tipo_id, id_producto, mensaje)
                creada=True
        else:
            cursor.execute("""UPDATE dbo.alertas SET atendida=1,fecha_atencion=SYSDATETIME(),fecha_actualizacion=SYSDATETIME()
                WHERE id_producto=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL""",id_producto,tipo_id)
            resueltas=max(cursor.rowcount,0)
        if propia:
            conexion.commit()
            from core.event_bus import emitir
            if creada or resueltas:
                emitir('ALERTA_CREADA' if creada else 'ALERTA_RESUELTA','ALERTAS','prediccion_stock',
                    'Alerta de predicción actualizada','Actualización de la condición de cobertura.',
                    reference='alerta-prediccion:'+str(id_producto),data={'id_producto':id_producto},metadata={'derivada':True})
    except Exception:
        if propia:conexion.rollback()
        raise
    finally:
        if propia:conexion.close()


def predecir_agotamiento(id_producto,actualizar_alertas=True,dias_objetivo=None,ventana=None,conexion=None,publicar=True):
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from core.config_manager import obtener
    if dias_objetivo is None: dias_objetivo=obtener('prediccion','horizonte')
    if ventana is None: ventana=obtener('prediccion','periodo')
    minimo_historial=obtener('prediccion','minimo_historial')
    if type(dias_objetivo) is not int or not 1<=dias_objetivo<=365: raise ValueError('Horizonte objetivo inválido.')
    opciones_conexion={'conexion':conexion} if conexion is not None else {}
    analisis=analizar_consumo_producto(id_producto,ventana,**opciones_conexion) if ventana else analizar_consumo_producto(id_producto,**opciones_conexion)
    analisis.update(datos_suficientes=False,dias_restantes_promedio=None,dias_restantes_regresion=None,
                    consumo_tendencia=None,pendiente_regresion=None,estado='Datos insuficientes',
                    cantidad_recomendada=None,stock_objetivo=None,dias_objetivo=dias_objetivo,
                    fecha_agotamiento=None,riesgo='SIN DATOS',tendencia='SIN DATOS',
                    metodo='Promedio diario observado; días sin salidas incluidos',explicacion='')
    if analisis['dias_con_salidas']<minimo_historial:
        analisis['mensaje']=f'Datos insuficientes para realizar una predicción confiable (mínimo {minimo_historial} días con salidas).'
        if analisis['consumo_promedio_diario']==0:
            analisis['mensaje']='Sin consumo reciente. '+analisis['mensaje']
        if conexion is None and publicar:
            from core.eventos_servicios import publicar_prediccion
            publicar_prediccion(id_producto,analisis,notificar=actualizar_alertas)
        return analisis
    promedio=analisis['consumo_promedio_diario']; stock=float(analisis['stock_actual'])
    dias=stock/promedio if promedio>0 else None
    cantidades=np.array([f['cantidad'] for f in analisis['consumo_diario']],dtype=float)
    modelo=LinearRegression().fit(np.arange(len(cantidades)).reshape(-1,1),cantidades)
    tendencia=max(float(modelo.predict([[len(cantidades)]])[0]),0.0)
    objetivo=max(float(analisis['stock_minimo']),promedio*dias_objetivo)
    analisis.update(datos_suficientes=True,dias_restantes_promedio=dias,
        dias_restantes_regresion=stock/tendencia if tendencia>0 else None,consumo_tendencia=tendencia,
        pendiente_regresion=float(modelo.coef_[0]),stock_objetivo=objetivo,
        cantidad_recomendada=round(max(objetivo-stock,0),3),
        estado='Próximo a agotarse' if dias is not None and dias<=DIAS_ALERTA_AGOTAMIENTO else 'Sin riesgo próximo',
        mensaje=f'Objetivo basado en {dias_objetivo} días de consumo observado y el stock mínimo. Estimación, no garantía.')
    from datetime import timedelta
    mitad=len(cantidades)//2
    anterior=float(np.mean(cantidades[:mitad])) if mitad else promedio
    reciente=float(np.mean(cantidades[mitad:]))
    cambio=reciente-anterior
    analisis['tendencia']='AUMENTANDO' if cambio>max(anterior*.1,.001) else 'DISMINUYENDO' if cambio<-max(anterior*.1,.001) else 'ESTABLE'
    analisis['riesgo']=calcular_riesgo(stock,float(analisis['stock_minimo']),dias)
    # Nunca producir fechas imposibles para consumos residuales muy pequeños.
    analisis['fecha_agotamiento']=(analisis['fecha_analisis']+timedelta(days=math.ceil(dias))) if dias is not None and stock>0 and dias<36500 else None
    analisis['explicacion']=(f'Stock total {stock:g}; consumo promedio {format_numero(promedio)} por día durante {analisis["dias_analizados"]} días, '
        f'con {analisis["dias_con_salidas"]} días con salidas. Se calcula stock / consumo; las transferencias y entradas no son consumo. '
        'Supone que el consumo se mantiene y no llegan nuevas entradas.')
    analisis['recomendacion']='Considerar reabastecimiento.' if analisis['riesgo'] in ('ALTO','CRÍTICO') else 'Revisar según el plazo real del proveedor.'
    analisis['explicacion']+=f' Stock mínimo registrado: {analisis["stock_minimo"]}. Riesgo {analisis["riesgo"]} según el stock mínimo y la cobertura estimada.'
    if actualizar_alertas and dias is not None:
        try:
            _actualizar_alerta(id_producto,analisis['producto'],dias,**opciones_conexion)
        except Exception:
            logger.warning('No fue posible actualizar la alerta de predicción del producto %s; el cálculo se conserva.',id_producto,exc_info=True)
            analisis['advertencia_alerta']='La predicción se calculó, pero no se pudo actualizar su alerta.'
    if conexion is None and publicar:
        from core.eventos_servicios import publicar_prediccion
        publicar_prediccion(id_producto,analisis,notificar=actualizar_alertas)
    return analisis

def calcular_riesgo(stock,minimo,dias):
    if stock<=0 or (minimo>0 and stock<=minimo/2) or (dias is not None and dias<=3): return 'CRÍTICO'
    if stock<=minimo or (dias is not None and dias<=7): return 'ALTO'
    if dias is not None and dias<=30: return 'MEDIO'
    return 'BAJO'
