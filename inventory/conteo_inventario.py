"""Conteo físico y aplicación íntegra de sus diferencias como movimientos."""
from inventory.inventario_service import consultar,decimal_inventario
from inventory.movimientos import _transaccion,_ajustar,_bloquear_producto,_validar_entidades

def listar_conteo_ubicacion(id_ubicacion):
    filas=consultar("""SELECT p.id_producto,p.codigo,p.nombre,p.unidad_medida,p.control_lotes,
        e.posicion,e.cantidad cantidad_sistema,CAST(NULL AS INT) id_lote,CAST(NULL AS NVARCHAR(80)) codigo_lote
        FROM existencias e JOIN productos p ON p.id_producto=e.id_producto
        WHERE e.id_ubicacion=? AND e.fecha_eliminacion IS NULL AND p.estado=1
        AND p.fecha_eliminacion IS NULL AND p.control_lotes=0
        UNION ALL SELECT p.id_producto,p.codigo,p.nombre,p.unidad_medida,p.control_lotes,
        (SELECT TOP 1 ex.posicion FROM existencias ex WHERE ex.id_producto=p.id_producto
            AND ex.id_ubicacion=e.id_ubicacion AND ex.fecha_eliminacion IS NULL),
        e.cantidad,l.id_lote,l.codigo_lote FROM existencias_lotes e
        JOIN lotes l ON l.id_lote=e.id_lote JOIN productos p ON p.id_producto=l.id_producto
        WHERE e.id_ubicacion=? AND p.estado=1 AND p.fecha_eliminacion IS NULL AND p.control_lotes=1 AND l.activo=1
        ORDER BY nombre,codigo_lote""",id_ubicacion,id_ubicacion)
    for f in filas: f['cantidad_fisica']=f['cantidad_sistema']
    return filas

def guardar_conteo(id_empleado,id_ubicacion,filas,id_conteo=None):
    from core.audit_service import operation
    with operation('INVENTARIO','COUNT_SAVE',origin='desktop',entity_type='conteo',entity_id=id_conteo):
        return _guardar_conteo(id_empleado,id_ubicacion,filas,id_conteo)

def _guardar_conteo(id_empleado,id_ubicacion,filas,id_conteo=None):
    if not filas: raise ValueError('El conteo está vacío.')
    claves=[(f['id_producto'],f.get('id_lote')) for f in filas]
    if len(set(claves))!=len(claves): raise ValueError('Productos/lotes duplicados en el conteo.')
    def ejecutar(q):
        existentes=None
        if id_conteo is not None:
            c=q.execute('SELECT id_ubicacion,estado FROM conteos_inventario WITH(UPDLOCK,HOLDLOCK) WHERE id_conteo=?',id_conteo).fetchone()
            if not c or c.estado!='BORRADOR':raise ValueError('El conteo está cerrado o no existe.')
            if c.id_ubicacion!=id_ubicacion:raise ValueError('La ubicación del borrador no puede cambiar.')
            existentes={(f.id_producto,f.id_lote):f for f in q.execute('SELECT * FROM detalle_conteos WHERE id_conteo=?',id_conteo).fetchall()}
            if set(existentes)!=set(claves):raise ValueError('Los productos/lotes del borrador cambiaron. Cargue de nuevo el conteo.')
        for p in sorted({f['id_producto'] for f in filas}):
            _bloquear_producto(q,p); _validar_entidades(q,id_empleado,p,[id_ubicacion])
        numero=id_conteo
        if numero is None:
            numero=q.execute('INSERT conteos_inventario(id_ubicacion,id_empleado) OUTPUT INSERTED.id_conteo VALUES(?,?)',id_ubicacion,id_empleado).fetchone()[0]
        else:q.execute('UPDATE conteos_inventario SET id_empleado=? WHERE id_conteo=?',id_empleado,numero)
        for f in filas:
            fisico=decimal_inventario(f['cantidad_fisica'],'Cantidad física')
            sistema=decimal_inventario(f['cantidad_sistema'],'Cantidad del sistema')
            contado=f.get('contado',True)
            if type(contado) is not bool:raise ValueError('El estado de conteo debe ser explícito.')
            if existentes is None:
                q.execute('INSERT detalle_conteos(id_conteo,id_producto,id_lote,cantidad_sistema,cantidad_fisica,contado) VALUES(?,?,?,?,?,?)',numero,f['id_producto'],f.get('id_lote'),sistema,fisico,contado)
            else:
                anterior=existentes[(f['id_producto'],f.get('id_lote'))]
                if anterior.cantidad_sistema!=sistema:raise ValueError('El stock de referencia del borrador no puede cambiar.')
                q.execute('UPDATE detalle_conteos SET cantidad_fisica=?,contado=? WHERE id_detalle_conteo=?',fisico,contado,anterior.id_detalle_conteo)
        from core.event_bus import emitir
        datos=dict(id_conteo=numero,id_empleado=id_empleado,id_ubicacion=id_ubicacion)
        if id_conteo is None:
            emitir('CONTEO_INICIADO','CONTEO','conteo_inventario','Conteo iniciado',data=datos,reference='conteo:'+str(numero))
        emitir('CONTEO_GUARDADO','CONTEO','conteo_inventario','Conteo guardado',data=datos,reference='conteo:'+str(numero))
        diferencias=[dict(f) for f in filas if f.get('contado',True) and decimal_inventario(f['cantidad_fisica'])!=decimal_inventario(f['cantidad_sistema'])]
        if diferencias:
            emitir('DIFERENCIA_CONTEO','CONTEO','conteo_inventario','Diferencias en el conteo',
                   f'{len(diferencias)} posiciones con diferencia.',severity='MEDIA',data=dict(datos,diferencias=diferencias))
        return numero
    return _transaccion(ejecutar)

