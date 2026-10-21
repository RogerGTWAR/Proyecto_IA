pass
from core.database import conectar
from inventory.tipos_alerta import obtener_tipo_alerta
from core.audit_service import audit_action


TIPOS_STOCK = (
    "Stock bajo",
    "Producto agotado"
)


@audit_action('ALERTAS','ANOMALY_ALERT_PERSIST',origin='automatic')
def registrar_alerta_anomalia_evento(datos):
    """Reuse the existing anomaly alert catalog and avoid its atomic movement alert."""
    if not datos.get('id_movimiento') or not datos.get('id_producto'): return None
    c=conectar()
    try:
        q=c.cursor()
        tipo=obtener_tipo_alerta('Cantidad inusual',cursor=q,obligatorio=False)
        if tipo is None:return None
        q.execute("SET NOCOUNT ON; IF @@TRANCOUNT=0 BEGIN TRANSACTION; DECLARE @r INT; EXEC @r=sp_getapplock @Resource=?,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000; SELECT @r",
                  'evento-anomalia:'+str(datos['id_movimiento'])+':'+str(datos['id_producto']))
        if q.fetchone()[0]<0:raise RuntimeError('No se pudo bloquear la alerta del hallazgo.')
        existente=q.execute('''SELECT TOP 1 id_alerta FROM alertas WITH(UPDLOCK,HOLDLOCK)
            WHERE id_movimiento=? AND id_producto=? AND id_tipo_alerta=? AND fecha_eliminacion IS NULL''',
            datos['id_movimiento'],datos['id_producto'],tipo).fetchone()
        if existente:return {'id_alerta':int(existente[0]),'creada':False}
        fila=q.execute('''INSERT alertas(id_tipo_alerta,id_producto,id_movimiento,id_empleado,mensaje,nivel,atendida,fecha_creacion)
            OUTPUT INSERTED.id_alerta VALUES(?,?,?,?,?,?,0,SYSDATETIME())''',tipo,datos['id_producto'],datos['id_movimiento'],
            datos.get('id_empleado'),str(datos.get('motivo','Movimiento inusual'))[:500],str(datos.get('nivel','Alta')).title()).fetchone()
        c.commit()
        return {'id_alerta':int(fila[0]),'creada':True}
    except Exception:
        c.rollback();raise
    finally:c.close()


@audit_action('ALERTAS','INTRUSION_ALERT_PERSIST',origin='automatic')
def registrar_alerta_intrusion(evento):
    """Registrar una transición confirmada, de forma idempotente por evento local."""
    import uuid
    import json
    from surveillance.identidad_vigilancia import texto_identidad
    from datetime import datetime,timezone,timedelta
    identificador=uuid.UUID(evento['id_evento']).hex
    fecha=datetime.fromisoformat(evento['fecha_hora'])
    if fecha.tzinfo is None:raise ValueError('La intrusión debe incluir zona horaria.')
    fecha=fecha.astimezone(timezone(timedelta(hours=-6)))
    marcador='[intrusion:'+identificador+']'
    mensaje=(f'{marcador} Intrusión detectada: {texto_identidad(evento)}; Zona: {evento["zona"]}; '
             f'Cámara: {evento["camara"]}; Track: {evento["track_id"]}; YOLO: {evento["confianza"]:.2f}.')[:500]
    detalle=json.dumps({k:evento.get(k) for k in ('id_evento','fecha_hora','camara','zona','track_id',
        'confianza','estado_identidad','subject','id_empleado','codigo_empleado','nombre','cargo',
        'similitud_facial','empleado_activo','identidad_evaluada')},ensure_ascii=False,allow_nan=False)
    empleado=evento.get('id_empleado') if evento.get('estado_identidad') in ('EMPLEADO_RECONOCIDO','EMPLEADO_INACTIVO') else None
    c=conectar()
    try:
        q=c.cursor()
        bloqueo=q.execute("""SET NOCOUNT ON; IF @@TRANCOUNT=0 BEGIN TRANSACTION;
            DECLARE @r int; EXEC @r=sp_getapplock
            @Resource=?,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000; SELECT @r;""",
            'inventario_intrusion_'+identificador).fetchone()[0]
        if bloqueo<0:raise RuntimeError('No se pudo bloquear el registro de intrusión.')
        anterior=q.execute('SELECT id_alerta FROM dbo.alertas WHERE LEFT(mensaje,?)=?',len(marcador),marcador).fetchone()
        if anterior:
            q.execute('UPDATE dbo.alertas SET mensaje=?,id_empleado=?,detalle_vigilancia=? WHERE id_alerta=?',
                      mensaje,empleado,detalle,int(anterior[0]))
            c.commit();return {'id_alerta':int(anterior[0]),'creada':False}
        tipo=obtener_tipo_alerta('intrusion_detectada',cursor=q)
        fila=q.execute('''INSERT dbo.alertas(id_tipo_alerta,id_producto,id_movimiento,id_empleado,
            id_ubicacion,mensaje,nivel,atendida,fecha_creacion,detalle_vigilancia)
            OUTPUT INSERTED.id_alerta VALUES(?,NULL,NULL,?,NULL,?,'Alta',0,?,?)''',
            tipo,empleado,mensaje,fecha.replace(tzinfo=None),detalle).fetchone()
        c.commit();return {'id_alerta':int(fila[0]),'creada':True}
    except Exception:
        c.rollback();raise
    finally:c.close()


