"""Adaptadores del orquestador a servicios existentes; lecturas sin efectos laterales."""
import json
from datetime import datetime
from collections import defaultdict
from decimal import Decimal
from jarvis import herramientas_jarvis as servicios


def productos(filtros):return servicios.datos_inventario()


def empleados(filtros):
    from jarvis.agente_inventario import obtener_empleados_activos
    return obtener_empleados_activos()


def movimientos(filtros):
    f=dict(filtros)
    tipo=f.get('tipo_movimiento')
    if tipo=='Ajuste':f.pop('tipo_movimiento')
    filas=servicios.datos_movimientos(f,f.get('producto'),f.get('empleado'))
    if tipo=='Ajuste':filas=[r for r in filas if r['tipo_movimiento'].startswith('Ajuste')]
    return filas


def alertas(filtros):
    from inventory.alertas import listar_alertas
    return listar_alertas(solo_pendientes=filtros.get('pendientes',True),refrescar=False)


def anomalias(filtros):return servicios.datos_anomalias(filtros)


def conteos(filtros):
    from inventory.conteo_inventario import listar_conteos
    return listar_conteos()


def ubicaciones(filtros):
    from inventory.mapa_almacen import ubicaciones_mapa
    return ubicaciones_mapa()


def vigilancia(filtros):
    from integrations.reporting.reportes import obtener_datos_reporte
    return obtener_datos_reporte('Vigilancia / Intrusiones',
        {'desde':filtros.get('fecha_desde'),'hasta':filtros.get('fecha_hasta')})['filas']


def facial(filtros):
    from inventory.inventario_service import consultar
    filas=consultar("SELECT contenido,fecha_creacion FROM notificaciones_telegram WHERE tipo='facial' ORDER BY fecha_creacion DESC,id_notificacion DESC")
    eventos=[]
    for fila in filas:
        try:datos=json.loads(fila['contenido']).get('datos',{})
        except (ValueError,TypeError):continue
        conocida=bool(datos.get('reconocido') or datos.get('estado_identidad')=='EMPLEADO_RECONOCIDO')
        desconocida=datos.get('estado_identidad') in ('DESCONOCIDO','NO_RECONOCIDO') or datos.get('tipo_evento')=='DESCONOCIDO'
        if (desconocida if filtros.get('identidad')=='desconocida' else conocida):
            if desconocida:datos=dict(datos,nombre='Persona desconocida',estado_identidad='DESCONOCIDO')
            eventos.append(dict(datos,fecha=datos.get('fecha_hora') or fila['fecha_creacion']))
    return eventos


LECTURAS={'productos':productos,'empleados':empleados,'movimientos':movimientos,
    'alertas':alertas,'anomalias':anomalias,'conteos':conteos,'vigilancia':vigilancia,'facial':facial,'ubicaciones':ubicaciones}
FECHAS={'productos':'fecha_creacion','empleados':'fecha_creacion','movimientos':'fecha_movimiento',
    'alertas':'fecha_generacion','anomalias':'fecha','conteos':'fecha','vigilancia':'fecha','facial':'fecha'}
IDS={'productos':'id_producto','empleados':'id_empleado','movimientos':'id_movimiento',
    'alertas':'id_alerta','anomalias':'id_anomalia','conteos':'id_conteo'}


def leer(dominio,filtros):
    # Usar el registro central existente, también para las nuevas capacidades.
    nombre='orquestador_'+dominio
    servicios.registrar(nombre,'Consulta estructurada de '+dominio,('filtros',),dominio,LECTURAS[dominio])
    return [dict(f) for f in servicios.ejecutar(nombre,{'filtros':filtros})]


def fecha(valor):
    if isinstance(valor,datetime):return valor.replace(tzinfo=None)
    if valor is None:return None
    try:return datetime.fromisoformat(str(valor)).replace(tzinfo=None)
    except ValueError:return None


def obtener_estado_sistema():
    from core.system_state import state_manager
    return state_manager.snapshot()


