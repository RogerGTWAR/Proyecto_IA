"""Movimientos atómicos sobre existencias, con cantidades decimales y lotes opcionales."""
from datetime import date
from decimal import Decimal
from core.database import conectar
from inventory.inventario_service import decimal_inventario
from inventory.alertas import verificar_alertas_stock
from ai.anomalies.deteccion_anomalias import evaluar_salida_para_alertas
from inventory.organizacion_fisica import asegurar_espacio

def _filas_a_diccionarios(cursor,filas):
    return [dict(zip([x[0] for x in cursor.description],r)) for r in filas]

def _bloquear_producto(q,id_producto):
    q.execute("DECLARE @r INT; EXEC @r=sp_getapplock @Resource=?,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; SELECT @r",'InventarioIA_stock_'+str(id_producto))
    if q.fetchone()[0]<0: raise RuntimeError('No se pudo bloquear el stock. Intente nuevamente.')

def _validar_entidades(q,empleado,producto,ubicaciones):
    if not q.execute('SELECT 1 FROM empleados WHERE id_empleado=? AND estado=1 AND fecha_eliminacion IS NULL',empleado).fetchone(): raise ValueError('Empleado inválido o inactivo.')
    p=q.execute('SELECT control_lotes FROM productos WITH(UPDLOCK,HOLDLOCK) WHERE id_producto=? AND estado=1 AND fecha_eliminacion IS NULL',producto).fetchone()
    if not p: raise ValueError('Producto inválido o inactivo.')
    for u in ubicaciones:
        if not q.execute('SELECT 1 FROM ubicaciones WITH(HOLDLOCK) WHERE id_ubicacion=? AND estado=1 AND fecha_eliminacion IS NULL',u).fetchone(): raise ValueError('Ubicación inválida o inactiva.')
    return bool(p[0])

def _saldo(q,p,u):
    r=q.execute('SELECT cantidad FROM existencias WITH(UPDLOCK,HOLDLOCK) WHERE id_producto=? AND id_ubicacion=? AND fecha_eliminacion IS NULL',p,u).fetchone()
    return Decimal(r[0]) if r else Decimal(0)

def _poner_saldo(q,p,u,cantidad):
    posicion=asegurar_espacio(q,p,u)
    q.execute('UPDATE existencias SET cantidad=?,fecha_actualizacion=SYSDATETIME() WHERE id_producto=? AND id_ubicacion=? AND fecha_eliminacion IS NULL',cantidad,p,u)
    if not q.rowcount: q.execute('INSERT existencias(id_producto,id_ubicacion,cantidad,posicion,fecha_creacion,fecha_actualizacion) VALUES(?,?,?,?,SYSDATETIME(),SYSDATETIME())',p,u,cantidad,posicion)

def _saldo_lote(q,l,u):
    r=q.execute('SELECT cantidad FROM existencias_lotes WITH(UPDLOCK,HOLDLOCK) WHERE id_lote=? AND id_ubicacion=?',l,u).fetchone()
    return Decimal(r[0]) if r else Decimal(0)

def _poner_lote(q,l,u,cantidad):
    q.execute('UPDATE existencias_lotes SET cantidad=? WHERE id_lote=? AND id_ubicacion=?',cantidad,l,u)
    if not q.rowcount: q.execute('INSERT existencias_lotes(id_lote,id_ubicacion,cantidad) VALUES(?,?,?)',l,u,cantidad)

def _comprobar_lotes(q,p,ubicaciones):
    for u in ubicaciones:
        total=q.execute('SELECT COALESCE(SUM(e.cantidad),0) FROM existencias_lotes e JOIN lotes l ON l.id_lote=e.id_lote WHERE l.id_producto=? AND e.id_ubicacion=?',p,u).fetchone()[0]
        if total!=_saldo(q,p,u):
            raise ValueError('El stock de lotes no coincide con la ubicación. Revise la asignación de lotes antes de registrar movimientos.')

