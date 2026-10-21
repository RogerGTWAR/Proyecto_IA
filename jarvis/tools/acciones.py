"""Acciones cerradas; las escrituras siguen en los servicios transaccionales."""
from decimal import Decimal


def movimiento(datos):
    from inventory import movimientos
    from jarvis import herramientas_jarvis as herramientas
    from jarvis import jarvis_consultas as consultas
    p = herramientas.datos_producto(datos['id_producto'])
    if p.get('control_lotes'):
        raise ValueError('Este producto requiere seleccionar lote desde Movimientos.')
    if not any(e['id_empleado'] == datos['id_empleado'] for e in consultas.empleados({})):
        raise ValueError('El responsable ya no está activo. Solicita el movimiento de nuevo.')
    ubicaciones = herramientas.datos_ubicaciones(datos['id_producto'])
    if datos.get('origen'):
        origen = next((u for u in ubicaciones if u['id_ubicacion'] == datos['origen']), None)
        if origen is None or Decimal(str(origen['cantidad'])) != datos['stock_anterior']:
            raise ValueError('Las existencias cambiaron. Solicita el movimiento nuevamente.')
    funciones = {
        'Entrada': lambda: movimientos.registrar_entrada(datos['id_empleado'], datos['id_producto'], datos['destino'], datos['cantidad'], observacion='Entrada confirmada mediante JARVIS.'),
        'Salida': lambda: movimientos.registrar_salida(datos['id_empleado'], datos['id_producto'], datos['origen'], datos['cantidad'], observacion='Salida confirmada mediante JARVIS.'),
        'Transferencia': lambda: movimientos.registrar_transferencia(datos['id_empleado'], datos['id_producto'], datos['origen'], datos['destino'], datos['cantidad'], observacion='Transferencia confirmada mediante JARVIS.')}
    identificador = funciones[datos['tipo']]()
    return f"{datos['tipo']} registrada. Movimiento #{identificador}."


def _heredada(nombre):
    def llamar(datos):
        from jarvis.jarvis_consultas import _ejecutar_confirmado_compatibilidad
        return _ejecutar_confirmado_compatibilidad(nombre, datos)
    return llamar


ACCIONES = {nombre: _heredada(nombre) for nombre in
            ('atender_alerta', 'aplicar_conteo', 'ajustar_stock', 'iniciar_vigilancia', 'detener_vigilancia')}
ACCIONES.update({nombre: movimiento for nombre in
                 ('registrar_entrada', 'registrar_salida', 'registrar_transferencia')})
