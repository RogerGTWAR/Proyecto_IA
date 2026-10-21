"""Alertas por vencimiento, sin aplicar fechas a productos que no manejan lotes."""
from inventory.tipos_alerta import obtener_tipo_alerta
def actualizar_alertas_vencimiento(q,id_producto=None):
    parametros=[id_producto] if id_producto else []
    filas=q.execute("""SELECT l.id_lote,l.id_producto,l.codigo_lote,p.nombre,l.activo,
        l.fecha_vencimiento,COALESCE(SUM(e.cantidad),0) cantidad,
        DATEDIFF(day,CAST(SYSDATETIME() AS DATE),l.fecha_vencimiento) dias
        FROM lotes l JOIN productos p ON p.id_producto=l.id_producto
        LEFT JOIN existencias_lotes e ON e.id_lote=l.id_lote
        AND EXISTS(SELECT 1 FROM ubicaciones u WHERE u.id_ubicacion=e.id_ubicacion AND u.estado=1 AND u.fecha_eliminacion IS NULL)
        WHERE p.control_lotes=1 AND p.estado=1 AND p.fecha_eliminacion IS NULL"""+
        (' AND p.id_producto=?' if id_producto else '')+
        ' GROUP BY l.id_lote,l.id_producto,l.codigo_lote,p.nombre,l.activo,l.fecha_vencimiento',*parametros).fetchall()
    tipos={nombre:obtener_tipo_alerta(nombre,cursor=q,obligatorio=False) for nombre in ('Lote próximo a vencer','Lote vencido')}
    tipos={nombre:identificador for nombre,identificador in tipos.items() if identificador is not None}
    for l in filas:
        tipo='Lote vencido' if l.dias is not None and l.dias<0 else 'Lote próximo a vencer'
        aplica=l.activo and l.cantidad>0 and l.dias is not None and l.dias<=30
        if tipos:
            cierre='UPDATE alertas SET atendida=1,fecha_atencion=SYSDATETIME(),fecha_actualizacion=SYSDATETIME() WHERE id_lote=? AND atendida=0 AND fecha_eliminacion IS NULL AND id_tipo_alerta IN('+','.join('?' for _ in tipos)+')'
            argumentos=[l.id_lote,*tipos.values()]
            if aplica and tipo in tipos:
                cierre+=' AND id_tipo_alerta<>?';argumentos.append(tipos[tipo])
            q.execute(cierre,*argumentos)
        if aplica and tipo in tipos:
            mensaje=f'{l.nombre} · lote {l.codigo_lote}: '+(f'vencido hace {-l.dias} días.' if l.dias<0 else f'vence en {l.dias} días.')
            nivel='Critica' if l.dias<0 else 'Alta'
            q.execute('UPDATE alertas SET mensaje=?,nivel=?,fecha_actualizacion=SYSDATETIME() WHERE id_lote=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL',mensaje,nivel,l.id_lote,tipos[tipo])
            if not q.rowcount:
                q.execute('INSERT alertas(id_tipo_alerta,id_producto,id_lote,mensaje,nivel,atendida,fecha_creacion) VALUES(?,?,?,?,?,0,SYSDATETIME())',tipos[tipo],l.id_producto,l.id_lote,mensaje,nivel)

def refrescar_vencimientos():
    from core.database import conectar
    c=conectar()
    try:
        q=c.cursor()
        q.execute("DECLARE @r INT; EXEC @r=sp_getapplock @Resource=N'InventarioIA_vencimientos',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; SELECT @r")
        if q.fetchone()[0]<0: raise RuntimeError('No se pudo actualizar vencimientos.')
        productos=[r[0] for r in q.execute('SELECT id_producto FROM productos WHERE control_lotes=1 AND estado=1 AND fecha_eliminacion IS NULL ORDER BY id_producto').fetchall()]
        from inventory.movimientos import _bloquear_producto
        for p in productos:
            _bloquear_producto(q,p)
            actualizar_alertas_vencimiento(q,p)
        c.commit()
    except Exception: c.rollback(); raise
    finally: c.close()
