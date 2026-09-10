from datetime import date

from alertas import verificar_alertas_stock
from database import conectar
from deteccion_anomalias import evaluar_salida_para_alertas


def _filas_a_diccionarios(cursor, filas):
    columnas = [columna[0] for columna in cursor.description]
    return [dict(zip(columnas, fila)) for fila in filas]


def _validar_entero_positivo(valor, nombre):
    try:
        valor = int(valor)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{nombre} debe ser un número entero.") from error
    if valor <= 0:
        raise ValueError(f"{nombre} debe ser mayor que cero.")
    return valor


def _validar_entidades(cursor, id_empleado, id_producto, ids_ubicaciones):
    cursor.execute("SELECT estado FROM empleados WHERE id_empleado=? AND fecha_eliminacion IS NULL;", id_empleado)
    empleado = cursor.fetchone()
    if empleado is None:
        raise ValueError("El empleado no existe.")
    if not empleado.estado:
        raise ValueError("El empleado seleccionado está inactivo.")
    cursor.execute("SELECT estado FROM productos WHERE id_producto=? AND fecha_eliminacion IS NULL;", id_producto)
    producto = cursor.fetchone()
    if producto is None:
        raise ValueError("El producto no existe.")
    if not producto.estado:
        raise ValueError("El producto seleccionado está inactivo.")
    for id_ubicacion in ids_ubicaciones:
        cursor.execute("SELECT estado FROM ubicaciones WHERE id_ubicacion=? AND fecha_eliminacion IS NULL;", id_ubicacion)
        ubicacion = cursor.fetchone()
        if ubicacion is None:
            raise ValueError("La ubicación seleccionada no existe.")
        if not ubicacion.estado:
            raise ValueError("La ubicación seleccionada está inactiva.")


def _crear_movimiento(cursor, id_empleado, tipo, observacion):
    cursor.execute("""
        SELECT id_tipo_movimiento FROM tipos_movimiento
        WHERE nombre = ? AND estado = 1 AND fecha_eliminacion IS NULL;
    """, tipo)
    fila = cursor.fetchone()
    if fila is None:
        raise ValueError(f"El tipo de movimiento '{tipo}' no existe o está inactivo.")
    cursor.execute("""
        INSERT INTO movimientos
            (id_empleado, id_tipo_movimiento, fecha_movimiento, observacion, fecha_creacion)
        OUTPUT INSERTED.id_movimiento
        VALUES (?, ?, SYSDATETIME(), ?, SYSDATETIME());
    """, id_empleado, fila.id_tipo_movimiento, observacion or None)
    return cursor.fetchone().id_movimiento


def _guardar_detalle(cursor, id_movimiento, id_producto, cantidad, origen,
                     destino, anterior, nuevo):
    cursor.execute("""
        INSERT INTO detalle_movimientos
            (id_movimiento, id_producto, cantidad, id_ubicacion_origen,
             id_ubicacion_destino, stock_anterior, stock_nuevo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, SYSDATETIME());
    """, id_movimiento, id_producto, cantidad, origen, destino, anterior, nuevo)


