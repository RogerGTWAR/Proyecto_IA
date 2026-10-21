from core.formato_numerico import format_numero
pass
from datetime import datetime

from core.database import conectar
from inventory.tipos_alerta import obtener_tipo_alerta


MINIMO_MOVIMIENTOS_ANALISIS = 10
MINIMO_DATOS_ISOLATION = 30
CONTAMINACION_ISOLATION = 0.05


def _datos_salidas(id_producto=None, cursor=None):
    propio = cursor is None; conexion = conectar() if propio else None
    cursor = conexion.cursor() if propio else cursor
    consulta = """SELECT m.id_movimiento, m.fecha_movimiento, d.id_producto,
                   p.nombre AS producto, CONCAT(e.nombres,' ',e.apellidos) empleado,
                   m.id_empleado, d.id_ubicacion_origen AS id_ubicacion,
                   d.cantidad, d.stock_anterior
                   FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
                   JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
                   JOIN productos p ON p.id_producto=d.id_producto
                   JOIN empleados e ON e.id_empleado=m.id_empleado
                   WHERE tm.nombre='Salida' AND m.fecha_eliminacion IS NULL
                     AND d.fecha_eliminacion IS NULL"""
    parametros = []
    if id_producto is not None: consulta += " AND d.id_producto=?"; parametros.append(id_producto)
    consulta += " ORDER BY m.fecha_movimiento"
    try:
        cursor.execute(consulta, *parametros); columnas = [c[0] for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    finally:
        if propio: cursor.close(); conexion.close()


def evaluar_cantidad_inusual(id_producto, cantidad, cursor=None):
    import numpy as np
    cantidad = float(cantidad); datos = _datos_salidas(id_producto, cursor)
    cantidades = np.array([d["cantidad"] for d in datos], dtype=float)
    resultado = {"es_inusual": False, "cantidad": cantidad, "movimientos_analizados": len(cantidades),
                 "promedio": None, "desviacion": None, "limite_superior": None}
    if len(cantidades) < MINIMO_MOVIMIENTOS_ANALISIS:
        resultado["mensaje"] = "Datos insuficientes para evaluar una cantidad inusual."
        return resultado
    promedio = float(np.mean(cantidades)); desviacion = float(np.std(cantidades))
    limite = promedio + 3 * desviacion
    resultado.update({"promedio": promedio, "desviacion": desviacion,
                      "limite_superior": limite, "es_inusual": cantidad > limite})
    return resultado


def entrenar_modelo_anomalias(cursor=None):
    import pandas as pd
    from sklearn.ensemble import IsolationForest
    datos = _datos_salidas(cursor=cursor)
    if len(datos) < MINIMO_DATOS_ISOLATION:
        return {"modelo": None, "datos": datos,
                "mensaje": "Datos insuficientes para analizar movimientos anormales."}
    caracteristicas = pd.DataFrame([{"cantidad": float(d["cantidad"]),
        "hora": d["fecha_movimiento"].hour, "dia_semana": d["fecha_movimiento"].weekday(),
        "stock_anterior": float(d["stock_anterior"] or 0)} for d in datos])
    modelo = IsolationForest(contamination=CONTAMINACION_ISOLATION, random_state=42)
    modelo.fit(caracteristicas)
    return {"modelo": modelo, "datos": datos, "caracteristicas": caracteristicas}


def evaluar_movimiento_anormal(cantidad, hora_movimiento, dia_semana,
                               stock_anterior, cursor=None):
    import pandas as pd
    entrenamiento = entrenar_modelo_anomalias(cursor)
    if entrenamiento["modelo"] is None:
        return {"es_anormal": False, "resultado_modelo": None,
                "mensaje": entrenamiento["mensaje"]}
    muestra = pd.DataFrame([{"cantidad": float(cantidad), "hora": int(hora_movimiento),
                            "dia_semana": int(dia_semana), "stock_anterior": float(stock_anterior)}])
    resultado = int(entrenamiento["modelo"].predict(muestra)[0])
    return {"es_anormal": resultado == -1, "resultado_modelo": resultado}


def analizar_movimientos_isolation_legacy():
    entrenamiento = entrenar_modelo_anomalias()
    datos = entrenamiento["datos"]
    if entrenamiento["modelo"] is None:
        return {"movimientos_analizados": len(datos), "anomalias_detectadas": 0,
                "resultados": [], "mensaje": entrenamiento["mensaje"]}
    predicciones = entrenamiento["modelo"].predict(entrenamiento["caracteristicas"])
    resultados = []
    for dato, prediccion in zip(datos, predicciones):
        if prediccion == -1:
            resultados.append({"fecha": dato["fecha_movimiento"], "producto": dato["producto"],
                               "empleado": dato["empleado"], "cantidad": dato["cantidad"],
                               "tipo_anomalia": "Movimiento anormal"})
    return {"movimientos_analizados": len(datos), "anomalias_detectadas": len(resultados),
            "resultados": resultados}


def evaluar_salida_para_alertas(cursor, id_movimiento, id_empleado, id_producto,
                                id_ubicacion, cantidad, stock_anterior):
    r=analizar_datos_movimientos(datos_movimientos(cursor))
    actuales=[a for a in r['resultados'] if a['id_movimiento']==id_movimiento and a['id_producto']==id_producto]
    guardar_hallazgos(actuales,cursor)
    for a in actuales:
        _insertar_alerta(cursor,'Cantidad inusual',id_producto,id_movimiento,id_empleado,id_ubicacion,'Critica' if a['nivel']=='CRÍTICA' else a['nivel'].title(),a['motivo'][:500])


def _insertar_alerta(cursor, tipo, producto, movimiento, empleado, ubicacion, nivel, mensaje):
    tipo_id = obtener_tipo_alerta(tipo,cursor=cursor,obligatorio=False)
    if tipo_id is not None:
        cursor.execute("""INSERT INTO alertas(id_tipo_alerta,id_producto,id_movimiento,id_empleado,
                       id_ubicacion,mensaje,nivel,fecha_creacion,atendida)
                       VALUES(?,?,?,?,?,?,?,SYSDATETIME(),0)""", tipo_id, producto, movimiento, empleado, ubicacion, mensaje, nivel)


def datos_movimientos(cursor=None,producto=None,tipo=None,limite=None,id_detalle=None,movimiento=None):
    """Detalles vigentes de entradas, salidas y transferencias; orden temporal real."""
    from core.config_manager import obtener
    propio=cursor is None; c=conectar() if propio else None
    q=c.cursor() if propio else cursor
    try:
        sql='''SELECT d.id_detalle,m.id_movimiento,m.fecha_movimiento fecha,d.id_producto,
            p.nombre producto,d.cantidad,tm.nombre tipo_movimiento,m.id_empleado,
            CONCAT(e.nombres,' ',e.apellidos) empleado,d.id_ubicacion_origen,d.id_ubicacion_destino,
            uo.codigo_ubicacion origen,ud.codigo_ubicacion destino
            FROM detalle_movimientos d JOIN movimientos m ON m.id_movimiento=d.id_movimiento
            JOIN productos p ON p.id_producto=d.id_producto
            JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
            JOIN empleados e ON e.id_empleado=m.id_empleado
            LEFT JOIN ubicaciones uo ON uo.id_ubicacion=d.id_ubicacion_origen
            LEFT JOIN ubicaciones ud ON ud.id_ubicacion=d.id_ubicacion_destino
            WHERE m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL
              AND tm.nombre IN('Entrada','Salida','Transferencia')
              AND m.fecha_movimiento<=SYSDATETIME() AND m.fecha_movimiento>=DATEADD(day,-?,SYSDATETIME())
            '''
        args=[obtener('anomalias','periodo')]
        if producto is not None:sql+=' AND d.id_producto=?';args.append(producto)
        if tipo is not None:sql+=' AND tm.nombre=?';args.append(tipo)
        if movimiento is not None:sql+=' AND m.id_movimiento=?';args.append(movimiento)
        if limite is not None:
            sql+=' AND (m.fecha_movimiento<? OR (m.fecha_movimiento=? AND d.id_detalle<?))';args.extend((limite,limite,id_detalle))
        q.execute(sql+' ORDER BY m.fecha_movimiento,d.id_detalle',*args)
        columnas=[x[0] for x in q.description]
        return [dict(zip(columnas,f)) for f in q.fetchall()]
    finally:
        if propio: q.close(); c.close()

def evaluar_cantidad_nueva(d,historial,cfg):
    from statistics import mean,pstdev
    if len(historial)<cfg['minimo_historial']:return None
    valores=[float(h['cantidad']) for h in historial]; promedio=mean(valores); desv=pstdev(valores)
    cantidad=float(d['cantidad'])
    score=(cantidad-promedio)/desv if desv>0 else cantidad/promedio if promedio>0 else 0
    metrica='Desviaciones estándar sobre el promedio' if desv>0 else 'Razón cantidad / promedio; variación histórica nula'
    if cantidad>promedio and score>=cfg['sensibilidad']:
        nivel='CRÍTICA' if score>=6 else 'ALTA' if score>=4 else 'MEDIA' if score>=3 else 'BAJA'
        motivo=f'{d["tipo_movimiento"]} de {cantidad:g}; promedio previo {format_numero(promedio)}, desviación {format_numero(desv)}, {len(historial)} movimientos del mismo producto y tipo. {metrica}: {format_numero(score)}.'
        return {**d,'tipo_anomalia':'Cantidad inusual','nivel':nivel,'score':score,
            'motivo':motivo,'referencia_historica':f'Promedio: {format_numero(promedio)}; desviación: {format_numero(desv)}; muestras: {len(historial)}; métrica: {metrica}',
            'estado':'PENDIENTE','observacion':''}


def analizar_datos_movimientos(datos,config=None):
    """Comparar cada movimiento solo con su historial previo, sin fuga del candidato."""
    from collections import defaultdict
    from statistics import mean,pstdev
    from core.config_manager import cargar_configuracion
    cfg=config or cargar_configuracion()['anomalias']
    grupos=defaultdict(list); resultados=[]; evaluados=0
    for d in sorted(datos,key=lambda d:(d['fecha'],d['id_detalle'])):
        historial=grupos[(d['id_producto'],d['tipo_movimiento'])]
        if len(historial)>=cfg['minimo_historial']:
            evaluados+=1
            hallazgo=evaluar_cantidad_nueva(d,historial,cfg)
            if hallazgo:resultados.append(hallazgo)
        historial.append(d)
    return {'movimientos_analizados':len(datos),'movimientos_evaluados':evaluados,
            'anomalias_detectadas':len(resultados),'resultados':resultados,
            **({'mensaje':'Datos insuficientes: se necesita historial previo por producto y tipo de movimiento.'} if not evaluados else {})}

def analizar_movimientos(persistir=False):
    r=analizar_datos_movimientos(datos_movimientos())
    from core.system_state import state_manager
    state_manager.update('ANOMALIAS','ONLINE','Motor de anomalías consultado.',
        details={'movimientos_evaluados':r.get('movimientos_evaluados',0)})
    if persistir: guardar_hallazgos(r['resultados'])
    return r


def evaluar_movimiento_incremental(movimiento,producto):
    from core.audit_service import operation, audit
    with operation('ANOMALIAS','ANOMALY_ANALYSIS',entity_type='producto',entity_id=producto,
                   data={'id_movimiento':movimiento}) as record:
        result=_evaluar_movimiento_incremental(movimiento,producto)
        record['data']=dict(id_movimiento=movimiento,analizados=result['movimientos_analizados'],
                            hallazgos=result['anomalias_detectadas'])
        audit.record('ANOMALIAS','ANOMALOUS' if result['anomalias_detectadas'] else 'NORMAL',
                     level='INFO' if result['anomalias_detectadas'] else 'DEBUG',data=record['data'])
        return result

def _evaluar_movimiento_incremental(movimiento,producto):
    """Solo el candidato y el historial anterior de su producto/tipo/ventana."""
    from core.config_manager import cargar_configuracion
    candidatos=datos_movimientos(producto=producto,movimiento=movimiento)
    hallazgos=[]
    for candidato in candidatos:
        historial=datos_movimientos(producto=producto,tipo=candidato['tipo_movimiento'],
            limite=candidato['fecha'],id_detalle=candidato['id_detalle'])
        hallazgo=evaluar_cantidad_nueva(candidato,historial,cargar_configuracion()['anomalias'])
        if hallazgo:hallazgos.append(hallazgo)
    guardar_hallazgos(hallazgos)
    from core.system_state import state_manager
    state_manager.update('ANOMALIAS','ONLINE','Movimiento evaluado de forma incremental.')
    return {'movimientos_analizados':len(candidatos),'anomalias_detectadas':len(hallazgos),'resultados':hallazgos}

def guardar_hallazgos(filas,cursor=None):
    from core.event_bus import _outbox,confirmar_eventos
    from core.eventos_servicios import publicar_anomalia
    propio=cursor is None
    c=conectar() if propio else None
    pendientes=[];token=_outbox.set(pendientes) if propio else None
    try:
        q=c.cursor() if propio else cursor
        for a in filas:
            q.execute('''IF NOT EXISTS(SELECT 1 FROM anomalias_inventario WITH(UPDLOCK,HOLDLOCK) WHERE id_detalle=? AND tipo_anomalia=?)
                BEGIN INSERT anomalias_inventario(id_detalle,tipo_anomalia,nivel,score,motivo,referencia_historica)
                OUTPUT INSERTED.id_anomalia VALUES(?,?,?,?,?,?) END ELSE SELECT CAST(NULL AS INT)''',
                a['id_detalle'],a['tipo_anomalia'],a['id_detalle'],a['tipo_anomalia'],a['nivel'],a['score'],a['motivo'],a['referencia_historica'])
            creada=q.fetchone()
            if creada and creada[0] is not None and _outbox.get() is not None:
                publicar_anomalia(dict(a,id_anomalia=int(creada[0])))
        if propio: c.commit()
    except Exception:
        if propio: c.rollback()
        raise
    finally:
        if propio:
            _outbox.reset(token)
            c.close()
    if propio: confirmar_eventos(pendientes)

def listar_anomalias(fecha_desde=None,fecha_hasta=None,producto=None,tipo=None,nivel=None,movimiento=None):
    from inventory.inventario_service import consultar
    from datetime import date
    condiciones=['m.fecha_eliminacion IS NULL','d.fecha_eliminacion IS NULL']; args=[]
    for f in (fecha_desde,fecha_hasta):
        if f: date.fromisoformat(f)
    if fecha_desde and fecha_hasta and fecha_desde>fecha_hasta: raise ValueError('Rango de fechas inválido.')
    if fecha_desde: condiciones.append('m.fecha_movimiento>=?'); args.append(fecha_desde)
    if fecha_hasta: condiciones.append('m.fecha_movimiento<DATEADD(day,1,CAST(? AS date))'); args.append(fecha_hasta)
    for campo,v in [('d.id_producto',producto),('a.tipo_anomalia',tipo),('a.nivel',nivel),('tm.nombre',movimiento)]:
        if v and v!='Todos': condiciones.append(campo+'=?'); args.append(v)
    return consultar('''SELECT a.*,m.fecha_movimiento fecha,m.id_movimiento,m.id_empleado,d.id_producto,p.nombre producto,p.codigo codigo,
        CONCAT(e.nombres,' ',e.apellidos) empleado,tm.nombre tipo_movimiento,d.cantidad,d.stock_anterior,d.stock_nuevo,
        uo.codigo_ubicacion origen,ud.codigo_ubicacion destino FROM anomalias_inventario a
        JOIN detalle_movimientos d ON d.id_detalle=a.id_detalle JOIN movimientos m ON m.id_movimiento=d.id_movimiento
        JOIN productos p ON p.id_producto=d.id_producto JOIN empleados e ON e.id_empleado=m.id_empleado
        JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
        LEFT JOIN ubicaciones uo ON uo.id_ubicacion=d.id_ubicacion_origen LEFT JOIN ubicaciones ud ON ud.id_ubicacion=d.id_ubicacion_destino
        WHERE '''+' AND '.join(condiciones)+' ORDER BY m.fecha_movimiento DESC,a.id_anomalia DESC',*args)

def cambiar_estado_anomalia(id_anomalia,estado,observacion=''):
    if estado not in ('PENDIENTE','REVISADA','JUSTIFICADA'): raise ValueError('Estado inválido.')
    if len(observacion)>1000: raise ValueError('Observación demasiado larga.')
    if estado=='JUSTIFICADA' and not observacion.strip(): raise ValueError('Describa la justificación.')
    c=conectar()
    try:
        q=c.cursor().execute('UPDATE anomalias_inventario SET estado=?,observacion=? WHERE id_anomalia=?',estado,observacion,id_anomalia)
        if q.rowcount!=1: raise ValueError('Anomalía no encontrada.')
        c.commit()
        if estado != 'PENDIENTE':
            from core.event_bus import emitir
            emitir('ANOMALIA_RESUELTA','ANOMALIAS','deteccion_anomalias','Anomalía revisada',
                   estado,reference='anomalia-resuelta:'+str(id_anomalia),data={'id_anomalia':id_anomalia,'estado':estado})
    except Exception: c.rollback(); raise
    finally: c.close()

def consultar_anomalias(incluir_analisis=False,**filtros):
    """Leer hallazgos existentes sin ejecutar ni persistir un análisis histórico."""
    from core.automatizacion_inventario import automatizacion
    analisis=automatizacion.ultima_evaluacion or {}
    filas=listar_anomalias(**filtros)
    return {'filas':filas,'analisis':analisis} if incluir_analisis else filas
