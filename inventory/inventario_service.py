"""Gestión de inventario: catálogos SQL, ficha, búsqueda y estadísticas reales."""
from decimal import Decimal, InvalidOperation
from datetime import date
from core.database import conectar

def decimal_inventario(valor,nombre='Cantidad',positivo=False,escala=3):
    try: numero=Decimal(str(valor).strip())
    except (InvalidOperation,ValueError,TypeError): raise ValueError(f'{nombre} debe ser un número válido.')
    paso=Decimal(1).scaleb(-escala)
    if not numero.is_finite() or numero<0 or (positivo and numero==0):
        raise ValueError(f'{nombre} debe ser '+('mayor que cero.' if positivo else 'cero o mayor.'))
    if numero>=Decimal('1000000000000000') or numero!=numero.quantize(paso):
        raise ValueError(f'{nombre} admite hasta {escala} decimales y está fuera de rango o precisión.')
    return numero.quantize(paso)

def estado_stock(stock,minimo,activo=True):
    if not activo: return 'INACTIVO'
    stock=Decimal(str(stock)); minimo=Decimal(str(minimo))
    if stock==0: return 'AGOTADO'
    if stock<=minimo/2: return 'CRÍTICO'
    if stock<=minimo: return 'BAJO'
    return 'NORMAL'

def consultar(sql,*args,conexion=None):
    propia=conexion is None; c=conexion or conectar(); q=c.cursor()
    try:
        q.execute(sql,*args); campos=[x[0] for x in q.description]
        return [dict(zip(campos,r)) for r in q.fetchall()]
    finally:
        q.close()
        if propia: c.close()

def listar_unidades(incluir_inactivas=False):
    return consultar('SELECT * FROM dbo.unidades_medida'+('' if incluir_inactivas else ' WHERE activo=1')+' ORDER BY nombre')

def guardar_unidad(nombre,abreviatura,id_unidad=None,activo=True):
    nombre=nombre.strip(); abreviatura=abreviatura.strip()
    if not nombre or len(nombre)>80 or not abreviatura or len(abreviatura)>16: raise ValueError('Nombre y abreviatura obligatorios (máximo 80 y 16 caracteres).')
    c=conectar()
    try:
        q=c.cursor()
        if id_unidad:
            q.execute('UPDATE dbo.unidades_medida SET nombre=?,abreviatura=?,activo=? WHERE id_unidad=?',nombre,abreviatura,activo,id_unidad)
            if not q.rowcount: raise ValueError('La unidad no existe.')
            q.execute('UPDATE dbo.productos SET unidad_medida=?,fecha_actualizacion=SYSDATETIME() WHERE id_unidad_medida=?',nombre,id_unidad)
        else:
            id_unidad=q.execute('INSERT dbo.unidades_medida(nombre,abreviatura) OUTPUT INSERTED.id_unidad VALUES(?,?)',nombre,abreviatura).fetchone()[0]
        c.commit(); return id_unidad
    except Exception: c.rollback(); raise
    finally: c.close()

def listar_motivos(tipo=None):
    return consultar('SELECT * FROM dbo.motivos_movimiento WHERE activo=1'+(' AND tipo=?' if tipo else '')+' ORDER BY nombre',*([tipo] if tipo else []))

def guardar_motivo(nombre,tipo):
    if not nombre.strip() or len(nombre)>100: raise ValueError('Motivo obligatorio, máximo 100 caracteres.')
    c=conectar()
    try:
        q=c.cursor()
        if not q.execute('SELECT 1 FROM tipos_movimiento WHERE nombre=? AND estado=1 AND fecha_eliminacion IS NULL',tipo).fetchone(): raise ValueError('Tipo de movimiento inválido.')
        id_motivo=q.execute('INSERT dbo.motivos_movimiento(nombre,tipo) OUTPUT INSERTED.id_motivo VALUES(?,?)',nombre.strip(),tipo).fetchone()[0]
        c.commit(); return id_motivo
    except Exception: c.rollback(); raise
    finally: c.close()

