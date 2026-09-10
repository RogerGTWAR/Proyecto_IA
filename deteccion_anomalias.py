from datetime import datetime

from database import conectar


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
    cantidad = int(cantidad); datos = _datos_salidas(id_producto, cursor)
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
    caracteristicas = pd.DataFrame([{"cantidad": d["cantidad"],
        "hora": d["fecha_movimiento"].hour, "dia_semana": d["fecha_movimiento"].weekday(),
        "stock_anterior": d["stock_anterior"] or 0} for d in datos])
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
    muestra = pd.DataFrame([{"cantidad": int(cantidad), "hora": int(hora_movimiento),
                            "dia_semana": int(dia_semana), "stock_anterior": int(stock_anterior)}])
    resultado = int(entrenamiento["modelo"].predict(muestra)[0])
    return {"es_anormal": resultado == -1, "resultado_modelo": resultado}


def analizar_movimientos():
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
    cursor.execute("SELECT nombre FROM productos WHERE id_producto=? AND fecha_eliminacion IS NULL", id_producto)
    producto = cursor.fetchone().nombre; ahora = datetime.now()
    cantidad_resultado = evaluar_cantidad_inusual(id_producto, cantidad, cursor)
    if cantidad_resultado["es_inusual"]:
        _insertar_alerta(cursor, "Cantidad inusual", id_producto, id_movimiento, id_empleado,
            id_ubicacion, "Alta", f"Se registró una salida de {cantidad} unidades de {producto}, superior al comportamiento habitual.")
    movimiento = evaluar_movimiento_anormal(cantidad, ahora.hour, ahora.weekday(), stock_anterior, cursor)
    if movimiento["es_anormal"]:
        _insertar_alerta(cursor, "Movimiento anormal", id_producto, id_movimiento, id_empleado,
            id_ubicacion, "Alta", f"Se detectó un movimiento fuera del comportamiento habitual para el producto {producto}.")


def _insertar_alerta(cursor, tipo, producto, movimiento, empleado, ubicacion, nivel, mensaje):
    cursor.execute("""SELECT id_tipo_alerta FROM tipos_alerta WHERE nombre=? AND estado=1
                      AND fecha_eliminacion IS NULL""", tipo)
    fila = cursor.fetchone()
    if fila:
        cursor.execute("""INSERT INTO alertas(id_tipo_alerta,id_producto,id_movimiento,id_empleado,
                       id_ubicacion,mensaje,nivel,fecha_generacion,atendida)
                       VALUES(?,?,?,?,?,?,?,SYSDATETIME(),0)""", fila.id_tipo_alerta, producto, movimiento, empleado, ubicacion, mensaje, nivel)