def estado():
    from core.system_state import format_service_state,NAMES
    return {({'SQL':'SQL','TTS':'TTS'}.get(name,NAMES.get(name,name))):format_service_state(value)['text']
            for name,value in obtener_estado_sistema().items()}


def agrupar_cantidades(filas,campo,cantidad,unidad='unidad_medida'):
    """Nunca sumar unidades incompatibles como si fueran una sola magnitud."""
    grupos=defaultdict(Decimal)
    for f in filas:grupos[(str(f.get(campo) or 'Sin información'),str(f.get(unidad) or 'Unidad no informada'))]+=Decimal(str(f.get(cantidad) or 0))
    return grupos


def vista_reporte(tipo,filtros,formato=None):
    from integrations.reporting.reportes import obtener_datos_reporte,exportar_pdf,exportar_excel,ruta_disponible
    r=obtener_datos_reporte(tipo,{'desde':filtros.get('fecha_desde'),'hasta':filtros.get('fecha_hasta'),
        'producto':filtros.get('producto')})
    if not formato:return r,None
    from core.config_manager import ruta
    carpeta=ruta('reportes','carpeta');carpeta.mkdir(parents=True,exist_ok=True)
    archivo=ruta_disponible(carpeta/('JARVIS_'+datetime.now().strftime('%Y%m%d_%H%M%S')+('.pdf' if formato=='PDF' else '.xlsx')))
    (exportar_pdf if formato=='PDF' else exportar_excel)(r,archivo)
    return r,str(archivo)


def ejecutar_confirmado(nombre,datos):
    from jarvis.tools import instalar
    from jarvis.herramientas_jarvis import ejecutar
    instalar()
    return ejecutar(nombre,{'datos':datos},confirmado=True)


def _ejecutar_confirmado_compatibilidad(nombre,datos):
    """Lista cerrada de acciones; cada servicio conserva validaciones/transacción."""
    if nombre=='atender_alerta':
        from inventory.alertas import marcar_alerta_atendida
        filas=alertas({})
        if not any(f['id_alerta']==datos['id_alerta'] for f in filas):raise ValueError('La alerta ya no está pendiente. Vuelve a consultarla.')
        marcar_alerta_atendida(datos['id_alerta']);return 'Alerta marcada como atendida.'
    if nombre=='aplicar_conteo':
        from inventory.conteo_inventario import aplicar_conteo
        aplicar_conteo(datos['id_conteo'],esperado=datos['filas'],empleado_esperado=datos['id_empleado'])
        return 'Conteo aplicado mediante los movimientos de ajuste del sistema.'
    if nombre=='ajustar_stock':
        from inventory.movimientos import registrar_ajuste
        m=registrar_ajuste(datos['id_empleado'],datos['id_producto'],datos['id_ubicacion'],
            datos['cantidad'],observacion='Ajuste confirmado mediante JARVIS.',esperado=datos['stock_anterior'])
        return 'Ajuste registrado.' if m else 'El stock ya coincidía; no se creó un movimiento.'
    if nombre in ('iniciar_vigilancia','detener_vigilancia'):
        from surveillance.vigilancia_yolo import servicio_vigilancia
        from core.config_manager import cargar_configuracion
        actual=servicio_vigilancia.obtener_estado()['activo']
        if actual!=datos['activo']:raise ValueError('El estado de vigilancia cambió. Consulta de nuevo antes de confirmar.')
        if nombre=='detener_vigilancia':servicio_vigilancia.parar();return 'Solicité detener la vigilancia.'
        cfg=cargar_configuracion()['vigilancia']
        if cfg!=datos['configuracion']:raise ValueError('La configuración cambió. Solicita una nueva confirmación.')
        servicio_vigilancia.iniciar(cfg);return 'Solicité iniciar la vigilancia. Consulta su estado para comprobar el arranque.'
    raise ValueError('Esta acción no está habilitada desde JARVIS.')