def aplicar_conteo(id_conteo,esperado=None,empleado_esperado=None):
    from core.audit_service import operation
    with operation('INVENTARIO','COUNT_APPLY',origin='desktop',entity_type='conteo',entity_id=id_conteo):
        return _aplicar_conteo(id_conteo,esperado,empleado_esperado)

def _aplicar_conteo(id_conteo,esperado=None,empleado_esperado=None):
    def ejecutar(q):
        c=q.execute("SELECT id_empleado,id_ubicacion,estado FROM conteos_inventario WITH(UPDLOCK,HOLDLOCK) WHERE id_conteo=?",id_conteo).fetchone()
        if not c or c.estado!='BORRADOR': raise ValueError('El conteo no existe o ya fue aplicado.')
        filas=q.execute('SELECT * FROM detalle_conteos WHERE id_conteo=? ORDER BY id_producto,id_lote',id_conteo).fetchall()
        if not filas or any(not f.contado for f in filas):raise ValueError('Complete el conteo de todos los productos/lotes antes de aplicar ajustes.')
        if esperado is not None:
            actual={(f.id_producto,f.id_lote):(f.cantidad_sistema,f.cantidad_fisica) for f in filas}
            referencia={(f['id_producto'],f.get('id_lote')):(decimal_inventario(f['cantidad_sistema']),decimal_inventario(f['cantidad_fisica'])) for f in esperado}
            if actual!=referencia or (empleado_esperado is not None and c.id_empleado!=empleado_esperado):
                raise ValueError('El borrador cambió desde la revisión. Cárguelo de nuevo antes de aplicar.')
        for f in filas:
            m=_ajustar(q,c.id_empleado,f.id_producto,c.id_ubicacion,f.cantidad_fisica,
                       f'Ajuste generado por conteo físico de inventario. Conteo #{id_conteo}',f.id_lote,f.cantidad_sistema)
            q.execute('UPDATE detalle_conteos SET id_movimiento=? WHERE id_detalle_conteo=?',m,f.id_detalle_conteo)
        q.execute("UPDATE conteos_inventario SET estado='APLICADO' WHERE id_conteo=?",id_conteo)
        from core.event_bus import emitir
        emitir('CONTEO_FINALIZADO','CONTEO','conteo_inventario','Conteo aplicado',
               reference='conteo-finalizado:'+str(id_conteo),data={'id_conteo':id_conteo},deduplicate=True)
        return id_conteo
    return _transaccion(ejecutar)

def listar_conteos():
    return consultar('''SELECT c.*,u.codigo_ubicacion,u.estante,u.nivel,
        CONCAT(e.nombres,' ',e.apellidos) empleado,e.codigo_empleado FROM conteos_inventario c
        JOIN ubicaciones u ON u.id_ubicacion=c.id_ubicacion JOIN empleados e ON e.id_empleado=c.id_empleado ORDER BY c.fecha DESC,c.id_conteo DESC''')


def cargar_conteo(id_conteo):
    cabecera=consultar('SELECT * FROM conteos_inventario WHERE id_conteo=?',id_conteo)
    if not cabecera:raise ValueError('El conteo no existe.')
    c=cabecera[0]
    filas=consultar('''SELECT d.*,p.codigo,p.nombre,p.unidad_medida,l.codigo_lote,ex.posicion FROM detalle_conteos d
        JOIN productos p ON p.id_producto=d.id_producto LEFT JOIN lotes l ON l.id_lote=d.id_lote
        LEFT JOIN existencias ex ON ex.id_producto=d.id_producto AND ex.id_ubicacion=? AND ex.fecha_eliminacion IS NULL
        WHERE d.id_conteo=? ORDER BY ex.posicion,p.nombre,l.codigo_lote''',c['id_ubicacion'],id_conteo)
    return c,filas


def resumir_conteo(filas):
    from decimal import Decimal
    contadas=[f for f in filas if f.get('contado')]
    diferencias=[Decimal(str(f['cantidad_fisica']))-Decimal(str(f['cantidad_sistema'])) for f in contadas]
    unidades={}
    for f in filas:
        u=f.get('unidad_medida') or 'Cantidad';s=unidades.setdefault(u,dict(sistema=Decimal(0),fisico=Decimal(0),diferencia=Decimal(0)))
        s['sistema']+=Decimal(str(f['cantidad_sistema']))
        if f.get('contado'):
            s['fisico']+=Decimal(str(f['cantidad_fisica']))
            s['diferencia']+=Decimal(str(f['cantidad_fisica']))-Decimal(str(f['cantidad_sistema']))
    return dict(registros=len(filas),productos=len({f['id_producto'] for f in filas}),contados=len(contadas),por_unidad=unidades,
        correctos=sum(d==0 for d in diferencias),faltantes=sum(d<0 for d in diferencias),sobrantes=sum(d>0 for d in diferencias),
        sistema=sum((Decimal(str(f['cantidad_sistema'])) for f in filas),Decimal(0)),
        fisico=sum((Decimal(str(f['cantidad_fisica'])) for f in contadas),Decimal(0)),
        diferencia=sum(diferencias,Decimal(0)))
