from decimal import Decimal, InvalidOperation

import pyodbc

from database import conectar


CONSULTA_PRODUCTOS = """
    SELECT
        p.id_producto,
        p.codigo,
        p.nombre,
        c.nombre AS categoria,
        p.unidad_medida,
        p.precio,

        COALESCE(
            SUM(e.cantidad),
            0
        ) AS stock_actual,

        p.stock_minimo,

        CASE
            WHEN COALESCE(
                SUM(e.cantidad),
                0
            ) = 0
                THEN 'Agotado'

            WHEN COALESCE(
                SUM(e.cantidad),
                0
            ) <= p.stock_minimo
                THEN 'Stock bajo'

            ELSE 'Normal'
        END AS estado_stock

    FROM productos AS p

    INNER JOIN categorias AS c
        ON c.id_categoria = p.id_categoria

    LEFT JOIN existencias AS e
        ON e.id_producto = p.id_producto
        AND e.fecha_eliminacion IS NULL

    WHERE
        p.fecha_eliminacion IS NULL
        AND p.estado = 1
        AND c.fecha_eliminacion IS NULL
        AND c.estado = 1
"""


def _filas_a_diccionarios(cursor, filas):
    columnas = [
        columna[0]
        for columna in cursor.description
    ]

    return [
        dict(zip(columnas, fila))
        for fila in filas
    ]


def _consultar_lista(
        consulta,
        parametros=()):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute(consulta, *parametros)

        return _filas_a_diccionarios(
            cursor,
            cursor.fetchall()
        )

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def _validar_precio(precio):
    try:
        precio = Decimal(
            str(precio).strip()
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ) as error:

        raise ValueError(
            "El precio debe ser un número válido."
        ) from error

    if precio < 0:
        raise ValueError(
            "El precio no puede ser negativo."
        )

    return precio.quantize(
        Decimal("0.01")
    )


# ============================================================
# PRODUCTOS
# ============================================================

def listar_productos():

    consulta = CONSULTA_PRODUCTOS + """
        GROUP BY
            p.id_producto,
            p.codigo,
            p.nombre,
            c.nombre,
            p.unidad_medida,
            p.precio,
            p.stock_minimo

        ORDER BY
            p.nombre;
    """

    return _consultar_lista(
        consulta
    )


def buscar_productos(texto_busqueda):

    texto = texto_busqueda.strip()

    if not texto:
        return listar_productos()

    patron = f"%{texto}%"

    consulta = CONSULTA_PRODUCTOS + """
        AND (
            p.codigo LIKE ?
            OR p.nombre LIKE ?
        )

        GROUP BY
            p.id_producto,
            p.codigo,
            p.nombre,
            c.nombre,
            p.unidad_medida,
            p.precio,
            p.stock_minimo

        ORDER BY
            p.nombre;
    """

    return _consultar_lista(
        consulta,
        (
            patron,
            patron
        )
    )


def obtener_producto_por_id(id_producto):

    conexion = None
    cursor = None

    consulta = """
        SELECT
            p.id_producto,
            p.codigo,
            p.nombre,
            p.descripcion,
            p.id_categoria,

            c.nombre AS categoria,

            p.unidad_medida,

            p.precio,

            COALESCE(
                SUM(e.cantidad),
                0
            ) AS stock_actual,

            p.stock_minimo,

            CASE
                WHEN COALESCE(
                    SUM(e.cantidad),
                    0
                ) = 0
                    THEN 'Agotado'

                WHEN COALESCE(
                    SUM(e.cantidad),
                    0
                ) <= p.stock_minimo
                    THEN 'Stock bajo'

                ELSE 'Normal'
            END AS estado

        FROM productos AS p

        INNER JOIN categorias AS c
            ON c.id_categoria =
               p.id_categoria

        LEFT JOIN existencias AS e
            ON e.id_producto =
               p.id_producto
            AND e.fecha_eliminacion IS NULL

        WHERE
            p.id_producto = ?
            AND p.fecha_eliminacion IS NULL

        GROUP BY
            p.id_producto,
            p.codigo,
            p.nombre,
            p.descripcion,
            p.id_categoria,
            c.nombre,
            p.unidad_medida,
            p.precio,
            p.stock_minimo;
    """

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute(consulta, id_producto)

        fila = cursor.fetchone()

        if fila is None:
            return None

        return _filas_a_diccionarios(
            cursor,
            [fila]
        )[0]

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def ver_ubicaciones_producto(id_producto):

    consulta = """
        SELECT
            u.id_ubicacion,
            u.codigo_ubicacion,
            u.seccion,
            u.pasillo,
            u.estante,
            u.nivel,
            e.cantidad

        FROM existencias AS e

        INNER JOIN ubicaciones AS u
            ON u.id_ubicacion =
               e.id_ubicacion

        WHERE
            e.id_producto = ?
            AND e.fecha_eliminacion IS NULL
            AND u.fecha_eliminacion IS NULL
            AND u.estado = 1

        ORDER BY
            u.codigo_ubicacion;
    """

    return _consultar_lista(
        consulta,
        (id_producto,)
    )