def _crear_lote(q,p,codigo,vencimiento,id_lote):
    if id_lote:
        r=q.execute('SELECT id_lote FROM lotes WHERE id_lote=? AND id_producto=? AND activo=1',id_lote,p).fetchone()
        if not r: raise ValueError('Lote inválido para este producto.')
        return id_lote
    codigo=(codigo or '').strip()
    if not codigo or len(codigo)>80: raise ValueError('Código de lote obligatorio, máximo 80 caracteres.')
    vence=date.fromisoformat(vencimiento) if isinstance(vencimiento,str) and vencimiento else vencimiento or None
    r=q.execute('SELECT id_lote,fecha_vencimiento,activo FROM lotes WITH(UPDLOCK,HOLDLOCK) WHERE id_producto=? AND codigo_lote=?',p,codigo).fetchone()
    if r:
        if r[1]!=vence or not r[2]: raise ValueError('El lote existente tiene otro vencimiento o está inactivo.')
        return r[0]
    return q.execute('INSERT lotes(id_producto,codigo_lote,fecha_vencimiento) OUTPUT INSERTED.id_lote VALUES(?,?,?)',p,codigo,vence).fetchone()[0]

def _validar_lote(q,p,l,u,cantidad,permitir_vencido=False):
    r=q.execute('SELECT activo,fecha_vencimiento FROM lotes WHERE id_lote=? AND id_producto=?',l,p).fetchone()
    if not r or not r[0]: raise ValueError('Seleccione un lote activo de este producto.')
    hoy=q.execute('SELECT CAST(SYSDATETIME() AS DATE)').fetchone()[0]
    if r[1] and r[1]<hoy and not permitir_vencido: raise ValueError('Lote vencido: requiere confirmación explícita.')
    disponible=_saldo_lote(q,l,u)
    if cantidad>disponible: raise ValueError(f'Stock insuficiente en el lote. Disponible: {disponible}.')
    return disponible

def _crear_movimiento(q,empleado,tipo,observacion,motivo=None,referencia=None):
    if len(observacion or '')>500 or len(referencia or '')>100: raise ValueError('Observación máximo 500 y referencia máximo 100 caracteres.')
    if motivo and not q.execute('SELECT 1 FROM motivos_movimiento WHERE id_motivo=? AND tipo=? AND activo=1',motivo,tipo).fetchone(): raise ValueError('Motivo inválido para este movimiento.')
    t=q.execute('SELECT id_tipo_movimiento FROM tipos_movimiento WHERE nombre=? AND estado=1 AND fecha_eliminacion IS NULL',tipo).fetchone()
    if not t: raise ValueError('Tipo de movimiento no disponible.')
    return q.execute('INSERT movimientos(id_empleado,id_tipo_movimiento,fecha_movimiento,observacion,fecha_creacion,id_motivo,referencia) OUTPUT INSERTED.id_movimiento VALUES(?,?,SYSDATETIME(),?,SYSDATETIME(),?,?)',empleado,t[0],observacion or None,motivo,referencia or None).fetchone()[0]

def _guardar_detalle(q,m,p,cantidad,origen,destino,anterior,nuevo,costo=None,lote=None):
    d=q.execute('INSERT detalle_movimientos(id_movimiento,id_producto,cantidad,id_ubicacion_origen,id_ubicacion_destino,stock_anterior,stock_nuevo,fecha_creacion,costo_unitario) OUTPUT INSERTED.id_detalle VALUES(?,?,?,?,?,?,?,SYSDATETIME(),?)',m,p,cantidad,origen,destino,anterior,nuevo,costo).fetchone()[0]
    if lote: q.execute('INSERT detalle_movimiento_lotes(id_detalle,id_lote,cantidad) VALUES(?,?,?)',d,lote,cantidad)
    return d

