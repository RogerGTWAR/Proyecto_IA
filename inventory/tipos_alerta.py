"""Claves lógicas de alertas y resolución de los identificadores reales de SQL."""
import unicodedata
from core.database import conectar

PROXIMO_AGOTARSE = 'proximo_agotarse'
NOMBRES_LOGICOS = {
    'intrusion_detectada': 'Intrusión detectada',
    'stock_bajo': 'Stock bajo',
    'producto_agotado': 'Producto agotado',
    PROXIMO_AGOTARSE: 'Próximo a agotarse',
    'movimiento_anormal': 'Movimiento anormal',
    'cantidad_inusual': 'Cantidad inusual',
    'horario_inusual': 'Horario inusual',
    'empleado_no_reconocido': 'Empleado no reconocido',
    'lote_proximo_vencer': 'Lote próximo a vencer',
    'lote_vencido': 'Lote vencido',
}


def normalizar_nombre(nombre):
    texto = unicodedata.normalize('NFKD', str(nombre))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return ' '.join(texto.casefold().split())


def obtener_tipo_alerta(clave, cursor=None, obligatorio=True):
    """Resolver nombre o clave estable; no insertar tipos ni asumir sus IDs."""
    nombre = NOMBRES_LOGICOS.get(normalizar_nombre(clave), clave)
    esperado = normalizar_nombre(nombre)
    c = None
    try:
        if cursor is None:
            c = conectar()
            cursor = c.cursor()
        filas = cursor.execute('SELECT id_tipo_alerta,nombre,estado,fecha_eliminacion FROM dbo.tipos_alerta').fetchall()
        candidatos = [r[0] for r in filas if r[2] and r[3] is None
                      and normalizar_nombre(r[1]) == esperado]
        if len(candidatos) > 1:
            raise ValueError(f'Existen tipos de alerta activos equivalentes a {nombre}. Revise el catálogo.')
        if candidatos:
            return candidatos[0]
        if obligatorio:
            raise ValueError(f'El tipo de alerta {nombre} no existe o está inactivo.')
        return None
    finally:
        if c is not None:
            cursor.close()
            c.close()