def registrar_producto(
        codigo,
        nombre,
        descripcion,
        id_categoria,
        unidad_medida,
        precio,
        stock_minimo):

    codigo = codigo.strip()
    nombre = nombre.strip()

    descripcion = (
        descripcion.strip()
        if descripcion
        else None
    )

    unidad_medida = (
        unidad_medida.strip()
    )

    if not codigo:
        raise ValueError(
            "El código es obligatorio."
        )

    if not nombre:
        raise ValueError(
            "El nombre es obligatorio."
        )

    if not unidad_medida:
        raise ValueError(
            "La unidad de medida es obligatoria."
        )

    try:
        id_categoria = int(
            id_categoria
        )

        stock_minimo = int(
            stock_minimo
        )

    except (TypeError, ValueError) as error:
        raise ValueError(
            "La categoría y el stock mínimo "
            "deben ser números enteros."
        ) from error

    precio = _validar_precio(
        precio
    )

    if stock_minimo < 0:
        raise ValueError(
            "El stock mínimo no puede ser negativo."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM productos

            WHERE
                codigo = ?
                AND fecha_eliminacion IS NULL;
        """, codigo)

        if cursor.fetchone() is not None:
            raise ValueError(
                "Ya existe un producto con ese código."
            )

        cursor.execute("""
            SELECT
                estado

            FROM categorias

            WHERE
                id_categoria = ?
                AND fecha_eliminacion IS NULL;
        """, id_categoria)

        categoria = cursor.fetchone()

        if categoria is None:
            raise ValueError(
                "La categoría seleccionada no existe."
            )

        if not categoria.estado:
            raise ValueError(
                "La categoría seleccionada está inactiva."
            )

        cursor.execute("""
            INSERT INTO productos (
                codigo,
                nombre,
                descripcion,
                id_categoria,
                unidad_medida,
                precio,
                stock_minimo,
                estado,
                fecha_creacion
            )

            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                1,
                SYSDATETIME()
            );
        """, codigo, nombre, descripcion, id_categoria, unidad_medida, precio, stock_minimo)

        conexion.commit()

        return True

    except (
        ValueError,
        ConnectionError
    ):
        if conexion is not None:
            conexion.rollback()

        raise

    except pyodbc.IntegrityError as error:

        if conexion is not None:
            conexion.rollback()

        raise ValueError(
            "No fue posible registrar el producto. "
            "Verifica que el código no esté repetido."
        ) from error

    except pyodbc.Error as error:

        if conexion is not None:
            conexion.rollback()

        raise RuntimeError(
            "Ocurrió un error al registrar "
            "el producto en SQL Server."
        ) from error

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def actualizar_producto(
        id_producto,
        codigo,
        nombre,
        descripcion,
        id_categoria,
        unidad_medida,
        precio,
        stock_minimo):

    codigo = codigo.strip()
    nombre = nombre.strip()
    unidad_medida = unidad_medida.strip()

    descripcion = (
        descripcion.strip()
        if descripcion
        else None
    )

    try:
        id_producto = int(
            id_producto
        )

        id_categoria = int(
            id_categoria
        )

        stock_minimo = int(
            stock_minimo
        )

    except (TypeError, ValueError) as error:
        raise ValueError(
            "La categoría y el stock mínimo "
            "deben ser números enteros."
        ) from error

    precio = _validar_precio(
        precio
    )

    if (
        not codigo
        or not nombre
        or not unidad_medida
    ):
        raise ValueError(
            "Código, nombre y unidad son obligatorios."
        )

    if stock_minimo < 0:
        raise ValueError(
            "El stock mínimo no puede ser negativo."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM productos

            WHERE
                codigo = ?
                AND id_producto <> ?
                AND fecha_eliminacion IS NULL;
        """, codigo, id_producto)

        if cursor.fetchone():
            raise ValueError(
                "Ya existe otro producto con ese código."
            )

        cursor.execute("""
            SELECT
                estado

            FROM categorias

            WHERE
                id_categoria = ?
                AND fecha_eliminacion IS NULL;
        """, id_categoria)

        categoria = cursor.fetchone()

        if categoria is None:
            raise ValueError(
                "La categoría seleccionada no existe."
            )

        if not categoria.estado:
            raise ValueError(
                "La categoría seleccionada está inactiva."
            )

        cursor.execute("""
            UPDATE productos

            SET
                codigo = ?,
                nombre = ?,
                descripcion = ?,
                id_categoria = ?,
                unidad_medida = ?,
                precio = ?,
                stock_minimo = ?,
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_producto = ?
                AND fecha_eliminacion IS NULL;
        """, codigo, nombre, descripcion, id_categoria, unidad_medida, precio, stock_minimo, id_producto)

        if cursor.rowcount == 0:
            raise ValueError(
                "El producto no existe o fue eliminado."
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


def eliminar_producto(id_producto):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            UPDATE productos

            SET
                estado = 0,
                fecha_eliminacion = SYSDATETIME(),
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_producto = ?
                AND fecha_eliminacion IS NULL;
        """, id_producto)

        if cursor.rowcount == 0:
            raise ValueError(
                "El producto no existe o ya fue eliminado."
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
# CATEGORÍAS
# ============================================================

def listar_categorias():

    return _consultar_lista("""
        SELECT
            id_categoria,
            nombre,
            descripcion

        FROM categorias

        WHERE
            estado = 1
            AND fecha_eliminacion IS NULL

        ORDER BY
            nombre;
    """)


def crear_categoria(
        nombre,
        descripcion=None):

    nombre = nombre.strip()

    descripcion = (
        descripcion.strip()
        if descripcion and descripcion.strip()
        else None
    )

    if not nombre:
        raise ValueError(
            "El nombre de la categoría es obligatorio."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM categorias

            WHERE
                nombre = ?
                AND fecha_eliminacion IS NULL;
        """, nombre)

        if cursor.fetchone():
            raise ValueError(
                "Ya existe una categoría con ese nombre."
            )

        cursor.execute("""
            INSERT INTO categorias (
                nombre,
                descripcion,
                estado,
                fecha_creacion
            )

            VALUES (
                ?,
                ?,
                1,
                SYSDATETIME()
            );
        """, nombre, descripcion)

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


