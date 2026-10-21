pass
pass
from decimal import Decimal, InvalidOperation

import pyodbc

from core.database import conectar


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
    from inventory.inventario_service import buscar_inventario
    return buscar_inventario()

def buscar_productos(texto_busqueda):
    from inventory.inventario_service import buscar_inventario
    return buscar_inventario(texto_busqueda)

def obtener_producto_por_id(id_producto):
    from inventory.inventario_service import obtener_ficha
    p=obtener_ficha(id_producto)
    p['estado']=p['estado_inventario']
    return p

def ver_ubicaciones_producto(id_producto):

    consulta = """
        SELECT
            u.id_ubicacion,
            u.codigo_ubicacion,
            u.seccion,
            u.pasillo,
            u.estante,
            u.nivel,
            e.cantidad,
            e.posicion

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


def _unidad_id(unidad):
    from inventory.inventario_service import listar_unidades
    r=next((u for u in listar_unidades() if u['nombre'].casefold()==str(unidad).strip().casefold()),None)
    if not r: raise ValueError('Unidad de medida no disponible en el catálogo.')
    return r['id_unidad']

def registrar_producto(codigo,nombre,descripcion,id_categoria,unidad_medida,precio,stock_minimo,**opciones):
    from inventory.inventario_service import guardar_producto
    return guardar_producto(codigo,nombre,descripcion,id_categoria,_unidad_id(unidad_medida),precio,stock_minimo,**opciones)

def actualizar_producto(id_producto,codigo,nombre,descripcion,id_categoria,unidad_medida,precio,stock_minimo,**opciones):
    from inventory.inventario_service import guardar_producto,consultar
    previo=consultar('SELECT control_lotes FROM productos WHERE id_producto=?',id_producto)
    if previo: opciones.setdefault('control_lotes',bool(previo[0]['control_lotes']))
    return guardar_producto(codigo,nombre,descripcion,id_categoria,_unidad_id(unidad_medida),precio,stock_minimo,id_producto=id_producto,**opciones)

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
                fecha_actualizacion = SYSDATETIME()

            WHERE
                id_producto = ?
                AND fecha_eliminacion IS NULL;
        """, id_producto)

        if cursor.rowcount == 0:
            raise ValueError(
                "El producto no existe o ya fue eliminado."
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

            OUTPUT INSERTED.id_categoria

            VALUES (
                ?,
                ?,
                1,
                SYSDATETIME()
            );
        """, nombre, descripcion)

        id_categoria = cursor.fetchone()[0]
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
            descripcion,
            almacen,
            zona

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

    from inventory.organizacion_fisica import validar_ubicacion
    codigo,estante,nivel=validar_ubicacion(codigo,estante,nivel)
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

            OUTPUT INSERTED.id_ubicacion

            VALUES (?, ?, ?, ?, ?, ?, 1, SYSDATETIME());
        """, codigo, seccion, pasillo or None, estante or None, nivel or None, descripcion or None)

        id_ubicacion = cursor.fetchone()[0]
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


def actualizar_ubicacion(
        id_ubicacion,
        codigo,
        seccion,
        pasillo=None,
        estante=None,
        nivel=None,
        descripcion=None):

    from inventory.organizacion_fisica import validar_ubicacion
    codigo,estante,nivel=validar_ubicacion(codigo,estante,nivel)
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


# ============================================================
# EXISTENCIAS
# ============================================================

def eliminar_existencia(id_existencia):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        saldo=cursor.execute('SELECT cantidad FROM existencias WITH(UPDLOCK,HOLDLOCK) WHERE id_existencia=? AND fecha_eliminacion IS NULL',id_existencia).fetchone()
        if saldo and saldo[0]>0:
            raise ValueError('No se puede borrar stock. Registre una salida o un ajuste de inventario.')

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
