"""Reglas físicas compartidas; productos y cantidades se obtienen de SQL."""
import re

NUM_ESTANTES = 6
NIVELES_POR_ESTANTE = 2
PRODUCTOS_POR_NIVEL = 2


def numero_fisico(valor):
    return int(re.sub(r'^[EN]', '', str(valor).upper()))


def describir_posicion(ubicacion):
    texto = f'Estante {numero_fisico(ubicacion["estante"])} - Nivel {numero_fisico(ubicacion["nivel"])}'
    if ubicacion.get('posicion') is not None:
        texto += f' - Posición {ubicacion["posicion"]}'
    return texto


def numero_led(estante, nivel, posicion):
    e, n, p = numero_fisico(estante), numero_fisico(nivel), int(posicion)
    if not 1 <= e <= NUM_ESTANTES or not 1 <= n <= NIVELES_POR_ESTANTE or not 1 <= p <= PRODUCTOS_POR_NIVEL:
        raise ValueError('Estante, nivel o posición fuera de la estructura física.')
    return (e-1)*NIVELES_POR_ESTANTE*PRODUCTOS_POR_NIVEL + (n-1)*PRODUCTOS_POR_NIVEL+p


def validar_ubicacion(codigo, estante, nivel):
    try:
        e, n = numero_fisico(estante), numero_fisico(nivel)
        numero_led(e, n, 1)
    except (ValueError, TypeError):
        raise ValueError('Seleccione Estante 1 a 6 y Nivel 1 o 2.')
    estante, nivel = f'{e:02}', f'{n:02}'
    esperado = f'E{estante}-N{nivel}'
    if str(codigo).strip().upper() != esperado:
        raise ValueError('El código de esta ubicación debe ser ' + esperado + '.')
    return esperado, estante, nivel


def asegurar_espacio(cursor, producto_id, ubicacion_id):
    """Reservar la posición con bloqueo de ubicación dentro de la transacción."""
    producto_id=int(producto_id)
    u = cursor.execute('''SELECT estante,nivel,capacidad_productos FROM dbo.ubicaciones
        WITH(UPDLOCK,HOLDLOCK) WHERE id_ubicacion=? AND estado=1 AND fecha_eliminacion IS NULL''', ubicacion_id).fetchone()
    if not u:
        raise ValueError('Ubicación inválida o inactiva.')
    filas = cursor.execute('''SELECT id_producto,posicion FROM dbo.existencias WITH(UPDLOCK,HOLDLOCK)
        WHERE id_ubicacion=? AND fecha_eliminacion IS NULL''', ubicacion_id).fetchall()
    for producto, posicion in filas:
        if producto == producto_id:
            return posicion
    # También reservar espacio para productos agotados: cero unidades no libera la posición.
    if len({f[0] for f in filas}) >= u[2]:
        raise ValueError(f'El Estante {numero_fisico(u[0])} - Nivel {numero_fisico(u[1])} ya tiene los dos espacios de producto ocupados.')
    ocupadas = {f[1] for f in filas}
    return next(p for p in range(1, PRODUCTOS_POR_NIVEL+1) if p not in ocupadas)