def buscar_inventario(texto='',estado='Todos',id_categoria=None,id_ubicacion=None,almacen=None,zona=None):
    condiciones=['i.fecha_eliminacion IS NULL']; args=[]
    estados={'Todos':'i.estado=1','Con stock':'i.estado=1 AND i.stock_actual>0',
             'Stock bajo':'i.estado=1 AND i.stock_actual<=i.stock_minimo',
             'Agotados':'i.estado=1 AND i.stock_actual=0','Inactivos':'i.estado=0'}
    if estado not in estados: raise ValueError('Filtro de estado inválido.')
    condiciones.append(estados[estado])
    if texto.strip():
        patron='%'+texto.strip()+'%'
        condiciones.append("(i.codigo COLLATE Latin1_General_CI_AI LIKE ? OR i.nombre COLLATE Latin1_General_CI_AI LIKE ? OR i.descripcion COLLATE Latin1_General_CI_AI LIKE ? OR i.categoria COLLATE Latin1_General_CI_AI LIKE ? OR EXISTS(SELECT 1 FROM existencias e JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion WHERE e.id_producto=i.id_producto AND e.fecha_eliminacion IS NULL AND u.estado=1 AND u.fecha_eliminacion IS NULL AND u.codigo_ubicacion COLLATE Latin1_General_CI_AI LIKE ?))")
        args.extend([patron]*5)
    if id_categoria: condiciones.append('i.id_categoria=?'); args.append(id_categoria)
    if id_ubicacion or almacen or zona:
        filtro=['e.id_producto=i.id_producto','e.fecha_eliminacion IS NULL','u.estado=1','u.fecha_eliminacion IS NULL']
        for campo,valor in [('id_ubicacion',id_ubicacion),('almacen',almacen),('zona',zona)]:
            if valor: filtro.append('u.'+campo+'=?'); args.append(valor)
        condiciones.append('EXISTS(SELECT 1 FROM existencias e JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion WHERE '+' AND '.join(filtro)+')')
    filas=consultar('SELECT i.* FROM dbo.vw_inventario i WHERE '+' AND '.join(condiciones)+' ORDER BY i.nombre',*args)
    for f in filas:
        f['unidad_medida']=f['unidad']; f['estado_stock']=f['estado_inventario']
    return filas