def _mover(q,empleado,p,origen,destino,cantidad,tipo,observacion='',id_motivo=None,
           referencia=None,costo_unitario=None,id_lote=None,codigo_lote=None,
           fecha_vencimiento=None,permitir_vencido=False):
    cantidad=decimal_inventario(cantidad,positivo=True)
    if origen and destino and int(origen)==int(destino): raise ValueError('Origen y destino deben ser diferentes.')
    _bloquear_producto(q,p)
    usa_lotes=_validar_entidades(q,empleado,p,[u for u in (origen,destino) if u])
    if destino: asegurar_espacio(q,p,destino)
    if not usa_lotes and (id_lote or codigo_lote or fecha_vencimiento): raise ValueError('Este producto no maneja lotes.')
    costo=decimal_inventario(costo_unitario,'Costo unitario',escala=2) if costo_unitario not in (None,'') else None
    if costo is not None and costo>=Decimal('10000000000000000'): raise ValueError('Costo fuera de rango.')
    anterior=_saldo(q,p,origen or destino)
    if origen and cantidad>anterior: raise ValueError(f'Stock insuficiente. Disponible: {anterior} unidades.')
    if usa_lotes:
        _comprobar_lotes(q,p,[u for u in (origen,destino) if u])
        if not origen: id_lote=_crear_lote(q,p,codigo_lote,fecha_vencimiento,id_lote)
        elif not id_lote: raise ValueError('Seleccione explícitamente un lote. Puede consultar la sugerencia FEFO/FIFO.')
        if origen:
            saldo=_validar_lote(q,p,id_lote,origen,cantidad,permitir_vencido)
            _poner_lote(q,id_lote,origen,saldo-cantidad)
        if destino: _poner_lote(q,id_lote,destino,_saldo_lote(q,id_lote,destino)+cantidad)
    nuevo=anterior-cantidad if origen else anterior+cantidad
    if origen: _poner_saldo(q,p,origen,nuevo)
    if destino: _poner_saldo(q,p,destino,_saldo(q,p,destino)+cantidad)
    if usa_lotes: _comprobar_lotes(q,p,[u for u in (origen,destino) if u])
    m=_crear_movimiento(q,empleado,tipo,observacion,id_motivo,referencia)
    detalle=_guardar_detalle(q,m,p,cantidad,origen,destino,anterior,nuevo,costo,id_lote)
    contexto=q.execute('''SELECT p.nombre,p.codigo,p.stock_minimo,
        (SELECT COALESCE(SUM(x.cantidad),0) FROM existencias x JOIN ubicaciones u ON u.id_ubicacion=x.id_ubicacion
         WHERE x.id_producto=p.id_producto AND x.fecha_eliminacion IS NULL AND u.estado=1 AND u.fecha_eliminacion IS NULL),
        CONCAT(e.nombres,' ',e.apellidos),m.fecha_movimiento
        FROM productos p CROSS JOIN empleados e CROSS JOIN movimientos m
        WHERE p.id_producto=? AND e.id_empleado=? AND m.id_movimiento=?''',p,empleado,m).fetchone()
    total=contexto[3];delta=Decimal(0) if tipo=='Transferencia' else cantidad if destino else -cantidad
    from core.event_bus import emitir
    datos=dict(id_movimiento=m,id_producto=p,id_empleado=empleado,tipo_movimiento=tipo,
               cantidad=cantidad,id_ubicacion_origen=origen,id_ubicacion_destino=destino,
               id_detalle=detalle,producto=contexto[0],codigo=contexto[1],stock_minimo=contexto[2],
               stock_anterior=total-delta,stock_nuevo=total,empleado=contexto[4],fecha=contexto[5],referencia=referencia)
    emitir('MOVIMIENTO_REGISTRADO','MOVIMIENTOS','movimientos','Movimiento registrado',
           f'{tipo}: {cantidad}. Movimiento #{m}.',reference='movimiento:'+str(m),data=datos,deduplicate=True)
    if tipo.startswith('Ajuste'):
        emitir('AJUSTE_INVENTARIO','INVENTARIO','movimientos','Ajuste de inventario',
               f'{tipo}: {cantidad}.',reference='ajuste:'+str(m),data=datos,deduplicate=True)
    from inventory.lotes_service import actualizar_alertas_vencimiento
    actualizar_alertas_vencimiento(q,p)
    return m

def _transaccion(fn):
    from core.audit_service import operation
    with operation('MOVIMIENTOS', 'INVENTORY_TRANSACTION', origin='desktop'):
        return _transaccion_observada(fn)


def _transaccion_observada(fn):
    from core.event_bus import _outbox,confirmar_eventos
    c=conectar()
    pendientes=[]; token=_outbox.set(pendientes)
    try:
        r=fn(c.cursor()); c.commit()
    except Exception: c.rollback(); raise
    finally:
        _outbox.reset(token)
        c.close()
    confirmar_eventos(pendientes)
    return r

def registrar_entrada(id_empleado,id_producto,id_ubicacion_destino,cantidad,observacion='',**opciones):
    return _transaccion(lambda q:_mover(q,id_empleado,id_producto,None,id_ubicacion_destino,cantidad,'Entrada',observacion,**opciones))