def _filas_a_diccionarios(cursor, filas):
    columnas = [
        columna[0]
        for columna in cursor.description
    ]

    return [
        dict(zip(columnas, fila))
        for fila in filas
    ]


# ============================================================
# VERIFICAR ALERTAS DE STOCK
# ============================================================

@audit_action('ALERTAS','STOCK_ALERT_EVALUATION',origin='automatic')
def verificar_alertas_stock(
        id_producto,
        conexion=None,
        cursor=None, publicar=True,publicar_stock_evento=True):

    """
    Verifica el stock actual de un producto.

    Puede:
    - crear una alerta nueva,
    - cerrar alertas anteriores,
    - participar dentro de una transacción existente.
    """

    conexion_propia = conexion is None
    cursor_propio = cursor is None

    if conexion_propia:
        conexion = conectar()

    if cursor_propio:
        cursor = conexion.cursor()

    try:

        # ----------------------------------------------------
        # Obtener producto y stock total
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                p.nombre,
                p.stock_minimo,

                COALESCE(
                    SUM(e.cantidad),
                    0
                ) AS stock_total

            FROM productos AS p

            LEFT JOIN existencias AS e
                ON e.id_producto = p.id_producto
                AND e.fecha_eliminacion IS NULL AND EXISTS(SELECT 1 FROM ubicaciones ua WHERE ua.id_ubicacion=e.id_ubicacion AND ua.estado=1 AND ua.fecha_eliminacion IS NULL)

            WHERE
                p.id_producto = ?
                AND p.fecha_eliminacion IS NULL

            GROUP BY
                p.nombre,
                p.stock_minimo;
            """, id_producto)

        producto = cursor.fetchone()

        if producto is None:
            raise ValueError(
                "El producto no existe o fue eliminado."
            )

        stock = producto.stock_total

        alerta_actual = None
        alerta_creada = False
        nivel = None
        mensaje = None


        # ----------------------------------------------------
        # Determinar estado del stock
        # ----------------------------------------------------

        if stock == 0:

            alerta_actual = "Producto agotado"
            nivel = "Critica"

            mensaje = (
                f"El producto {producto.nombre} "
                "se encuentra agotado."
            )

        elif stock <= producto.stock_minimo:

            alerta_actual = "Stock bajo"
            nivel = "Critica" if stock <= producto.stock_minimo / 2 else "Alta"

            mensaje = (
                f"El producto {producto.nombre} tiene "
                f"{stock} unidades disponibles. "
                f"Stock mínimo: {producto.stock_minimo}."
            )

        # ----------------------------------------------------
        # Cerrar alertas anteriores que ya no correspondan
        # ----------------------------------------------------

        ids_stock = {nombre: obtener_tipo_alerta(nombre,cursor=cursor,obligatorio=False) for nombre in TIPOS_STOCK}
        ids_stock = {nombre:identificador for nombre,identificador in ids_stock.items() if identificador is not None}
        tipo_id = obtener_tipo_alerta(alerta_actual,cursor=cursor) if alerta_actual else None
        marcadores = ", ".join(
            "?"
            for _ in ids_stock
        )

        parametros_cierre = [
            id_producto,
            *ids_stock.values()
        ]

        sql_cierre = f"""
            UPDATE a

            SET
                atendida = 1,
                fecha_atencion = SYSDATETIME(),
                fecha_actualizacion = SYSDATETIME()

            FROM alertas AS a

            INNER JOIN tipos_alerta AS ta
                ON ta.id_tipo_alerta = a.id_tipo_alerta

            WHERE
                a.id_producto = ?
                AND a.atendida = 0
                AND a.fecha_eliminacion IS NULL

                AND ta.fecha_eliminacion IS NULL
                AND ta.estado = 1

                AND ta.id_tipo_alerta IN (
                    {marcadores}
                )
        """

        if alerta_actual:

            sql_cierre += """
                AND ta.id_tipo_alerta <> ?
            """

            parametros_cierre.append(
                tipo_id
            )

        resueltas=0
        if ids_stock:
            cursor.execute(sql_cierre, *parametros_cierre)
            if type(cursor.rowcount) is int and cursor.rowcount>0:resueltas=cursor.rowcount


        # ----------------------------------------------------
        # Crear alerta si es necesaria
        # ----------------------------------------------------

        if alerta_actual:

            # ------------------------------------------------
            # Evitar alerta duplicada pendiente
            # ------------------------------------------------

            cursor.execute("""
                SELECT 1

                FROM alertas

                WHERE
                    id_producto = ?
                    AND id_tipo_alerta = ?
                    AND atendida = 0
                    AND fecha_eliminacion IS NULL
                ;
                """, id_producto, tipo_id)

            existe = cursor.fetchone()

            if existe is not None:
                cursor.execute('UPDATE alertas SET mensaje=?,nivel=?,fecha_actualizacion=SYSDATETIME() WHERE id_producto=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL',
                               mensaje,nivel,id_producto,tipo_id)

            if existe is None:
                alerta_creada=True

                cursor.execute("""
                    INSERT INTO alertas (
                        id_tipo_alerta,
                        id_producto,
                        mensaje,
                        nivel,
                        atendida,
                        fecha_creacion
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        0,
                        SYSDATETIME()
                    );
                    """, tipo_id, id_producto, mensaje, nivel)


        if conexion_propia:
            conexion.commit()
            if alerta_actual and not alerta_creada:
                from core.audit_service import audit
                audit.record('ALERTAS','ALERT_DUPLICATE_AVOIDED','SKIPPED',entity_type='producto',entity_id=id_producto)
                audit.record('ALERTAS','ALERT_UPDATED',entity_type='producto',entity_id=id_producto)

        if publicar:
            from core.event_bus import _outbox
            # Caller-owned transactions publish only through the shared after-commit outbox.
            if conexion_propia or _outbox.get() is not None:
                from core.eventos_servicios import publicar_stock
                if publicar_stock_evento:
                    publicar_stock(id_producto, stock, producto.stock_minimo, producto.nombre, nivel=nivel,alertas_actualizadas=True)
                from core.event_bus import emitir
                if alerta_creada:
                    emitir('ALERTA_CREADA','ALERTAS','alertas','Alerta de stock creada',mensaje,nivel,
                           'alerta-stock:'+str(id_producto),{'id_producto':id_producto},metadata={'derivada':True})
                if resueltas:
                    emitir('ALERTA_RESUELTA','ALERTAS','alertas','Alertas de stock resueltas',
                           f'{resueltas} alertas ya no corresponden al stock actual.',
                           reference='alerta-stock-resuelta:'+str(id_producto),data={'id_producto':id_producto,'cantidad':resueltas})

        return alerta_actual


    except Exception:

        if conexion_propia:
            conexion.rollback()

        raise


    finally:

        if cursor_propio and cursor is not None:
            cursor.close()

        if conexion_propia and conexion is not None:
            conexion.close()


# ============================================================
# LISTAR ALERTAS
# ============================================================

def listar_alertas(solo_pendientes=False,refrescar=True):
    from inventory.lotes_service import refrescar_vencimientos
    if refrescar:refrescar_vencimientos()

    conexion = None
    cursor = None

    try:

        conexion = conectar()
        cursor = conexion.cursor()

        consulta = """
            SELECT
                a.id_alerta,a.id_producto,a.id_empleado,a.id_movimiento,

                a.fecha_creacion
                    AS fecha_generacion,

                ta.nombre
                    AS tipo,

                a.nivel,

                COALESCE(
                    p.nombre,
                    'Sin producto'
                ) AS producto,

                a.mensaje,

                CASE
                    WHEN a.atendida = 1
                        THEN 'Atendida'
                    ELSE 'Pendiente'
                END AS estado

            FROM alertas AS a

            INNER JOIN tipos_alerta AS ta
                ON ta.id_tipo_alerta =
                   a.id_tipo_alerta

            LEFT JOIN productos AS p
                ON p.id_producto =
                   a.id_producto

            WHERE
                a.fecha_eliminacion IS NULL

                AND ta.fecha_eliminacion IS NULL

                AND ta.estado = 1
        """

        if solo_pendientes:

            consulta += """
                AND a.atendida = 0
            """

        consulta += """
            ORDER BY
                a.fecha_creacion DESC;
        """

        cursor.execute(
            consulta
        )

        filas = cursor.fetchall()

        return _filas_a_diccionarios(
            cursor,
            filas
        )


    finally:

        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


# ============================================================
# MARCAR ALERTA COMO ATENDIDA
# ============================================================

@audit_action('ALERTAS','ALERT_RESOLVE',origin='desktop')
def marcar_alerta_atendida(id_alerta):

    conexion = None
    cursor = None

    try:

        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            UPDATE alertas

            SET
                atendida = 1,
                fecha_atencion = SYSDATETIME(),
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_alerta = ?
                AND atendida = 0
                AND fecha_eliminacion IS NULL;
            """, id_alerta)

        if cursor.rowcount == 0:

            raise ValueError(
                "La alerta no existe "
                "o ya fue atendida."
            )

        pass

        conexion.commit()
        from core.event_bus import emitir
        emitir('ALERTA_RESUELTA','ALERTAS','alertas','Alerta atendida',
               reference='alerta-resuelta:'+str(id_alerta),data={'id_alerta':id_alerta},deduplicate=True)

        return True


    except Exception:

        if conexion is not None:
            conexion.rollback()

        raise


    finally:

        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


