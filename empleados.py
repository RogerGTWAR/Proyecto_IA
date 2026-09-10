from database import conectar


def listar_empleados():
    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                id_empleado,
                codigo_empleado,
                nombres,
                apellidos,
                cargo,
                estado
            FROM empleados
            WHERE
                fecha_eliminacion IS NULL
                AND estado = 1
            ORDER BY
                nombres,
                apellidos;
        """)

        columnas = [
            columna[0]
            for columna in cursor.description
        ]

        return [
            dict(zip(columnas, fila))
            for fila in cursor.fetchall()
        ]

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def registrar_empleado(
        codigo,
        nombres,
        apellidos,
        cargo=None):

    codigo = codigo.strip().upper()
    nombres = nombres.strip()
    apellidos = apellidos.strip()

    cargo = (
        cargo.strip()
        if cargo and cargo.strip()
        else None
    )

    if not codigo or not nombres or not apellidos:
        raise ValueError(
            "Código, nombres y apellidos son obligatorios."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1
            FROM empleados
            WHERE
                codigo_empleado = ?
                AND fecha_eliminacion IS NULL;
        """, codigo)

        if cursor.fetchone():
            raise ValueError(
                "El código de empleado ya existe."
            )

        cursor.execute("""
            INSERT INTO empleados (
                codigo_empleado,
                nombres,
                apellidos,
                cargo,
                estado,
                fecha_creacion
            )

            OUTPUT INSERTED.id_empleado

            VALUES (
                ?,
                ?,
                ?,
                ?,
                1,
                SYSDATETIME()
            );
        """, codigo, nombres, apellidos, cargo)

        fila = cursor.fetchone()

        if fila is None:
            raise RuntimeError(
                "No fue posible obtener el ID del empleado registrado."
            )

        id_empleado = int(
            fila.id_empleado
        )

        conexion.commit()

        return {
            "id_empleado": id_empleado,
            "codigo_empleado": codigo,
            "nombres": nombres,
            "apellidos": apellidos,
            "cargo": cargo,
            "estado": True
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


def obtener_empleado(id_empleado):
    empleados = listar_empleados()

    return next(
        (
            empleado
            for empleado in empleados
            if empleado["id_empleado"] == int(id_empleado)
        ),
        None
    )


def actualizar_empleado(
        id_empleado,
        codigo,
        nombres,
        apellidos,
        cargo=None):

    codigo = codigo.strip().upper()
    nombres = nombres.strip()
    apellidos = apellidos.strip()

    cargo = (
        cargo.strip()
        if cargo and cargo.strip()
        else None
    )

    if not codigo or not nombres or not apellidos:
        raise ValueError(
            "Código, nombres y apellidos son obligatorios."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1
            FROM empleados
            WHERE
                codigo_empleado = ?
                AND id_empleado <> ?
                AND fecha_eliminacion IS NULL;
        """, codigo, id_empleado)

        if cursor.fetchone():
            raise ValueError(
                "El código de empleado ya está siendo utilizado."
            )

        cursor.execute("""
            UPDATE empleados

            SET
                codigo_empleado = ?,
                nombres = ?,
                apellidos = ?,
                cargo = ?,
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_empleado = ?
                AND fecha_eliminacion IS NULL;
        """, codigo, nombres, apellidos, cargo, id_empleado)

        if cursor.rowcount == 0:
            raise ValueError(
                "El empleado no existe o fue eliminado."
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


def eliminar_empleado(id_empleado):
    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            UPDATE empleados

            SET
                estado = 0,
                fecha_actualizacion = SYSDATETIME(),
                fecha_eliminacion = SYSDATETIME()

            WHERE
                id_empleado = ?
                AND fecha_eliminacion IS NULL;
        """, id_empleado)

        if cursor.rowcount == 0:
            raise ValueError(
                "El empleado no existe o ya fue eliminado."
            )

        cursor.execute("""
            UPDATE rostros_empleados

            SET
                estado = 0,
                fecha_actualizacion = SYSDATETIME(),
                fecha_eliminacion = SYSDATETIME()

            WHERE
                id_empleado = ?
                AND fecha_eliminacion IS NULL;
        """, id_empleado)

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


desactivar_empleado = eliminar_empleado