def actualizar_categoria(
        id_categoria,
        nombre,
        descripcion=None):

    nombre = nombre.strip()

    descripcion = (
        descripcion.strip()
        if descripcion and descripcion.strip()
        else None
    )

    if not nombre:
        raise ValueError(
            "El nombre de la categoría es obligatorio."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM categorias

            WHERE
                nombre = ?
                AND id_categoria <> ?
                AND fecha_eliminacion IS NULL;
        """, nombre, id_categoria)

        if cursor.fetchone():
            raise ValueError(
                "Ya existe otra categoría con ese nombre."
            )

        cursor.execute("""
            UPDATE categorias

            SET
                nombre = ?,
                descripcion = ?,
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_categoria = ?
                AND fecha_eliminacion IS NULL;
        """, nombre, descripcion, id_categoria)

        if cursor.rowcount == 0:
            raise ValueError(
                "La categoría no existe."
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


def eliminar_categoria(id_categoria):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM productos

            WHERE
                id_categoria = ?
                AND estado = 1
                AND fecha_eliminacion IS NULL;
        """, id_categoria)

        if cursor.fetchone():
            raise ValueError(
                "No se puede eliminar una categoría "
                "con productos activos."
            )

        cursor.execute("""
            UPDATE categorias

            SET
                estado = 0,
                fecha_actualizacion = SYSDATETIME(),
                fecha_eliminacion = SYSDATETIME()

            WHERE
                id_categoria = ?
                AND fecha_eliminacion IS NULL;
        """, id_categoria)

        if cursor.rowcount == 0:
            raise ValueError(
                "La categoría no existe."
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
# UBICACIONES
# ============================================================

def listar_ubicaciones():

    return _consultar_lista("""
        SELECT
            id_ubicacion,
            codigo_ubicacion,
            seccion,
            pasillo,
            estante,
            nivel,
            descripcion

        FROM ubicaciones

        WHERE
            estado = 1
            AND fecha_eliminacion IS NULL

        ORDER BY
            codigo_ubicacion;
    """)


def registrar_ubicacion(
        codigo,
        seccion,
        pasillo=None,
        estante=None,
        nivel=None,
        descripcion=None):

    codigo = codigo.strip()
    seccion = seccion.strip()

    if not codigo:
        raise ValueError(
            "El código de ubicación es obligatorio."
        )

    if not seccion:
        raise ValueError(
            "La sección es obligatoria."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM ubicaciones

            WHERE
                codigo_ubicacion = ?
                AND fecha_eliminacion IS NULL;
        """, codigo)

        if cursor.fetchone():
            raise ValueError(
                "Ya existe una ubicación con ese código."
            )

        cursor.execute("""
            INSERT INTO ubicaciones (
                codigo_ubicacion,
                seccion,
                pasillo,
                estante,
                nivel,
                descripcion,
                estado,
                fecha_creacion
            )

            VALUES (?, ?, ?, ?, ?, ?, 1, SYSDATETIME());
        """, codigo, seccion, pasillo or None, estante or None, nivel or None, descripcion or None)

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


def actualizar_ubicacion(
        id_ubicacion,
        codigo,
        seccion,
        pasillo=None,
        estante=None,
        nivel=None,
        descripcion=None):

    codigo = codigo.strip()
    seccion = seccion.strip()

    if not codigo:
        raise ValueError(
            "El código de ubicación es obligatorio."
        )

    if not seccion:
        raise ValueError(
            "La sección es obligatoria."
        )

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM ubicaciones

            WHERE
                codigo_ubicacion = ?
                AND id_ubicacion <> ?
                AND fecha_eliminacion IS NULL;
        """, codigo, id_ubicacion)

        if cursor.fetchone():
            raise ValueError(
                "Ya existe otra ubicación con ese código."
            )

        cursor.execute("""
            UPDATE ubicaciones

            SET
                codigo_ubicacion = ?,
                seccion = ?,
                pasillo = ?,
                estante = ?,
                nivel = ?,
                descripcion = ?,
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_ubicacion = ?
                AND fecha_eliminacion IS NULL;
        """, codigo, seccion, pasillo or None, estante or None, nivel or None, descripcion or None, id_ubicacion)

        if cursor.rowcount == 0:
            raise ValueError(
                "La ubicación no existe."
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


def eliminar_ubicacion(id_ubicacion):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT 1

            FROM existencias

            WHERE
                id_ubicacion = ?
                AND cantidad > 0
                AND fecha_eliminacion IS NULL;
        """, id_ubicacion)

        if cursor.fetchone():
            raise ValueError(
                "No se puede eliminar una ubicación "
                "con stock activo."
            )

        cursor.execute("""
            UPDATE ubicaciones

            SET
                estado = 0,
                fecha_actualizacion = SYSDATETIME(),
                fecha_eliminacion = SYSDATETIME()

            WHERE
                id_ubicacion = ?
                AND fecha_eliminacion IS NULL;
        """, id_ubicacion)

        if cursor.rowcount == 0:
            raise ValueError(
                "La ubicación no existe."
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
# EXISTENCIAS
# ============================================================

def eliminar_existencia(id_existencia):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            UPDATE existencias

            SET
                fecha_eliminacion = SYSDATETIME(),
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_existencia = ?
                AND fecha_eliminacion IS NULL;
        """, id_existencia)

        if cursor.rowcount == 0:
            raise ValueError(
                "La existencia no existe."
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
