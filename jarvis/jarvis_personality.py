"""Presentación central: datos verificados, contexto temporal y respuestas breves."""
import re
from collections import defaultdict
from core.formato_numerico import format_numero
_turnos_sociales=defaultdict(int)

SOCIALES={
    'saludo':('Hola. ¿Qué necesitas revisar en el almacén?', 'Hola. Estoy listo para ayudarte con el inventario.'),
    'como_estas':('Todo bien por aquí. ¿Qué revisamos?', 'Estoy listo. ¿Qué necesitas revisar?'),
    'agradecimiento':('Con gusto.', 'Cuando quieras.'),
    'despedida':('Hasta luego.',),
    'confirmacion_social':('Perfecto. Aquí estoy si necesitas revisar algo.', 'De acuerdo.'),
    'actividad_social':('Estoy listo para ayudarte con inventario, ubicaciones y análisis.',),
}

def numero(valor):
    return format_numero(valor,compactar=True)

def social(intencion):
    opciones=SOCIALES.get(intencion,('Puedo ayudarte con el inventario y sus ubicaciones.',))
    indice=_turnos_sociales[intencion]; _turnos_sociales[intencion]+=1
    return opciones[indice%len(opciones)]

def mensaje_telegram(modo):
    return {
        'inicio':'Hola. Soy JARVIS, el asistente del sistema de inventario.\n\nPuedo mantenerte informado de las alertas del almacén o podemos conversar directamente. ¿Qué deseas hacer?',
        'conversar':'JARVIS en línea. Adelante, ¿qué necesitas consultar?',
        'salir':'Entendido. Salgo del modo conversación, pero seguiré pendiente de las alertas del sistema.',
        'espera':'Seguiré pendiente del sistema. Te avisaré si detecto algo importante. Para conversar, pulsa «Hablar con JARVIS» o escribe /jarvis.'
    }[modo]


def mensaje_presencia(datos):
    from datetime import datetime
    tipo=datos.get('tipo_evento','')
    frase=('No pude asociar esta persona con ningún empleado registrado.' if tipo=='PERSONA_DESCONOCIDA_HABITACION' else
           'Identificación confirmada.' if tipo=='EMPLEADO_ENTRO_HABITACION' else
           'El empleado dejó de estar visible en la habitación.' if tipo=='EMPLEADO_SALIO_HABITACION' else
           'No puedo comprobar la presencia; revise la conexión de la cámara.')
    titulo='PERSONA NO RECONOCIDA' if tipo=='PERSONA_DESCONOCIDA_HABITACION' else tipo.replace('_',' ')
    lines=[titulo,frase,'Categoría: Presencia']
    fecha=datos.get('fecha_hora')
    if fecha:
        f=datetime.fromisoformat(fecha);lines.extend([f'Fecha: {f:%d/%m/%Y}',f'Hora: {f:%H:%M:%S}'])
    for key,label in (('camara','Cámara'),('zona','Ubicación'),('track_id','Track'),('nombre','Empleado'),('codigo_empleado','Código'),('identidad_texto','Identidad')):
        if datos.get(key) is not None:lines.append(label+': '+str(datos[key]))
    return '\n'.join(lines)


def frase_alerta(tipo):
    t=tipo.upper()
    if 'INTRUSI' in t:return 'Atención. Detecté una persona dentro de la zona restringida.'
    if 'ANOMAL' in t:return 'Detecté un movimiento que se aparta del comportamiento habitual.'
    if 'STOCK BAJO' in t or 'STOCK_BAJO' in t:return 'Conviene revisar este producto; se reporta por debajo del mínimo.'
    return None


def saludar_empleado(nombre):
    return f'Hola, {nombre}. ¿Qué necesitas revisar?'

def prediccion(datos,detalles=False):
    if not datos['datos_suficientes']: return datos['producto']+': '+datos['mensaje']
    dias=datos['dias_restantes_promedio']
    if dias is None: return datos['producto']+': sin consumo reciente. No puedo estimar una fecha de agotamiento.'
    texto=f"{datos['producto']} podría durar aproximadamente {dias:.1f} días con el consumo registrado. Riesgo {datos['riesgo'].lower()}."
    if datos.get('stock_actual') is not None and datos.get('consumo_promedio_diario') is not None:
        texto+=f" Stock: {numero(datos['stock_actual'])}; consumo estimado: {numero(datos['consumo_promedio_diario'])} por día."
    if detalles: texto+=' '+datos['explicacion']
    return texto

def version_voz(texto):
    # Mantener el contenido real, omitir marcas de listas que no aportan al habla.
    return re.sub(r'(?m)^\s*[-•]\s*','',texto).replace(' | ','. ')

def presentar(texto):
    return re.sub(r'^(Claro\.|Sí, lo encontré\.|Por supuesto\.)\s*','',texto.strip())

def respuesta_stock(producto,seguimiento=False):
    cantidad=producto['stock_actual'];unidad=producto['unidad_medida']
    if not cantidad:return 'Está agotado.' if seguimiento else f'{producto["nombre"]} está agotado.'
    unidades={'unidad':'unidades','caja':'cajas','paquete':'paquetes','litro':'litros','galon':'galones','galón':'galones','metro':'metros','kilogramo':'kilogramos'}
    unidad=unidad.lower()
    if cantidad!=1:unidad=unidades.get(unidad,unidad)
    texto=f'Queda{ "n" if cantidad!=1 else ""} {numero(cantidad)} {unidad}'+('.' if seguimiento else f' de {producto["nombre"]}.')
    if cantidad<=producto['stock_minimo']:texto+=f' Stock bajo; mínimo: {numero(producto["stock_minimo"])}.'
    return texto


def respuesta_ubicaciones(filas,describir,producto=None):
    """Redacta datos ya consultados; no obtiene ubicaciones ni calcula stock."""
    if not filas:return 'No tiene existencias localizadas.', 'No tiene existencias localizadas.'
    plurales={'unidad':'unidades','litro':'litros','metro':'metros','caja':'cajas','paquete':'paquetes','galón':'galones','kilogramo':'kilogramos'}
    descripciones=[];lineas=[]
    for fila in filas:
        descripcion=re.sub(r'(?i)\b(almac[eé]n)\s+\1\b',r'\1',describir(fila))
        if fila.get('posicion') is not None and not re.search(r'posici[oó]n',descripcion,re.I):
            descripcion+=f", Posición {fila['posicion']}"
        descripciones.append(descripcion)
        unidad=fila['unidad_medida'].lower()
        if fila['cantidad']!=1:unidad=plurales.get(unidad,unidad)
        lineas.append(f'{descripcion} ({fila["codigo_ubicacion"]}): {numero(fila["cantidad"])} {unidad}.')
    texto=('Está en '+lineas[0]) if len(filas)==1 else f'Se encuentra en {len(filas)} ubicaciones:\n'+'\n'.join('- '+l for l in lineas)
    if producto: texto=producto['nombre']+' '+texto[:1].lower()+texto[1:]
    voz='Está en '+ '; '.join(descripciones[:3])+'.'
    if all(float(f['cantidad'])==0 for f in filas):
        texto+=' Actualmente está agotado; conserva la posición física asignada.'
        voz+=' Actualmente está agotado.'
    if len(filas)>3:voz+=f' Hay {len(filas)} ubicaciones; el detalle está en pantalla.'
    return texto,voz

def respuesta_lista(lineas,tipo):
    return {'respuesta':'\n'.join(lineas) if lineas else 'No hay resultados para esa consulta.',
        'voz':f'Hay {len(lineas)} {tipo}. El detalle está en pantalla.' if lineas else 'No hay resultados para esa consulta.'}
