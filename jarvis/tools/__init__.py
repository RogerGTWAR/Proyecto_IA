"""Catálogo único de herramientas: adaptadores mínimos sobre servicios existentes."""
from threading import RLock
_lock = RLock()


def instalar():
    from jarvis import agente_inventario  # Registrar también las capacidades compatibles antes del primer turno.
    from jarvis import herramientas_jarvis as herramientas
    from jarvis import jarvis_consultas as consultas
    from .acciones import ACCIONES
    from . import eventos
    with _lock:
        from surveillance import presencia_empleados as presencia
        for nombre,funcion,params in (
            ('vigilancia.obtener_ocupacion',presencia.obtener_ocupacion,()),
            ('vigilancia.obtener_presentes',presencia.obtener_presentes,()),
            ('vigilancia.obtener_desconocidos',presencia.obtener_desconocidos,()),
            ('vigilancia.estado_camara',presencia.estado_camara,('camera',))):
            herramientas.registrar(nombre,'Consultar presencia real sin activar cámaras',params,'presencia',funcion)
        for nombre,parametros in (('obtener_eventos_recientes',('limite',)),
                                   ('obtener_eventos_criticos',('limite',)),
                                   ('obtener_ultimo_evento',('tipo',)),
                                   ('obtener_eventos_categoria',('categoria','limite'))):
            herramientas.registrar(nombre,'Consultar eventos reales de la sesión',parametros,
                                   'eventos',getattr(eventos,nombre))
        for dominio in consultas.LECTURAS:
            def leer(filtros, d=dominio):
                return consultas.LECTURAS[d](filtros)
            herramientas.registrar('orquestador_'+dominio, 'Consultar '+dominio,
                                   ('filtros',), dominio, leer)
        herramientas.registrar('sistema_estado','Estado real sin activar dispositivos',(),
                               'sistema',consultas.estado)
        herramientas.registrar('obtener_estado_sistema','Snapshot central de servicios',(),
                               'sistema',consultas.obtener_estado_sistema)
        herramientas.registrar('reporte_generar','Vista previa o exportación',('tipo','filtros','formato'),
                               'reportes',consultas.vista_reporte)
        from integrations.arduino.led_service import servicio_led
        herramientas.registrar('led_producto','Localizar o apagar un producto',('id_producto','encendido'),
                               'leds',servicio_led.por_producto)
        herramientas.registrar('led_apagar_todos','Apagar luces de localización',(),
                               'leds',servicio_led.apagar_todos)
        for nombre, funcion in ACCIONES.items():
            herramientas.registrar(nombre,'Acción confirmada: '+nombre,('datos',),
                                   'acciones',funcion,requiere_confirmacion=True)


def catalogo():
    instalar()
    from jarvis.herramientas_jarvis import obtener_descripciones
    return obtener_descripciones()