# ============================================================
# ALERTA DE EMPLEADO NO RECONOCIDO
# ============================================================

@audit_action('ALERTAS','UNKNOWN_FACE_ALERT_PERSIST',origin='automatic')
def registrar_alerta_empleado_no_reconocido():

    conexion = None
    cursor = None

    try:

        conexion = conectar()
        cursor = conexion.cursor()


        # ----------------------------------------------------
        # Obtener tipo de alerta
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id_tipo_alerta

            FROM tipos_alerta

            WHERE
                nombre = 'Empleado no reconocido'
                AND estado = 1
                AND fecha_eliminacion IS NULL;
            """
        )

        tipo = cursor.fetchone()

        if tipo is None:

            raise ValueError(
                "El tipo de alerta "
                "'Empleado no reconocido' "
                "no existe o está inactivo."
            )


        # ----------------------------------------------------
        # Registrar alerta
        # ----------------------------------------------------

        cursor.execute("""
            INSERT INTO alertas (
                id_tipo_alerta,
                id_producto,
                id_movimiento,
                id_empleado,
                id_ubicacion,
                mensaje,
                nivel,
                atendida,
                fecha_creacion
            )

            OUTPUT INSERTED.id_alerta

            VALUES (
                ?,
                NULL,
                NULL,
                NULL,
                NULL,
                ?,
                'Alta',
                0,
                SYSDATETIME()
            );
            """, tipo.id_tipo_alerta, "Se detectó una persona no reconocida "
                "mediante la cámara del almacén.")

        fila = cursor.fetchone()

        if fila is None:

            raise RuntimeError(
                "No fue posible obtener el ID "
                "de la alerta registrada."
            )

        id_alerta = int(
            fila.id_alerta
        )

        conexion.commit()

        return {
            "creada": True,
            "id_alerta": id_alerta
        }


    except Exception:

        if conexion is not None:
            conexion.rollback()

        raise


    finally:

        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


# Alias para compatibilidad con código anterior
registrar_empleado_no_reconocido = (
    registrar_alerta_empleado_no_reconocido
)


# ============================================================
# ELIMINAR ALERTA LÓGICAMENTE
# ============================================================

def eliminar_alerta(id_alerta):

    conexion = None
    cursor = None

    try:

        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            UPDATE alertas

            SET
                fecha_eliminacion = SYSDATETIME(),
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_alerta = ?
                AND fecha_eliminacion IS NULL;
            """, id_alerta)

        if cursor.rowcount == 0:

            raise ValueError(
                "La alerta no existe "
                "o ya fue eliminada."
            )

        pass

        conexion.commit()

        return True


    except Exception:

        if conexion is not None:
            conexion.rollback()

        raise


    finally:

        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()
