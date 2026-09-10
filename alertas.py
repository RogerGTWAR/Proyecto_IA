from database import conectar


TIPOS_STOCK = (
    "Stock bajo",
    "Producto agotado"
)


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

def verificar_alertas_stock(
        id_producto,
        conexion=None,
        cursor=None):

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
                AND e.fecha_eliminacion IS NULL

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
            nivel = "Alta"

            mensaje = (
                f"El producto {producto.nombre} tiene "
                f"{stock} unidades disponibles. "
                f"Stock mínimo: {producto.stock_minimo}."
            )

        # ----------------------------------------------------
        # Cerrar alertas anteriores que ya no correspondan
        # ----------------------------------------------------

        marcadores = ", ".join(
            "?"
            for _ in TIPOS_STOCK
        )

        parametros_cierre = [
            id_producto,
            *TIPOS_STOCK
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

                AND ta.nombre IN (
                    {marcadores}
                )
        """

        if alerta_actual:

            sql_cierre += """
                AND ta.nombre <> ?
            """

            parametros_cierre.append(
                alerta_actual
            )

        cursor.execute(sql_cierre, *parametros_cierre)


        # ----------------------------------------------------
        # Crear alerta si es necesaria
        # ----------------------------------------------------

        if alerta_actual:

            cursor.execute("""
                SELECT
                    ta.id_tipo_alerta

                FROM tipos_alerta AS ta

                WHERE
                    ta.nombre = ?
                    AND ta.estado = 1
                    AND ta.fecha_eliminacion IS NULL;
                """, alerta_actual)

            tipo = cursor.fetchone()

            if tipo is None:
                raise ValueError(
                    f"El tipo de alerta "
                    f"'{alerta_actual}' "
                    "no existe o está inactivo."
                )


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
                """, id_producto, tipo.id_tipo_alerta)

            existe = cursor.fetchone()

            if existe is None:

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
                    """, tipo.id_tipo_alerta, id_producto, mensaje, nivel)


        if conexion_propia:
            conexion.commit()

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

def listar_alertas(solo_pendientes=False):

    conexion = None
    cursor = None

    try:

        conexion = conectar()
        cursor = conexion.cursor()

        consulta = """
            SELECT
                a.id_alerta,

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

                AND ta.nombre IN (
                    'Stock bajo',
                    'Producto agotado',
                    'Stock excedido',
                    'Próximo a agotarse',
                    'Cantidad inusual',
                    'Movimiento anormal',
                    'Horario inusual',
                    'Empleado no reconocido'
                )
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


# ============================================================
# ALERTA DE EMPLEADO NO RECONOCIDO
# ============================================================

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