def guardar_producto(codigo,nombre,descripcion,id_categoria,id_unidad,precio,stock_minimo,
                     id_producto=None,control_lotes=False,codigo_barras=None,codigo_qr=None,imagen_producto=None):
    codigo=(codigo or '').strip().upper(); nombre=nombre.strip(); descripcion=(descripcion or '').strip()
    precio=decimal_inventario(precio,'Precio',escala=2); minimo=decimal_inventario(stock_minimo,'Stock mínimo')
    if precio>=Decimal('10000000000'): raise ValueError('Precio fuera de rango.')
    if not nombre or len(nombre)>150 or len(codigo)>30 or len(descripcion)>500: raise ValueError('Nombre obligatorio; máximo código 30, nombre 150 y descripción 500 caracteres.')
    for valor,limite in [(codigo_barras,100),(codigo_qr,250),(imagen_producto,1000)]:
        if valor and len(valor)>limite: raise ValueError('Campo opcional demasiado largo.')
    c=conectar()
    try:
        q=c.cursor()
        # Serializar código automático y cambios de catálogo, sin depender de roles.
        q.execute("DECLARE @r INT; EXEC @r=sp_getapplock @Resource=N'InventarioIA_productos',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; SELECT @r")
        if q.fetchone()[0]<0: raise RuntimeError('No fue posible bloquear el producto.')
        if not q.execute('SELECT 1 FROM categorias WHERE id_categoria=? AND estado=1 AND fecha_eliminacion IS NULL',id_categoria).fetchone(): raise ValueError('Categoría inválida o inactiva.')
        unidad=q.execute('SELECT nombre FROM unidades_medida WHERE id_unidad=? AND activo=1',id_unidad).fetchone()
        if not unidad: raise ValueError('Unidad inválida o inactiva.')
        if id_producto:
            actual=q.execute('SELECT control_lotes FROM productos WITH(UPDLOCK,HOLDLOCK) WHERE id_producto=? AND fecha_eliminacion IS NULL',id_producto).fetchone()
            if not actual: raise ValueError('Producto no encontrado.')
            if bool(actual[0])!=bool(control_lotes):
                saldo=q.execute('SELECT COALESCE(SUM(cantidad),0) FROM existencias WHERE id_producto=? AND fecha_eliminacion IS NULL',id_producto).fetchone()[0]
                if saldo: raise ValueError('Para cambiar el control de lotes el producto debe estar sin stock; conserva primero su trazabilidad mediante movimientos.')
        if not codigo:
            siguiente=q.execute('SELECT COALESCE(MAX(id_producto),0)+1 FROM productos').fetchone()[0]
            codigo=f'PRO-{siguiente:06d}'
            while q.execute('SELECT 1 FROM productos WHERE codigo=?',codigo).fetchone(): siguiente+=1; codigo=f'PRO-{siguiente:06d}'
        if q.execute('SELECT 1 FROM productos WHERE codigo COLLATE Latin1_General_CI_AI=? AND id_producto<>?',codigo,id_producto or 0).fetchone(): raise ValueError('Ya existe un producto con ese código.')
        valores=(codigo,nombre,descripcion or None,id_categoria,unidad[0],id_unidad,precio,minimo,control_lotes,codigo_barras or None,codigo_qr or None,imagen_producto or None)
        if id_producto:
            q.execute('UPDATE productos SET codigo=?,nombre=?,descripcion=?,id_categoria=?,unidad_medida=?,id_unidad_medida=?,precio=?,stock_minimo=?,control_lotes=?,codigo_barras=?,codigo_qr=?,imagen_producto=?,fecha_actualizacion=SYSDATETIME() WHERE id_producto=?',*valores,id_producto)
        else:
            id_producto=q.execute('INSERT productos(codigo,nombre,descripcion,id_categoria,unidad_medida,id_unidad_medida,precio,stock_minimo,control_lotes,codigo_barras,codigo_qr,imagen_producto,estado,fecha_creacion) OUTPUT INSERTED.id_producto VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,SYSDATETIME())',*valores).fetchone()[0]
        from inventory.alertas import verificar_alertas_stock
        verificar_alertas_stock(id_producto,c,q)
        c.commit(); return id_producto
    except Exception: c.rollback(); raise
    finally: c.close()

def activar_producto(id_producto,activo=True):
    c=conectar()
    try:
        q=c.cursor(); q.execute('UPDATE productos SET estado=?,fecha_actualizacion=SYSDATETIME() WHERE id_producto=? AND fecha_eliminacion IS NULL',activo,id_producto)
        if not q.rowcount: raise ValueError('Producto no encontrado.')
        if activo:
            from inventory.alertas import verificar_alertas_stock
            verificar_alertas_stock(id_producto,c,q)
        else:
            from inventory.tipos_alerta import obtener_tipo_alerta,PROXIMO_AGOTARSE
            tipos=[obtener_tipo_alerta(clave,cursor=q,obligatorio=False) for clave in ('stock_bajo','producto_agotado',PROXIMO_AGOTARSE,'lote_proximo_vencer','lote_vencido')]
            tipos=[t for t in tipos if t is not None]
            if tipos:
                q.execute('UPDATE alertas SET atendida=1,fecha_atencion=SYSDATETIME(),fecha_actualizacion=SYSDATETIME() WHERE id_producto=? AND atendida=0 AND fecha_eliminacion IS NULL AND id_tipo_alerta IN('+','.join('?' for _ in tipos)+')',id_producto,*tipos)
        c.commit()
    except Exception: c.rollback(); raise
    finally: c.close()