def registrar_entrada(id_empleado, id_producto, id_ubicacion_destino, cantidad, observacion=""):
    cantidad = _validar_entero_positivo(cantidad, "La cantidad")
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        _validar_entidades(cursor, id_empleado, id_producto, [id_ubicacion_destino])
        cursor.execute("""
            SELECT cantidad FROM existencias WITH (UPDLOCK, HOLDLOCK)
            WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;
        """, id_producto, id_ubicacion_destino)
        existencia = cursor.fetchone()
        anterior = existencia.cantidad if existencia else 0
        nuevo = anterior + cantidad
        if existencia:
            cursor.execute("""UPDATE existencias SET cantidad = ?, fecha_actualizacion = SYSDATETIME()
                               WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", nuevo, id_producto, id_ubicacion_destino)
        else:
            cursor.execute("""INSERT INTO existencias
                               (id_producto, id_ubicacion, cantidad, fecha_creacion, fecha_actualizacion)
                               VALUES (?, ?, ?, SYSDATETIME(), SYSDATETIME());""", id_producto, id_ubicacion_destino, nuevo)
        id_movimiento = _crear_movimiento(cursor, id_empleado, "Entrada", observacion)
        _guardar_detalle(cursor, id_movimiento, id_producto, cantidad, None,
                         id_ubicacion_destino, anterior, nuevo)
        verificar_alertas_stock(id_producto, conexion, cursor)
        conexion.commit()
        return id_movimiento
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.close()
        conexion.close()


def registrar_salida(id_empleado, id_producto, id_ubicacion_origen, cantidad, observacion=""):
    cantidad = _validar_entero_positivo(cantidad, "La cantidad")
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        _validar_entidades(cursor, id_empleado, id_producto, [id_ubicacion_origen])
        cursor.execute("""SELECT cantidad FROM existencias WITH (UPDLOCK, HOLDLOCK)
                           WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", id_producto, id_ubicacion_origen)
        existencia = cursor.fetchone()
        if existencia is None:
            raise ValueError("No existe stock de este producto en la ubicación seleccionada.")
        anterior = existencia.cantidad
        if cantidad > anterior:
            raise ValueError(f"Stock insuficiente. Disponible: {anterior} unidades.")
        nuevo = anterior - cantidad
        cursor.execute("""UPDATE existencias SET cantidad = ?, fecha_actualizacion = SYSDATETIME()
                           WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", nuevo, id_producto, id_ubicacion_origen)
        id_movimiento = _crear_movimiento(cursor, id_empleado, "Salida", observacion)
        _guardar_detalle(cursor, id_movimiento, id_producto, cantidad,
                         id_ubicacion_origen, None, anterior, nuevo)
        evaluar_salida_para_alertas(cursor, id_movimiento, id_empleado, id_producto,
                                    id_ubicacion_origen, cantidad, anterior)
        verificar_alertas_stock(id_producto, conexion, cursor)
        conexion.commit()
        return id_movimiento
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.close()
        conexion.close()


def registrar_transferencia(id_empleado, id_producto, id_ubicacion_origen,
                            id_ubicacion_destino, cantidad, observacion=""):
    cantidad = _validar_entero_positivo(cantidad, "La cantidad")
    if int(id_ubicacion_origen) == int(id_ubicacion_destino):
        raise ValueError("La ubicación origen y destino no pueden ser iguales.")
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        _validar_entidades(cursor, id_empleado, id_producto,
                           [id_ubicacion_origen, id_ubicacion_destino])
        cursor.execute("""SELECT cantidad FROM existencias WITH (UPDLOCK, HOLDLOCK)
                           WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", id_producto, id_ubicacion_origen)
        origen = cursor.fetchone()
        if origen is None:
            raise ValueError("No existe stock de este producto en la ubicación seleccionada.")
        anterior = origen.cantidad
        if cantidad > anterior:
            raise ValueError(f"Stock insuficiente. Disponible: {anterior} unidades.")
        nuevo = anterior - cantidad
        cursor.execute("""UPDATE existencias SET cantidad = ?, fecha_actualizacion = SYSDATETIME()
                           WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", nuevo, id_producto, id_ubicacion_origen)
        cursor.execute("""SELECT cantidad FROM existencias WITH (UPDLOCK, HOLDLOCK)
                           WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", id_producto, id_ubicacion_destino)
        destino = cursor.fetchone()
        if destino:
            cursor.execute("""UPDATE existencias SET cantidad = ?, fecha_actualizacion = SYSDATETIME()
                               WHERE id_producto = ? AND id_ubicacion = ? AND fecha_eliminacion IS NULL;""", destino.cantidad + cantidad, id_producto, id_ubicacion_destino)
        else:
            cursor.execute("""INSERT INTO existencias
                               (id_producto, id_ubicacion, cantidad, fecha_creacion, fecha_actualizacion)
                               VALUES (?, ?, ?, SYSDATETIME(), SYSDATETIME());""", id_producto, id_ubicacion_destino, cantidad)
        id_movimiento = _crear_movimiento(cursor, id_empleado, "Transferencia", observacion)
        _guardar_detalle(cursor, id_movimiento, id_producto, cantidad,
                         id_ubicacion_origen, id_ubicacion_destino, anterior, nuevo)
        verificar_alertas_stock(id_producto, conexion, cursor)
        conexion.commit()
        return id_movimiento
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.close()
        conexion.close()


def listar_empleados_activos():
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT id_empleado, codigo_empleado, nombres, apellidos
                           FROM empleados WHERE estado=1 AND fecha_eliminacion IS NULL
                           ORDER BY nombres, apellidos;""")
        return _filas_a_diccionarios(cursor, cursor.fetchall())
    finally:
        cursor.close()
        conexion.close()


def buscar_movimientos(texto=None, tipo_movimiento=None, fecha_desde=None, fecha_hasta=None):
    condiciones = []
    parametros = []
    if texto and texto.strip():
        patron = f"%{texto.strip()}%"
        condiciones.append("(p.codigo LIKE ? OR p.nombre LIKE ? OR e.codigo_empleado LIKE ? OR CONCAT(e.nombres, ' ', e.apellidos) LIKE ?)")
        parametros.extend([patron] * 4)
    if tipo_movimiento and tipo_movimiento != "Todos":
        condiciones.append("tm.nombre = ?")
        parametros.append(tipo_movimiento)
    for valor, etiqueta in ((fecha_desde, "Fecha desde"), (fecha_hasta, "Fecha hasta")):
        if valor:
            try:
                date.fromisoformat(valor)
            except ValueError as error:
                raise ValueError(f"{etiqueta} debe usar el formato YYYY-MM-DD.") from error
    if fecha_desde:
        condiciones.append("m.fecha_movimiento >= ?")
        parametros.append(fecha_desde)
    if fecha_hasta:
        condiciones.append("m.fecha_movimiento < DATEADD(day, 1, CAST(? AS date))")
        parametros.append(fecha_hasta)
    consulta = """
        SELECT m.id_movimiento, m.fecha_movimiento, tm.nombre AS tipo_movimiento,
               CONCAT(e.codigo_empleado, ' - ', e.nombres, ' ', e.apellidos) AS empleado,
               p.codigo AS codigo_producto, p.nombre AS producto, d.cantidad,
               uo.codigo_ubicacion AS ubicacion_origen,
               ud.codigo_ubicacion AS ubicacion_destino,
               d.stock_anterior, d.stock_nuevo, m.observacion
        FROM movimientos AS m
        INNER JOIN tipos_movimiento AS tm ON tm.id_tipo_movimiento = m.id_tipo_movimiento
        INNER JOIN empleados AS e ON e.id_empleado = m.id_empleado
        INNER JOIN detalle_movimientos AS d ON d.id_movimiento = m.id_movimiento
        INNER JOIN productos AS p ON p.id_producto = d.id_producto
        LEFT JOIN ubicaciones AS uo ON uo.id_ubicacion = d.id_ubicacion_origen
        LEFT JOIN ubicaciones AS ud ON ud.id_ubicacion = d.id_ubicacion_destino
    """
    condiciones.insert(0, "m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL")
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY m.fecha_movimiento DESC, m.id_movimiento DESC;"
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        cursor.execute(consulta, *parametros)
        return _filas_a_diccionarios(cursor, cursor.fetchall())
    finally:
        cursor.close()
        conexion.close()


def obtener_historial_movimientos():
    return buscar_movimientos()


def actualizar_observacion_movimiento(id_movimiento, observacion):
    """Edita solo información administrativa; nunca altera cantidad ni stock."""
    conexion=conectar(); cursor=conexion.cursor()
    try:
        cursor.execute("""UPDATE movimientos SET observacion=?,fecha_actualizacion=SYSDATETIME()
                          WHERE id_movimiento=? AND fecha_eliminacion IS NULL;""", observacion.strip() or None, id_movimiento)
        if cursor.rowcount==0: raise ValueError("El movimiento no existe.")
        conexion.commit(); return True
    except Exception: conexion.rollback(); raise
    finally: cursor.close(); conexion.close()