def registrar_salida(id_empleado,id_producto,id_ubicacion_origen,cantidad,observacion='',**opciones):
    return _transaccion(lambda q:_mover(q,id_empleado,id_producto,id_ubicacion_origen,None,cantidad,'Salida',observacion,**opciones))

def registrar_transferencia(id_empleado,id_producto,id_ubicacion_origen,id_ubicacion_destino,cantidad,observacion='',**opciones):
    return _transaccion(lambda q:_mover(q,id_empleado,id_producto,id_ubicacion_origen,id_ubicacion_destino,cantidad,'Transferencia',observacion,**opciones))

def _ajustar(q,empleado,p,u,fisico,observacion='',id_lote=None,esperado=None):
    fisico=decimal_inventario(fisico,'Stock físico')
    _bloquear_producto(q,p); usa_lotes=_validar_entidades(q,empleado,p,[u])
    if usa_lotes and not id_lote: raise ValueError('El ajuste requiere seleccionar un lote.')
    actual=_saldo_lote(q,id_lote,u) if usa_lotes else _saldo(q,p,u)
    if esperado is not None and actual!=Decimal(str(esperado)): raise ValueError('El stock cambió desde el conteo: vuelva a comparar antes de aplicar.')
    diferencia=fisico-actual
    if diferencia==0: return None
    tipo='Ajuste entrada' if diferencia>0 else 'Ajuste salida'
    motivo=q.execute('SELECT TOP 1 id_motivo FROM motivos_movimiento WHERE tipo=? AND activo=1 ORDER BY id_motivo',tipo).fetchone()
    return _mover(q,empleado,p,u if diferencia<0 else None,u if diferencia>0 else None,abs(diferencia),tipo,observacion,id_motivo=motivo[0] if motivo else None,id_lote=id_lote,permitir_vencido=True)

def registrar_ajuste(id_empleado,id_producto,id_ubicacion,cantidad_fisica,observacion='',id_lote=None,esperado=None):
    return _transaccion(lambda q:_ajustar(q,id_empleado,id_producto,id_ubicacion,cantidad_fisica,observacion,id_lote,esperado))

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


def buscar_movimientos(texto=None, tipo_movimiento=None, fecha_desde=None, fecha_hasta=None,
                       id_producto=None,id_categoria=None,id_ubicacion=None,id_empleado=None):
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
    if fecha_desde and fecha_hasta and fecha_desde>fecha_hasta:
        raise ValueError('Fecha desde debe ser anterior a fecha hasta.')
    for campo,valor in [('d.id_producto',id_producto),('p.id_categoria',id_categoria),('m.id_empleado',id_empleado)]:
        if valor:
            condiciones.append(campo+'=?'); parametros.append(valor)
    if id_ubicacion:
        condiciones.append('(d.id_ubicacion_origen=? OR d.id_ubicacion_destino=?)')
        parametros.extend([id_ubicacion]*2)
    consulta = """
        SELECT m.id_movimiento,m.id_empleado, m.fecha_movimiento, tm.nombre AS tipo_movimiento,
               CONCAT(e.codigo_empleado, ' - ', e.nombres, ' ', e.apellidos) AS empleado,
               p.id_producto,p.unidad_medida,p.codigo AS codigo_producto, p.nombre AS producto, d.cantidad,
               uo.codigo_ubicacion AS ubicacion_origen,
               ud.codigo_ubicacion AS ubicacion_destino,
               d.stock_anterior, d.stock_nuevo, m.observacion, mm.nombre AS motivo, m.referencia, d.costo_unitario
        FROM movimientos AS m
        INNER JOIN tipos_movimiento AS tm ON tm.id_tipo_movimiento = m.id_tipo_movimiento
        INNER JOIN empleados AS e ON e.id_empleado = m.id_empleado
        INNER JOIN detalle_movimientos AS d ON d.id_movimiento = m.id_movimiento
        INNER JOIN productos AS p ON p.id_producto = d.id_producto
        LEFT JOIN motivos_movimiento mm ON mm.id_motivo=m.id_motivo
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
        pass
        conexion.commit(); return True
    except Exception: conexion.rollback(); raise
    finally: cursor.close(); conexion.close()