def obtener_ficha(id_producto):
    filas=consultar('SELECT * FROM vw_inventario WHERE id_producto=? AND fecha_eliminacion IS NULL',id_producto)
    if not filas: raise ValueError('Producto no encontrado.')
    f=filas[0]; f['estado_stock']=f['estado_inventario']; f['unidad_medida']=f['unidad']
    f['ubicaciones']=consultar('SELECT u.*,e.cantidad,e.posicion FROM existencias e JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion WHERE e.id_producto=? AND e.fecha_eliminacion IS NULL AND u.estado=1 AND u.fecha_eliminacion IS NULL ORDER BY u.codigo_ubicacion',id_producto)
    f['ultimo_movimiento']=consultar('SELECT TOP 1 m.fecha_movimiento,tm.nombre tipo,d.cantidad FROM movimientos m JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento WHERE d.id_producto=? AND m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC',id_producto)
    f['alertas']=consultar('SELECT mensaje,nivel FROM alertas WHERE id_producto=? AND atendida=0 AND fecha_eliminacion IS NULL',id_producto)
    from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
    f['prediccion']=predecir_agotamiento(id_producto,actualizar_alertas=False) if f['estado'] else {'datos_suficientes':False,'mensaje':'Producto inactivo.'}
    f['lotes']=listar_lotes(id_producto)
    return f

def listar_lotes(id_producto=None,id_ubicacion=None,conexion=None):
    cond=['1=1']; args=[]
    if id_producto: cond.append('l.id_producto=?'); args.append(id_producto)
    if id_ubicacion: cond.append('e.id_ubicacion=?'); args.append(id_ubicacion)
    return consultar("SELECT l.*,COALESCE(SUM(CASE WHEN u.estado=1 AND u.fecha_eliminacion IS NULL THEN e.cantidad ELSE 0 END),0) cantidad,CASE WHEN l.fecha_vencimiento<CAST(SYSDATETIME() AS DATE) THEN 'VENCIDO' WHEN l.fecha_vencimiento<=DATEADD(day,30,CAST(SYSDATETIME() AS DATE)) THEN 'PRÓXIMO A VENCER' ELSE 'VIGENTE' END estado_vencimiento,DATEDIFF(day,CAST(SYSDATETIME() AS DATE),l.fecha_vencimiento) dias_vencimiento FROM lotes l LEFT JOIN existencias_lotes e ON e.id_lote=l.id_lote LEFT JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion WHERE "+' AND '.join(cond)+' GROUP BY l.id_lote,l.id_producto,l.codigo_lote,l.fecha_ingreso,l.fecha_vencimiento,l.activo ORDER BY CASE WHEN l.fecha_vencimiento IS NULL THEN 1 ELSE 0 END,l.fecha_vencimiento,l.fecha_ingreso,l.id_lote',*args,conexion=conexion)

def sugerir_lotes(id_producto,id_ubicacion):
    # No ejecuta salidas. FEFO con vencimiento; FIFO para el resto.
    return [l for l in listar_lotes(id_producto,id_ubicacion) if l['activo'] and l['cantidad']>0]

def estadisticas_inventario(dias=30):
    if dias not in (7,30,60,90): raise ValueError('Periodo inválido.')
    top=consultar("SELECT TOP 10 p.id_producto,p.codigo,p.nombre,SUM(d.cantidad) cantidad FROM detalle_movimientos d JOIN movimientos m ON m.id_movimiento=d.id_movimiento JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento JOIN productos p ON p.id_producto=d.id_producto WHERE tm.nombre='Salida' AND m.fecha_movimiento>=DATEADD(day,-?,SYSDATETIME()) AND m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL GROUP BY p.id_producto,p.codigo,p.nombre ORDER BY cantidad DESC",dias)
    sin=consultar('SELECT i.* FROM vw_inventario i WHERE i.estado=1 AND i.fecha_eliminacion IS NULL AND i.fecha_creacion<=DATEADD(day,-?,SYSDATETIME()) AND NOT EXISTS(SELECT 1 FROM detalle_movimientos d JOIN movimientos m ON m.id_movimiento=d.id_movimiento WHERE d.id_producto=i.id_producto AND m.fecha_movimiento>=DATEADD(day,-?,SYSDATETIME()) AND d.fecha_eliminacion IS NULL AND m.fecha_eliminacion IS NULL)',dias,dias)
    return {'mas_consumidos':top,'baja_rotacion':sin,'rotacion':'Datos insuficientes: no existe una serie histórica del valor promedio del inventario.'}
