"""Bot API de Telegram; credenciales externas y errores sin URLs ni tokens."""
from core.paths import PROJECT_ROOT
import os
import json
import threading
import uuid
import logging
import unicodedata
import queue
import time
import hashlib
import mimetypes
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

BASE = PROJECT_ROOT
LOG = logging.getLogger('telegram')
MAX_INTENTOS = 3
from core.system_state import state_manager


def _redactar(valor):
    texto=str(valor)
    for secreto in _credenciales():
        if secreto:texto=texto.replace(secreto,'[oculto]')
    texto=re.sub(r'https?://[^\s\'"<>]+','[URL ocultada]',texto)
    return texto[:900]


def _error_seguro(error):
    return type(error).__name__+': '+_redactar(error)


def _categoria(tipo):
    normal=_normalizar(tipo).replace(' ','_')
    aliases={'PRUEBA':'sistema','TEST':'sistema','SISTEMA':'sistema','INVENTARIO':'inventario',
        'STOCK':'inventario','ALERTAS':'alertas','PREDICCION':'prediccion','EMPLEADOS':'facial',
        'ANOMALIA':'anomalias','ANOMALIAS':'anomalias',
        'INTRUSION':'vigilancia','VIGILANCIA':'vigilancia','FACIAL':'facial','RECONOCIMIENTO_FACIAL':'facial'}
    if normal not in aliases:raise ValueError('Tipo de notificación inválido: '+str(tipo))
    return aliases[normal]


def _filtro(config,tipo,nivel):
    if not config['habilitado']:return 'Telegram desactivado'
    if not config.get(tipo,False):return 'categoría desactivada'
    if not permitido(config,tipo,nivel):return 'severidad inferior al mínimo'
    return None


def _filtro_evento(config,tipo,nivel,datos):
    if (datos or {}).get('origen_telegram')=='Alertas' and not config.get('alertas',True):
        return 'categoría Alertas desactivada'
    return _filtro(config,tipo,nivel)


def _credenciales():
    try:
        from dotenv import dotenv_values
        valores = dotenv_values(BASE / '.env', encoding='utf-8')
    except ImportError:
        valores = {}
    return tuple((os.getenv(k) or valores.get(k) or '').strip()
                 for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'))


def estado_telegram():
    token, chat = _credenciales()
    return {'configurado': bool(token and chat),
            'token_configurado':bool(token),'chat_configurado':bool(chat),
            'estado': state_manager.get('TELEGRAM').status,
            'detalle': state_manager.get('TELEGRAM').message}


def _peticion_api(metodo,datos,files=None,timeout=20):
    """Transporte compartido por entregas y listener; nunca registra la URL."""
    import requests
    token,_=_credenciales()
    return requests.post('https://api.telegram.org/bot'+token+'/'+metodo,
        data=datos,files=files,timeout=(5,timeout),allow_redirects=False)


def consultar_bot(metodo,datos=None,timeout=20):
    """Lecturas Bot API; getUpdates solo lo consume telegram_bot_service."""
    if metodo not in ('getUpdates','getWebhookInfo','getMe','getChat'):raise ValueError('Lectura de bot inválida.')
    if not all(_credenciales()):return dict(ok=False,detalle='Telegram sin configurar.')
    try:
        r=_peticion_api(metodo,datos or {},timeout=timeout)
        cuerpo=r.json()
        if not isinstance(cuerpo,dict):raise ValueError('Respuesta no válida.')
        ok=r.status_code==200 and cuerpo.get('ok') is True
        return dict(ok=ok,http=r.status_code,result=cuerpo.get('result') if ok else None,
            retry_after=cuerpo.get('parameters',{}).get('retry_after',5),
            detalle='Consulta confirmada.' if ok else 'Telegram rechazó la lectura (HTTP '+str(r.status_code)+').')
    except Exception as error:
        LOG.warning('[TELEGRAM BOT] fallo de transporte: %s',type(error).__name__)
        return dict(ok=False,detalle='No se pudo consultar Telegram.')


def enviar_respuesta_chat(chat_id,texto,teclado=None):
    """Texto conversacional sin filtros de alertas; otro chat solo recibe rechazo."""
    _,autorizado=_credenciales()
    if str(chat_id)!=autorizado:
        texto='Chat no autorizado.';teclado=None
    texto=_texto_publico_bot(texto)
    resultados=[]
    for inicio in range(0,len(texto),4000):
        campos={'text':texto[inicio:inicio+4000]}
        if teclado and inicio==0:campos['reply_markup']=json.dumps(teclado,ensure_ascii=False)
        r=_enviar('sendMessage',campos,chat_destino=chat_id)
        resultados.append(r)
        if not r.get('enviado'):break  # No repetir una entrega incierta.
    return dict(enviado=bool(resultados) and all(r.get('enviado') for r in resultados),partes=resultados)


def _texto_publico_bot(texto):
    texto=str(texto).strip()
    # Solo se entrega la respuesta, nunca payloads, trazas ni acciones internas.
    for secreto in _credenciales():
        if secreto and len(secreto)>5:texto=texto.replace(secreto,'[oculto]')
    try:
        from dotenv import dotenv_values
        secretos=dict(dotenv_values(BASE/'.env', encoding='utf-8'));secretos.update(os.environ)
        for clave,valor in secretos.items():
            if valor and len(str(valor))>3 and any(p in clave.upper() for p in ('PASSWORD','SECRET','TOKEN','API_KEY','SQL_PWD')):
                texto=texto.replace(str(valor),'[oculto]')
    except (ImportError,OSError):pass
    texto=re.sub(r'https?://[^\s<>]+','[enlace omitido]',texto)
    texto=re.sub(r'(?:[A-Za-z]:[\\/]|\\\\)[^\n\s]+','[ruta interna]',texto)
    texto=re.sub(r'(?<!\w)/(?:home|tmp|var|Users|mnt)/[^\n\s]+','[ruta interna]',texto)
    texto=re.sub(r'(?i)\b(?:password|pwd|token|uid|server|database)\s*=\s*[^;\n]+','[credencial omitida]',texto)
    return texto or 'No se obtuvo una respuesta de texto.'


def _reportar_transporte(success,message,temporary=False):
    from core.config_manager import obtener
    worker=bool(servicio_telegram.hilo and servicio_telegram.hilo.is_alive())
    current=state_manager.get('TELEGRAM')
    status='ONLINE' if success and worker else 'DEGRADED' if success or temporary else 'ERROR'
    enabled=obtener('telegram','habilitado')
    if not enabled:status='DISABLED'
    state_manager.update('TELEGRAM',status,message,
        details={'enabled':enabled,'worker_running':worker,'chat_configured':True,'last_delivery':success},
        available=enabled and worker and (success or temporary and current.available),error=None if success else 'TELEGRAM_REQUEST_FAILED')


def _enviar(metodo, campos, archivo=None, campo=None,chat_destino=None):
    if metodo not in ('sendMessage','sendPhoto','sendVideo'):
        return _enviar_observado(metodo,campos,archivo,campo,chat_destino)
    from core.audit_service import operation
    with operation('TELEGRAM',metodo) as record:
        result=_enviar_observado(metodo,campos,archivo,campo,chat_destino)
        record.update(status='SUCCESS' if result.get('enviado') else 'FAILED',
            error_type=None if result.get('enviado') else 'TelegramDeliveryError',
            error_message=None if result.get('enviado') else result.get('detalle','Delivery not confirmed'),
            data={k:result[k] for k in ('http','ok','message_id','incierto','reintentable','detalle') if k in result})
        return result


def _enviar_observado(metodo, campos, archivo=None, campo=None,chat_destino=None):
    state_manager.set_activity('TELEGRAM','SENDING' if metodo!='getChat' else 'PROCESSING')
    token, chat = _credenciales()
    LOG.info('[TELEGRAM CONFIG] token_configurado=%s chat_id_configurado=%s archivo_env=%s origen_token=%s origen_chat=%s',
        bool(token),bool(chat),BASE/'.env','entorno' if os.getenv('TELEGRAM_BOT_TOKEN') else '.env',
        'entorno' if os.getenv('TELEGRAM_CHAT_ID') else '.env')
    if not token or not chat:
        LOG.error('[TELEGRAM ERROR] Faltan token o chat_id en runtime.')
        state_manager.update('TELEGRAM','OFFLINE','Telegram sin configuración de conexión.',
            details={'chat_configured':bool(chat)},activity='IDLE',expected=True)
        return {'enviado': False,'reintentable':False,'detalle': 'Telegram no configurado: falta token o chat_id en runtime.'}
    import requests
    fichero = None
    try:
        datos = dict(campos, chat_id=chat if chat_destino is None else chat_destino)
        ficheros = None
        if archivo is not None:
            ruta = Path(archivo)
            LOG.info('[TELEGRAM PHOTO/VIDEO] ruta=%s existe=%s tamaño=%s',_redactar(ruta),ruta.is_file(),ruta.stat().st_size if ruta.is_file() else 0)
            limite = (45 if campo=='video' else 10)*1024*1024
            if not ruta.is_file() or ruta.stat().st_size > limite:
                return {'enviado': False, 'detalle': 'Archivo ausente o demasiado grande para Telegram.'}
            try:fichero = ruta.open('rb')
            except OSError:
                return {'enviado':False,'reintentable':False,'detalle':'No se pudo abrir el adjunto; evidencia original conservada.'}
            mime = mimetypes.guess_type(ruta.name)[0] or 'application/octet-stream'
            ficheros = {campo: (ruta.name, fichero, mime)}
        LOG.info('[TELEGRAM API] %s...',metodo)
        respuesta = _peticion_api(metodo,datos,files=ficheros)
        try:cuerpo=respuesta.json()
        except (ValueError,TypeError):cuerpo={}
        if not isinstance(cuerpo,dict):cuerpo={}
        LOG.info('[TELEGRAM API] metodo=%s HTTP=%s ok=%s',metodo,respuesta.status_code,cuerpo.get('ok'))
        if respuesta.status_code != 200:
            _reportar_transporte(False,'Telegram rechazó la solicitud.',temporary=respuesta.status_code==429 or respuesta.status_code>=500)
            descripcion=_redactar(cuerpo.get('description') or getattr(respuesta,'text','Respuesta sin descripción'))
            LOG.error('[TELEGRAM ERROR] HTTP=%s respuesta=%s',respuesta.status_code,descripcion)
            return {'enviado': False, 'reintentable':respuesta.status_code==429 or respuesta.status_code>=500,
                    'http':respuesta.status_code,'ok':False,'detalle': f'Telegram: error HTTP {respuesta.status_code}: '+descripcion}
        if cuerpo.get('ok') is not True:
            _reportar_transporte(False,'Telegram no confirmó la solicitud.')
            descripcion=_redactar(cuerpo.get('description') or getattr(respuesta,'text','Respuesta no válida'))
            LOG.error('[TELEGRAM ERROR] HTTP=%s respuesta=%s',respuesta.status_code,descripcion)
            return {'enviado': False,'http':respuesta.status_code,'ok':False,'reintentable':False,
                    'detalle':'Telegram: respuesta sin ok=True: '+descripcion}
        _reportar_transporte(True,'Solicitud confirmada por Telegram.')
        return {'enviado': True,'http':respuesta.status_code,'ok':True,
                'message_id':cuerpo.get('result',{}).get('message_id'),'detalle': 'Telegram: enviado (HTTP 200, ok=True).' if metodo!='getChat' else 'Conexión comprobada (getChat HTTP 200, ok=True).'}
    except requests.exceptions.ConnectTimeout as error:
        LOG.error('[TELEGRAM ERROR] %s',_error_seguro(error))
        _reportar_transporte(False,'No se pudo conectar con Telegram.',temporary=True)
        return {'enviado':False,'reintentable':True,'detalle':'Tiempo de conexión agotado; se permite reintento limitado.'}
    except Exception as error:
        # La excepción HTTP original puede incluir el token en su URL.
        _reportar_transporte(False,'No se pudo confirmar la entrega.',temporary=True)
        detalle='Telegram: '+_error_seguro(error)
        LOG.error('[TELEGRAM ERROR] %s',detalle)
        return {'enviado': False, 'incierto':True,'detalle': detalle}
    finally:
        if fichero is not None: fichero.close()
        state_manager.set_activity('TELEGRAM','IDLE')



def probar_telegram():
    referencia='diagnostico:texto:'+uuid.uuid4().hex
    return _probar_por_cola('Prueba del sistema','Telegram está funcionando correctamente.',referencia)


def _probar_por_cola(titulo,mensaje,referencia,imagen=None):
    r=notificar_evento('PRUEBA',titulo,mensaje,nivel='INFO',imagen=imagen,referencia=referencia)
    if r.get('estado')!='PENDIENTE':return r
    limite=time.monotonic()+75
    while time.monotonic()<limite:
        estado=servicio_telegram.estado_entrega(referencia)
        if estado and estado.get('estado') in ('ENVIADA','ERROR','OMITIDA','INCIERTO'):
            return dict(estado,referencia=referencia,encolado=True,worker_proceso=True)
        if not servicio_telegram.hilo or not servicio_telegram.hilo.is_alive():
            return dict(enviado=False,estado='ERROR',detalle='El worker de Telegram no está vivo.',referencia=referencia)
        time.sleep(.05)
    return dict(enviado=False,estado='PENDIENTE',detalle='Evento encolado; revise el log del worker.',referencia=referencia)


def probar_envio_telegram_real(imagen):
    """Dos entregas explícitas por la cola real. No se ejecuta al iniciar el sistema."""
    ruta=Path(imagen)
    if not ruta.is_file() or ruta.suffix.lower() not in ('.jpg','.jpeg','.png'):
        raise ValueError('Seleccione una imagen JPG o PNG existente para la comprobación.')
    resultados={'texto':probar_telegram()}
    if not resultados['texto'].get('enviado'):return resultados
    resultados['foto']=_probar_por_cola('Comprobación de fotografía','Fotografía de diagnóstico del sistema.',
        'diagnostico:foto:'+uuid.uuid4().hex,imagen=str(ruta))
    return resultados


def comprobar_conexion():
    """Comprueba credenciales mediante getChat, sin publicar mensajes."""
    resultado=_enviar('getChat', {})
    return resultado


def formatear_evento(evento):
    """Presentación única; los campos adicionales se incluyen solo si existen."""
    from core.formato_numerico import format_numero
    e=dict(evento)
    fecha=e.get('fecha_hora') or e.get('fecha_creacion') or e.get('fecha') or datetime.now().astimezone()
    if isinstance(fecha,str):fecha=datetime.fromisoformat(fecha)
    tipo=e.get('tipo_evento') or 'ALERTA'
    categoria=e.get('categoria','Sistema')
    from jarvis.jarvis_personality import frase_alerta
    frase=frase_alerta(str(tipo))
    niveles={'INFO':'Informativa','INFORMATIVA':'Informativa','BAJA':'Baja','BAJO':'Baja',
        'MEDIA':'Media','MEDIO':'Media','ALTO':'Alta','ALTA':'Alta','CRITICA':'Crítica','CRITICO':'Crítica'}
    lineas=['['+str(tipo).upper()+']',*([frase] if frase else []),'Categoría: '+categoria,'Subtipo: '+str(e.get('subtipo') or tipo),
        f'Fecha: {fecha:%Y-%m-%d}',f'Hora: {fecha:%H:%M:%S}']
    for clave,titulo in (('camara','Cámara'),('zona','Zona')):
        if e.get(clave) is not None:lineas.append(titulo+': '+str(e[clave]))
    lineas.extend(['Módulo: '+str(e.get('modulo') or categoria),
        'Nivel: '+niveles.get(_normalizar(e.get('nivel','INFO')),str(e.get('nivel','INFO')))])
    campos=(('track_id','Track'),('clase','Clase detectada'),('confianza','Confianza YOLO'),
        ('nombre','Empleado'),('codigo_empleado','Código'),('motor_facial','Motor facial'),
        ('similitud_facial','Confianza facial'),('identidad_texto','Identidad'),('producto','Producto'),
        ('codigo','Código producto'),('stock_actual','Stock actual'),('stock_minimo','Stock mínimo'),
        ('riesgo','Riesgo'),('consumo_promedio_diario','Consumo diario'),('dias_restantes_promedio','Cobertura estimada (días)'),
        ('tipo_movimiento','Movimiento'),('cantidad','Cantidad detectada'),('promedio','Promedio previo'),
        ('stock_anterior','Stock anterior en ubicación'),('stock_nuevo','Stock posterior en ubicación'),
        ('desviacion','Desviación'),('score','Score de anomalía'),('empleado','Empleado'),
        ('ubicacion','Ubicación'),('id_movimiento','Movimiento ID'),('referencia_historica','Referencia histórica'),
        ('estado','Estado'),('estado_zona','Estado en zona'),('componente','Componente'),
        ('fecha_agotamiento','Fecha estimada de agotamiento'),('id_evento','Evento'))
    numericos={'confianza','similitud_facial','stock_actual','stock_minimo','consumo_promedio_diario',
        'dias_restantes_promedio','cantidad','promedio','desviacion','score','stock_anterior','stock_nuevo'}
    for clave,titulo in campos:
        if e.get(clave) is not None and e[clave]!='':
            valor=format_numero(e[clave]) if clave in numericos and not isinstance(e[clave],str) else str(e[clave])
            lineas.append(titulo+': '+valor)
    lineas.append('Descripción: '+str(e.get('descripcion') or 'Evento registrado por el sistema.'))
    return '\n'.join(lineas)


def evento_visual(evento):
    e=dict(evento)
    if e.get('fuente_camara'):e['camara']=str(e.get('camara') or 'Cámara')+' ('+str(e['fuente_camara'])+')'
    tipo=e.get('tipo_evento','INTRUSIÓN')
    normal=_normalizar(tipo)
    e.update(tipo_evento=tipo,categoria=e.get('categoria') or ('Vigilancia' if e.get('confianza') is not None else 'Reconocimiento facial'),
        modulo=e.get('modulo') or ('Vigilancia' if e.get('confianza') is not None else 'Reconocimiento facial'),
        subtipo={'INTRUSION':'Entrada a zona restringida','DESCONOCIDO':'Persona no reconocida',
                 'EMPLEADO RECONOCIDO':'Persona identificada'}.get(normal,tipo),
        nivel=e.get('nivel') or ('INFO' if normal=='EMPLEADO RECONOCIDO' else 'ALTA'))
    e.setdefault('descripcion',{'INTRUSION':'Se detectó el ingreso de una persona a la zona restringida.',
        'DESCONOCIDO':'SFace no encontró una coincidencia válida en la base facial.',
        'EMPLEADO RECONOCIDO':'SFace identificó a un empleado registrado en la cámara de vigilancia.'}.get(normal,'Evento visual registrado.'))
    estado=e.get('estado_identidad')
    if estado in ('EMPLEADO_RECONOCIDO','EMPLEADO_INACTIVO'):
        e['identidad_texto']=e.get('nombre') or 'Empleado identificado'
        e['motor_facial']='SFace'
        if estado=='EMPLEADO_INACTIVO':e['estado']='Empleado inactivo'
    elif estado=='NO_RECONOCIDO':e['identidad_texto']='DESCONOCIDO';e['motor_facial']='SFace'
    elif estado in ('BUSCANDO_ROSTRO','VERIFICANDO_IDENTIDAD','DETECTADO'):e['identidad_texto']='Verificando identidad'
    else:e['identidad_texto']='No disponible'
    if e.get('confianza') is not None:e['clase']='persona'
    return e


def generar_snapshot_evento(frame,evento,ruta_salida):
    """Guarda el frame completo recibido, sin sustituciones ni imágenes de reserva."""
    import cv2
    import numpy as np
    if frame is None or not isinstance(frame,np.ndarray) or frame.ndim!=3 or frame.shape[2]!=3 or not frame.size:
        raise ValueError('No hay un frame BGR válido del evento.')
    imagen=frame.copy();alto,ancho=imagen.shape[:2]
    poligono=evento.get('zone_polygon')
    if poligono:
        puntos=np.asarray(poligono,dtype=float)
        if puntos.ndim==2 and puntos.shape[1]==2 and len(puntos)>=3:
            if np.max(puntos)<=1:puntos=puntos*[ancho,alto]
            cv2.polylines(imagen,[puntos.astype(np.int32)],True,(60,100,245),2)
    caja=evento.get('bbox')
    if caja is None and evento.get('caja') is not None:
        x,y,w,h=evento['caja'];caja=[x,y,x+w,y+h]
    if caja is not None:
        x1,y1,x2,y2=map(int,caja)
        cv2.rectangle(imagen,(max(0,x1),max(0,y1)),(min(ancho-1,x2),min(alto-1,y2)),(50,200,240),2)
    from PIL import Image,ImageDraw,ImageFont
    pil=Image.fromarray(cv2.cvtColor(imagen,cv2.COLOR_BGR2RGB));dibujo=ImageDraw.Draw(pil)
    tamano=max(12,min(24,ancho//50));fuente=None
    for archivo in ('C:/Windows/Fonts/segoeui.ttf','DejaVuSans.ttf'):
        try:fuente=ImageFont.truetype(archivo,tamano);break
        except OSError:pass
    fuente=fuente or ImageFont.load_default()
    e=evento_visual(evento)
    lineas=['['+e['tipo_evento']+'] '+str(e.get('fecha_hora') or datetime.now().astimezone().isoformat(timespec='seconds')),
        str(e.get('camara') or 'Cámara sin nombre')+' · '+str(e.get('zona') or 'Zona no especificada'),
        'Identidad: '+e['identidad_texto']+(' · Track '+str(e['track_id']) if e.get('track_id') is not None else '')]
    # Solo se superponen rótulos; se conserva la resolución completa del frame.
    for i,linea in enumerate(lineas):
        y=i*(tamano+7)
        dibujo.rectangle((0,y,ancho,min(alto,y+tamano+7)),fill='#142333')
        dibujo.text((6,y+2),linea,font=fuente,fill='white')
    imagen=cv2.cvtColor(np.asarray(pil),cv2.COLOR_RGB2BGR)
    ruta=Path(ruta_salida);ruta.parent.mkdir(parents=True,exist_ok=True)
    correcto,datos=cv2.imencode('.jpg',imagen,[cv2.IMWRITE_JPEG_QUALITY,94])
    if not correcto:raise OSError('No fue posible codificar el snapshot del evento.')
    auxiliar=ruta.with_suffix('.tmp');auxiliar.write_bytes(datos.tobytes());os.replace(auxiliar,ruta)
    LOG.info('[SNAPSHOT] generado ruta=%s tamaño=%s',_redactar(ruta),ruta.stat().st_size)
    return str(ruta)


def mensaje_evento(evento):
    return formatear_evento(evento_visual(evento))


def enviar_evento(evento, archivo=None, video=False):
    mensaje = mensaje_evento(evento)
    tipo=_normalizar(evento.get('tipo_evento','INTRUSIÓN'))
    categoria='vigilancia' if tipo=='INTRUSION' else 'facial'
    datos=dict(evento,solo_video=bool(video),
        registrar_alerta_facial=tipo=='DESCONOCIDO' and not video and not evento.get('alerta_por_event_bus'))
    if video:datos['recorte']=None;datos['foto_referencia']=referencia_evento_visual(evento)
    return notificar_evento(categoria,evento.get('tipo_evento','Intrusión'),mensaje,
        evento.get('nivel') or ('INFO' if tipo=='EMPLEADO RECONOCIDO' else 'ALTA'),datos=datos,
        imagen=archivo if not video else None,video=archivo if video else None,
        referencia=referencia_evento_visual(evento,video))


def referencia_evento_visual(evento,video=False):
    prefijo='intrusion:' if _normalizar(evento.get('tipo_evento','INTRUSIÓN'))=='INTRUSION' else 'visual:'
    return prefijo+evento['id_evento']+(':video' if video else ':foto')


def _normalizar(texto):
    return unicodedata.normalize('NFKD',str(texto)).encode('ascii','ignore').decode().upper()


def permitido(config,tipo,nivel):
    valores={'BAJA':0,'BAJO':0,'MEDIA':1,'MEDIO':1,'ALTA':2,'ALTO':2,'CRITICA':3,'CRITICO':3}
    umbrales={'TODAS':0,'MEDIO+':1,'ALTO+':2,'CRITICO':3}
    return (config['habilitado'] and config.get(tipo,False) and
            valores.get(_normalizar(nivel),0)>=umbrales[_normalizar(config['nivel_minimo'])])


def _entregar_contenido(datos,conservar):
    """Progreso por adjunto: reintentar un vídeo no repite una foto confirmada."""
    partes=datos.setdefault('_partes',{})
    imagen=Path(datos['imagen']) if datos.get('imagen') else None
    video=Path(datos['video']) if datos.get('video') else None
    foto_valida=bool(imagen and imagen.is_file() and imagen.suffix.lower() in ('.jpg','.jpeg','.png'))
    solo_video=bool(datos.get('datos',{}).get('solo_video'))
    trabajos=[('foto','sendPhoto',imagen,'photo')] if foto_valida else [] if solo_video and video else [('texto','sendMessage',None,None)]
    recorte=Path(datos['datos']['recorte']) if datos.get('datos',{}).get('recorte') else None
    if foto_valida and recorte and recorte.is_file():trabajos.append(('recorte','sendPhoto',recorte,'photo'))
    # Una descripción extensa no se pierde por el límite del caption.
    if foto_valida and len(datos['mensaje'])>1024:
        for i in range(0,len(datos['mensaje']),4000):trabajos.append(('detalle_'+str(i),'sendMessage',None,None))
    elif not foto_valida and not solo_video and len(datos['mensaje'])>4096:
        for i in range(4096,len(datos['mensaje']),4000):trabajos.append(('detalle_'+str(i),'sendMessage',None,None))
    if video:trabajos.append(('video','sendVideo',video,'video'))
    resultados=[]
    for clave,metodo,archivo,campo in trabajos:
        anterior=partes.get(clave,{})
        if anterior.get('enviado') or anterior.get('incierto') or anterior.get('reintentable') is False:
            resultados.append(anterior);continue
        mensaje=datos['mensaje']
        if clave.startswith('detalle_'):
            inicio=int(clave.split('_')[1]);fin=inicio+4000
            if foto_valida and partes.get('texto',{}).get('enviado'):
                inicio=max(inicio,4096)
                if inicio>=min(fin,len(mensaje)):continue
            mensaje=mensaje[inicio:fin]
        if archivo and len(mensaje)>1024:
            mensaje=mensaje[:940].rsplit('\n',1)[0]+'\nDetalle completo en el mensaje adjunto.'
        r=_enviar(metodo,{'caption' if archivo else 'text':mensaje[:1024 if archivo else 4096]},archivo,campo)
        partes[clave]=r
        conservar(datos)
        resultados.append(r)
        if not r['enviado']:
            LOG.warning('[TELEGRAM ERROR %s] referencia=%s HTTP=%s respuesta=%s',
                'VIDEO' if clave=='video' else 'FOTO' if clave in ('foto','recorte') else 'TEXTO',
                datos.get('referencia'),r.get('http'),r['detalle'])
        # Conservar al menos el aviso cuando la foto es rechazada de forma cierta.
        if clave=='foto' and not r['enviado'] and not partes.get('texto',{}).get('enviado') and not partes.get('texto',{}).get('incierto'):
            texto=_enviar('sendMessage',{'text':datos['mensaje'][:4096]})
            partes['texto']=texto;conservar(datos);resultados.append(texto)
    incierto=any(r.get('incierto') for r in resultados)
    fallo=any(not r.get('enviado') for r in resultados)
    datos['_reintentar']=any(not r.get('enviado') and r.get('reintentable',False) for r in resultados) and not incierto
    conservar(datos)
    detalle='; '.join(k+': '+v['detalle'] for k,v in partes.items())
    return {'enviado':not fallo,'incierto':incierto,'reintentable':datos['_reintentar'],
        'detalle':detalle or 'No se produjo una entrega de contenido.'}


class ServicioTelegram:
    """Observa solo IDs posteriores al arranque; SQL conserva cada entrega."""
    def __init__(self):
        self.sesion=uuid.uuid4().hex;self.detener=threading.Event();self.hilo=None
        self.lock=threading.Lock();self.detalle='Notificaciones detenidas.'
        self.base_alertas=None;self.base_anomalias=None
        self.base_movimientos=None;self.movimientos_procesados=set()
        self.cola=queue.Queue(maxsize=200)
        self.encoladas=set();self.reintentos={}
        self.iniciado=datetime.now().astimezone()
        self.directorio=BASE/'outputs'/'telegram'
        self._proxima_observacion=0
        self._log_handler=None
        self._sql_estaba_caido=False
        self.estados={}
        self.estados_stock={}

    def estado_entrega(self,referencia):
        with self.lock:return dict(self.estados.get(referencia,{}))

    def recuperar_estados(self,referencias):
        """Lectura para el historial, sin reencolar ni reenviar entregas."""
        referencias=list(dict.fromkeys(referencias))[:200]
        if not referencias:return
        from inventory.inventario_service import consultar
        filas=consultar('SELECT referencia,estado,detalle,contenido FROM notificaciones_telegram WHERE referencia IN ('+
            ','.join('?' for _ in referencias)+')',*referencias)
        with self.lock:
            for f in filas:
                self.estados[f['referencia']]=dict(estado=f['estado'],detalle=f['detalle'],
                    enviado=f['estado']=='ENVIADA',registrado_sql=True,partes=json.loads(f['contenido']).get('_partes',{}))

    def _publicar_estado(self,referencia,resultado):
        with self.lock:
            self.estados[referencia]=dict(self.estados.get(referencia,{}),**resultado)
            if len(self.estados)>2000:self.estados.pop(next(iter(self.estados)))
        LOG.info('[TELEGRAM] referencia=%s estado_final=%s detalle=%s',referencia,
            resultado.get('estado'),_redactar(resultado.get('detalle','')))
        return resultado

    def iniciar(self):
        with self.lock:
            if self.hilo and self.hilo.is_alive():return
            self.sesion=uuid.uuid4().hex;self.iniciado=datetime.now().astimezone()
            self.base_alertas=None;self.base_anomalias=None;self.base_movimientos=None
            self.movimientos_procesados.clear()
            self.estados_stock.clear()
            self.reintentos.clear();self.encoladas.clear()
            self._proxima_observacion=0;self._sql_estaba_caido=False
            self.directorio.mkdir(parents=True,exist_ok=True)
            if not any(getattr(h,'name',None)=='telegram-central' for h in LOG.handlers):
                manejador=RotatingFileHandler(self.directorio/'servicio.log',maxBytes=1024*1024,backupCount=3,encoding='utf-8')
                manejador.name='telegram-central';manejador.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                LOG.addHandler(manejador);LOG.setLevel(logging.INFO)
                self._log_handler=manejador
            self.detener.clear()
            self.hilo=threading.Thread(target=self._ejecutar_con_limpieza,daemon=True,name='telegram-central')
            self.hilo.start()
            from core.config_manager import obtener
            enabled=obtener('telegram','habilitado')
            state_manager.update('TELEGRAM','STARTING' if enabled else 'DISABLED','Worker iniciado; conexión pendiente de comprobar.' if enabled else 'Notificaciones deshabilitadas.',
                details={'worker_running':True,'enabled':enabled},expected=True)

    def cerrar(self):
        self.detener.set()
        state_manager.update('TELEGRAM','OFFLINE','Servicio detenido.',details={'worker_running':False},activity='IDLE',expected=True)

    def _ejecutar_con_limpieza(self):
        LOG.info('[TELEGRAM] Worker iniciado sesion=%s',self.sesion)
        try:
            while not self.detener.is_set():
                try:
                    self._ejecutar()
                    if not self.detener.is_set():raise RuntimeError('El worker terminó sin solicitud de cierre.')
                except Exception as error:
                    LOG.error('[TELEGRAM ERROR] Worker terminó: %s',_error_seguro(error))
                    self.informar_componente('Worker Telegram',False,'El worker se interrumpió; se intenta recuperar. '+_error_seguro(error))
                    self.detener.wait(2)
        finally:
            LOG.info('[TELEGRAM] Worker detenido sesion=%s',self.sesion)
            if self._log_handler:
                LOG.removeHandler(self._log_handler);self._log_handler.close();self._log_handler=None

    def _guardar(self,tipo,titulo,mensaje,nivel,datos,imagen,video,referencia):
        from core.config_manager import cargar_configuracion
        from core.database import conectar
        config=cargar_configuracion()['telegram']
        motivo=_filtro_evento(config,tipo,nivel,datos)
        estado='OMITIDA' if motivo else 'PENDIENTE'
        LOG.info('[TELEGRAM] referencia=%s telegram_habilitado=%s categoria=%s categoria_habilitada=%s severidad_permitida=%s nivel=%s minimo=%s',
            referencia,config['habilitado'],tipo,config.get(tipo,False),permitido(dict(config,habilitado=True,**{tipo:True}),tipo,nivel),nivel,config['nivel_minimo'])
        if motivo:LOG.warning('[TELEGRAM] Evento omitido: %s referencia=%s',motivo,referencia)
        from core.audit_service import capture_context
        contenido=json.dumps(dict(titulo=titulo,mensaje=mensaje,datos=datos or {},imagen=imagen,video=video,
                                  referencia=referencia,_audit_context=capture_context()),ensure_ascii=False,default=str)
        c=conectar()
        try:
            q=c.cursor()
            q.execute('''IF NOT EXISTS(SELECT 1 FROM dbo.notificaciones_telegram WITH(UPDLOCK,HOLDLOCK) WHERE referencia=?)
                INSERT dbo.notificaciones_telegram(referencia,sesion,tipo,nivel,contenido,estado,detalle)
                VALUES(?,?,?,?,?,?,?)''',referencia,referencia,self.sesion,tipo,nivel,contenido,estado,
                'Evento omitido: '+motivo if motivo else 'Pendiente del trabajador central.')
            c.commit()
        except Exception:c.rollback();raise
        finally:c.close()

    def _omitir(self,tipo,titulo,mensaje,nivel,datos,referencia,motivo):
        self._guardar(tipo,titulo,mensaje,nivel,datos,None,None,referencia)
        from core.database import conectar
        c=conectar()
        try:
            c.cursor().execute("UPDATE notificaciones_telegram SET estado='OMITIDA',detalle=? WHERE referencia=? AND estado='PENDIENTE'",motivo,referencia)
            c.commit()
        finally:c.close()
        self._publicar_estado(referencia,dict(tipo=tipo,estado='OMITIDA',detalle=motivo))

    def notificar(self,tipo,titulo,mensaje,nivel='MEDIA',datos=None,imagen=None,video=None,referencia=None):
        from core.audit_service import audit, capture_context
        original=tipo;tipo=_categoria(tipo)
        LOG.info('[TELEGRAM] Evento recibido tipo=%s referencia=%s categoria=%s nivel=%s',original,referencia,tipo,nivel)
        if not referencia or len(referencia)>180:raise ValueError('La notificación requiere una referencia estable de hasta 180 caracteres.')
        if not str(mensaje).startswith('[') or '\nCategoría:' not in str(mensaje):
            e=dict(datos or {})
            e.update(categoria={'inventario':'Inventario','alertas':'Inventario','prediccion':'Predicción','anomalias':'Inventario','facial':'Empleados',
                'vigilancia':'Vigilancia','sistema':'Sistema'}[tipo],subtipo=str(titulo),nivel=nivel,
                descripcion=str(mensaje),modulo={'inventario':'Alertas','alertas':'Alertas','prediccion':'Predicción','anomalias':'Anomalías','facial':'Empleados',
                'vigilancia':'Vigilancia','sistema':'Estado del sistema'}[tipo])
            e.setdefault('tipo_evento','RIESGO DE AGOTAMIENTO' if e.get('riesgo') else
                'ERROR DEL SISTEMA' if tipo=='sistema' and _normalizar(nivel) in ('ALTA','ALTO','CRITICO','CRITICA') else
                'ANOMALÍA' if tipo=='anomalias' else 'ALERTA')
            mensaje=formatear_evento(e)
        evento=dict(tipo=tipo,titulo=str(titulo),mensaje=str(mensaje),nivel=nivel,datos=datos or {},
            imagen=str(imagen) if imagen else None,video=str(video) if video else None,referencia=referencia)
        evento['_audit_context']=capture_context()
        if (datos or {}).get('registrar_alerta_facial'):evento['_crear_alerta_facial']=True
        with self.lock:
            if referencia in self.encoladas:
                audit.record('TELEGRAM','NOTIFICATION_DUPLICATE','SKIPPED',data={'reference':referencia})
                LOG.info('[TELEGRAM] duplicado=True referencia=%s ya en cola',referencia)
                return dict(enviado=False,estado='PENDIENTE',detalle='Evento ya encolado.')
            try:self.cola.put_nowait(evento)
            except queue.Full:
                audit.record('TELEGRAM','NOTIFICATION_ENQUEUE','FAILED',level='ERROR',data={'reference':referencia,'reason':'queue_full'})
                LOG.error('Cola central saturada; evento original conservado. Referencia: %s',referencia)
                return dict(enviado=False,estado='ERROR',detalle='Cola saturada; evidencia original conservada.')
            self.encoladas.add(referencia)
            audit.record('TELEGRAM','NOTIFICATION_ENQUEUED',data={'reference':referencia,'type':tipo})
            self.estados[referencia]=dict(enviado=False,estado='PENDIENTE',tipo=tipo,detalle='Telegram: pendiente en la cola central.')
            LOG.info('[TELEGRAM] duplicado=False agregado a cola referencia=%s pendientes=%s worker_vivo=%s',referencia,self.cola.qsize(),bool(self.hilo and self.hilo.is_alive()))
        return dict(enviado=False,estado='PENDIENTE',detalle='Encolado en el servicio central.',referencia=referencia)

    def informar_componente(self,nombre,correcto,detalle):
        """Una notificación por caída; una recuperación permite una nueva caída."""
        from core.eventos_servicios import informar_estado_componente
        informar_estado_componente(nombre,correcto,detalle)

    def _registro_local(self,evento):
        self.directorio.mkdir(parents=True,exist_ok=True)
        ruta=self.directorio/(hashlib.sha256(evento['referencia'].encode()).hexdigest()+'.json')
        auxiliar=ruta.with_suffix('.tmp')
        auxiliar.write_text(json.dumps(dict(evento,sesion=self.sesion,fecha=datetime.now().astimezone().isoformat()),
            ensure_ascii=False,default=str),encoding='utf-8')
        os.replace(auxiliar,ruta)

    def _procesar_evento(self,evento):
        from core.audit_service import use_context, operation
        with use_context(evento.get('_audit_context'),origin='automatic'):
            with operation('TELEGRAM','NOTIFICATION_PROCESS',data={'reference':evento.get('referencia',evento.get('_entrega'))}) as record:
                result=self._procesar_evento_observado(evento)
                if result is False:record['status']='FAILED'
                return result

    def _procesar_evento_observado(self,evento):
        LOG.info('[TELEGRAM WORKER] procesando referencia=%s',evento.get('referencia',evento.get('_entrega')))
        if '_entrega' in evento:
            from core.database import conectar
            c=conectar()
            try:
                c.cursor().execute("UPDATE notificaciones_telegram SET estado='PENDIENTE' WHERE referencia=? AND sesion=? AND estado='ERROR' AND intentos<?",
                    evento['_entrega'],self.sesion,MAX_INTENTOS);c.commit()
            finally:c.close()
            self.entregar(evento['_entrega'])
            return
        referencia=evento['referencia']
        try:
            if evento.get('_frame') is not None:
                import cv2
                carpeta=BASE/'outputs'/'eventos'/('desconocidos' if evento.get('_crear_alerta_facial') or evento['datos'].get('estado_identidad')=='NO_RECONOCIDO' else 'empleados')
                carpeta.mkdir(parents=True,exist_ok=True)
                foto=carpeta/(hashlib.sha256(referencia.encode()).hexdigest()+'.jpg')
                try:
                    evento['imagen']=generar_snapshot_evento(evento['_frame'],evento['datos'],foto)
                    caja=evento['datos'].get('caja')
                    if caja is not None:
                        x,y,w,h=map(int,caja[:4]);frame=evento['_frame']
                        crop=frame[max(0,y):min(frame.shape[0],y+h),max(0,x):min(frame.shape[1],x+w)]
                        if crop.size:
                            ruta=foto.with_name(foto.stem+'_rostro.jpg')
                            ok,contenido=cv2.imencode('.jpg',crop)
                            if ok:
                                ruta.write_bytes(contenido.tobytes());evento['datos']['recorte']=str(ruta)
                except Exception as error:LOG.warning('Evidencia facial no disponible: %s',_error_seguro(error))
                evento.pop('_frame',None)
            if evento.pop('_crear_alerta_facial',False):
                from inventory.alertas import registrar_alerta_empleado_no_reconocido
                try:
                    alerta=registrar_alerta_empleado_no_reconocido()
                    evento['datos']['id_alerta']=alerta['id_alerta']
                except Exception:
                    evento['_crear_alerta_facial']=True
                    raise
            self._guardar(*(evento[k] for k in ('tipo','titulo','mensaje','nivel','datos','imagen','video','referencia')))
            if evento.get('_entrega_local'):
                from core.database import conectar
                c=conectar()
                try:
                    r=evento['_entrega_local']
                    c.cursor().execute('UPDATE notificaciones_telegram SET estado=?,detalle=?,fecha_envio=CASE WHEN ?=\'ENVIADA\' THEN SYSDATETIME() ELSE fecha_envio END WHERE referencia=?',
                        r['estado'],r['detalle'][:500],r['estado'],evento['referencia']);c.commit()
                finally:c.close()
            else:self.entregar(evento['referencia'])
            LOG.info('Evento registrado: %s · %s',evento['tipo'],evento['referencia'])
            self.reintentos.pop(referencia,None)
            ruta=self.directorio/(hashlib.sha256(evento['referencia'].encode()).hexdigest()+'.json')
            ruta.unlink(missing_ok=True)
            return True
        except Exception as error:
            self._publicar_estado(evento['referencia'],dict(enviado=False,estado='ERROR',detalle='Telegram: error de registro/proceso: '+_error_seguro(error)))
            evento['_intentos_registro']=evento.get('_intentos_registro',0)+1
            # La alerta de SQL debe poder salir aunque SQL sea precisamente el servicio caído.
            local=evento.get('_entrega_local')
            if (evento['tipo']=='sistema' and evento['datos'].get('componente')=='SQL' and
                    (not local or local.get('reintentable') and evento['_intentos_registro']<=MAX_INTENTOS)):
                from core.config_manager import cargar_configuracion
                if permitido(cargar_configuracion()['telegram'],'sistema',evento['nivel']):
                    self._registro_local(evento)
                    r=_enviar('sendMessage',{'text':evento['mensaje'][:4096]})
                    evento['_entrega_local']=dict(r,estado='ENVIADA' if r['enviado'] else 'INCIERTO' if r.get('incierto') else 'ERROR')
            self._registro_local(evento)
            if evento['_intentos_registro']<MAX_INTENTOS:
                self.reintentos[referencia]=(time.monotonic()+min(60,5*evento['_intentos_registro']),evento)
            LOG.warning('Registro pendiente de SQL: %s; evidencia local conservada.',referencia)
            return False
        finally:
            with self.lock:self.encoladas.discard(referencia)

    def entregar(self,referencia):
        from core.database import conectar
        from core.config_manager import cargar_configuracion
        c=conectar()
        try:
            q=c.cursor()
            fila=q.execute('SELECT tipo,nivel,estado,contenido FROM dbo.notificaciones_telegram WHERE referencia=?',referencia).fetchone()
            if not fila:return dict(enviado=False,detalle='Notificación no encontrada.')
            tipo,nivel,estado,contenido=fila
            datos=json.loads(contenido)
            from core.audit_service import use_context, operation
            with use_context(datos.get('_audit_context')):
                with operation('TELEGRAM','NOTIFICATION_DELIVERY',data={'reference':referencia}) as record:
                    result=self._entregar_registro(referencia,c,q,tipo,nivel,estado,datos)
                    record['status']=('SKIPPED' if estado!='PENDIENTE' or result.get('estado') in ('OMITIDA','PENDIENTE','ENVIANDO')
                                      else 'SUCCESS' if result.get('enviado') else 'FAILED')
                    record['data']=dict(reference=referencia,delivery_state=result.get('estado'),
                                        http=result.get('http'),detail=result.get('detalle'))
                    return result
        except Exception:c.rollback();raise
        finally:c.close()

    def _entregar_registro(self,referencia,c,q,tipo,nivel,estado,datos):
        from core.config_manager import cargar_configuracion
        motivo=_filtro_evento(cargar_configuracion()['telegram'],tipo,nivel,datos.get('datos',{}))
        LOG.info('[TELEGRAM] referencia=%s duplicado=%s estado_sql=%s',referencia,estado=='ENVIADA',estado)
        if estado!='PENDIENTE':
            motivo=motivo if estado=='OMITIDA' else None
            return self._publicar_estado(referencia,dict(enviado=estado=='ENVIADA',estado=estado,registrado_sql=True,detalle='Evento omitido: '+motivo if motivo else 'Telegram: '+estado.lower()))
        if motivo:
            q.execute("UPDATE dbo.notificaciones_telegram SET estado='OMITIDA',detalle=N'Desactivada por configuración' WHERE referencia=? AND estado='PENDIENTE'",referencia)
            c.commit();return self._publicar_estado(referencia,dict(enviado=False,estado='OMITIDA',registrado_sql=True,detalle='Evento omitido: '+motivo))
        principal=datos.get('datos',{}).get('foto_referencia')
        if principal:
            foto=q.execute('SELECT estado FROM notificaciones_telegram WHERE referencia=?',principal).fetchone()
            if not foto or foto[0] in ('PENDIENTE','ENVIANDO'):
                return self._publicar_estado(referencia,dict(enviado=False,estado='PENDIENTE',registrado_sql=True,detalle='Clip pendiente: esperando el envío de la foto principal.'))
        tomada=q.execute("""UPDATE dbo.notificaciones_telegram SET estado='ENVIANDO',intentos=intentos+1
            OUTPUT INSERTED.id_notificacion WHERE referencia=? AND estado='PENDIENTE' AND intentos<?""",referencia,MAX_INTENTOS).fetchone()
        c.commit()
        if not tomada:return dict(enviado=False,detalle='La notificación ya está siendo procesada.')
        def conservar(contenido):
            q.execute('UPDATE notificaciones_telegram SET contenido=? WHERE referencia=?',
                json.dumps(contenido,ensure_ascii=False,default=str),referencia)
            c.commit()
        r=_entregar_contenido(datos,conservar)
        estado='ENVIADA' if r['enviado'] else 'INCIERTO' if r.get('incierto') else 'ERROR'
        q.execute('''UPDATE dbo.notificaciones_telegram SET estado=?,detalle=?,
            fecha_envio=CASE WHEN ?='ENVIADA' THEN SYSDATETIME() ELSE fecha_envio END WHERE id_notificacion=?''',
            estado,r['detalle'][:500],estado,int(tomada[0]))
        c.commit()
        LOG.info('Entrega %s · %s · %s',referencia,estado,datetime.now().isoformat(timespec='seconds'))
        partes=datos.get('_partes',{})
        detalle='; '.join(k+': '+v['detalle'] for k,v in partes.items())
        return self._publicar_estado(referencia,dict(r,estado=estado,detalle=detalle or r['detalle'],partes=partes,registrado_sql=True))

    def reintentar_errores(self):
        from core.database import conectar
        c=conectar()
        try:
            q=c.cursor();filas=q.execute("UPDATE dbo.notificaciones_telegram SET estado='PENDIENTE',sesion=? OUTPUT INSERTED.referencia WHERE estado='ERROR' AND intentos<?",self.sesion,MAX_INTENTOS).fetchall()
            c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
        return len(filas)

    def _observar(self):
        from inventory.inventario_service import consultar
        alertas=consultar('''SELECT a.id_alerta,a.id_producto,a.id_movimiento,a.mensaje,a.nivel,a.fecha_creacion,a.atendida,
            ta.nombre tipo,p.nombre producto,p.codigo,v.stock_actual,v.stock_minimo,
            an.id_anomalia FROM alertas a LEFT JOIN tipos_alerta ta ON ta.id_tipo_alerta=a.id_tipo_alerta
            LEFT JOIN productos p ON p.id_producto=a.id_producto LEFT JOIN vw_inventario v ON v.id_producto=a.id_producto
            OUTER APPLY(SELECT TOP 1 ai.id_anomalia FROM anomalias_inventario ai
                JOIN detalle_movimientos d ON d.id_detalle=ai.id_detalle
                WHERE d.id_movimiento=a.id_movimiento AND d.id_producto=a.id_producto ORDER BY ai.id_anomalia) an
            WHERE a.id_alerta>? AND a.fecha_eliminacion IS NULL AND LEFT(a.mensaje,10)<>'[intrusion:'
            AND NOT EXISTS(SELECT 1 FROM notificaciones_telegram n WHERE n.referencia=CONCAT('alerta:',a.id_alerta))''',self.base_alertas)
        for a in alertas:
            if self.detener.is_set():return
            tipo=_normalizar(a['tipo']);categoria='facial' if 'RECONOC' in tipo else 'anomalias' if any(t in tipo for t in ('INUSUAL','ANORMAL')) else 'prediccion' if 'PROXIMO' in tipo else 'inventario' if ('STOCK' in tipo or 'AGOTADO' in tipo) else 'alertas'
            # Solo SFace publica eventos faciales enriquecidos; no se conecta CNN.
            if categoria=='facial':continue
            referencia='alerta:'+str(a['id_alerta'])
            with self.lock:
                if referencia in self.encoladas:continue
            a['origen_telegram']='Alertas'
            estado_stock='AGOTADO' if 'AGOTADO' in tipo else 'BAJO' if 'STOCK BAJO' in tipo else None
            if estado_stock and a.get('id_producto'):
                anterior=self.estados_stock.get(a['id_producto'])
                if anterior==estado_stock:
                    self._omitir(categoria,a['tipo'],a['mensaje'],a['nivel'],a,referencia,'Sin transición de stock')
                    continue
            if categoria=='anomalias' and a.get('id_anomalia'):
                # El hallazgo y su alerta SQL son el mismo movimiento inusual.
                self._omitir('anomalias','Movimiento inusual',a['mensaje'],a['nivel'],a,referencia,'Notificado por el hallazgo asociado')
                continue
            mensaje=formatear_alerta(a)
            if a.get('id_producto'):
                try:
                    from inventory.mapa_almacen import ubicaciones_producto,describir_ubicacion
                    ubicaciones=ubicaciones_producto(a['id_producto'])
                    if ubicaciones:mensaje+='\nUbicación: '+'; '.join(describir_ubicacion(u) for u in ubicaciones)
                except Exception:pass  # El detalle opcional no impide notificar la alerta.
            if 'PROXIMO' in tipo and a.get('id_producto'):
                from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
                try:
                    p=predecir_agotamiento(a['id_producto'],False)
                    if p.get('datos_suficientes'):
                        from core.formato_numerico import format_numero
                        mensaje+='\nConsumo diario: '+format_numero(p['consumo_promedio_diario'])+'\nCobertura estimada: '+format_numero(p['dias_restantes_promedio'])+' días\nRiesgo: '+p['riesgo']
                except Exception:pass
            from core.eventos_servicios import publicar_stock
            from core.event_bus import emitir
            if estado_stock:
                publicar_stock(a['id_producto'],a['stock_actual'],a['stock_minimo'],a.get('producto',''),a.get('codigo',''))
                self.estados_stock[a['id_producto']]=estado_stock
            elif categoria=='prediccion':
                pass  # Las transiciones provienen del servicio de prediccion.
            elif categoria=='anomalias' and a.get('id_anomalia'):
                pass  # El hallazgo persistido tiene su propio evento de dominio.
            elif categoria=='anomalias':
                emitir('MOVIMIENTO_INUSUAL','ANOMALIAS','observador_sql',a['tipo'],mensaje,a['nivel'],referencia,a,deduplicate=True)
            else:
                emitir('ALERTA_CREADA','ALERTAS','observador_sql',a['tipo'],mensaje,a['nivel'],referencia,a,
                       metadata={'externa':True},deduplicate=True)
            self._omitir(categoria,a['tipo'],mensaje,a['nivel'],a,referencia,'Gestionado por el bus central')
        for p in consultar('SELECT id_producto,stock_actual,stock_minimo FROM vw_inventario WHERE activo=1'):
            from core.eventos_servicios import publicar_stock
            publicar_stock(p['id_producto'],p['stock_actual'],p['stock_minimo'])
            if p['stock_actual']>p['stock_minimo']:self.estados_stock[p['id_producto']]='NORMAL'
        pendientes=consultar('''SELECT TOP 100 id_anomalia FROM anomalias_inventario a WHERE id_anomalia>?
            AND NOT EXISTS(SELECT 1 FROM notificaciones_telegram n WHERE n.referencia=CONCAT('anomalia:',a.id_anomalia))
            ORDER BY id_anomalia''',self.base_anomalias)
        if not pendientes:return
        ids={a['id_anomalia'] for a in pendientes}
        from ai.anomalies.deteccion_anomalias import listar_anomalias
        for a in listar_anomalias():
            if self.detener.is_set():return
            if a['id_anomalia'] not in ids:continue
            referencia='anomalia:'+str(a['id_anomalia'])
            if consultar('SELECT id_notificacion FROM notificaciones_telegram WHERE referencia=?',referencia):continue
            from core.eventos_servicios import publicar_anomalia
            publicar_anomalia(a)

    def _observar_movimientos(self):
        """Compatibilidad: el servicio de dominio consume MOVIMIENTO_REGISTRADO."""
        return None

    def _cambio_riesgo(self,producto,movimiento,r):
        """Compatibility entry: the prediction service owns risk events."""
        from core.eventos_servicios import publicar_prediccion
        publicar_prediccion(producto,r,notificar=True)

    def _ejecutar(self):
        from inventory.inventario_service import consultar
        while not self.detener.is_set():
            try:
                ahora=time.monotonic()
                if ahora>=self._proxima_observacion:
                    self._proxima_observacion=ahora+5
                    self._sincronizar_observadores(consultar)
                # Un único consumidor realiza SQL y HTTP, nunca el hilo de Tkinter.
                for _ in range(5):
                    try:evento=self.cola.get_nowait()
                    except queue.Empty:break
                    try:self._procesar_evento(evento)
                    finally:self.cola.task_done()
                for referencia,(cuando,evento) in list(self.reintentos.items()):
                    if cuando<=time.monotonic():
                        self.reintentos.pop(referencia,None);self._procesar_evento(evento)
            except Exception as error:
                self.detalle='No se pudo sincronizar Telegram; los eventos originales se conservan.'
                LOG.error('[TELEGRAM ERROR] ciclo del worker: %s',_error_seguro(error))
            self.detener.wait(.1)

    def _sincronizar_observadores(self,consultar):
        if not state_manager.is_available('SQL'):
            self._sql_estaba_caido=True
            self.detalle='SQL pendiente de comprobación o sin conexión; eventos conservados.'
            return
        try:
            if self._sql_estaba_caido:
                self._sql_estaba_caido=False
                # Recuperación de esta ejecución; nunca recorrer sesiones históricas.
                if self.directorio.is_dir():
                    for ruta in self.directorio.glob('*.json'):
                        e=json.loads(ruta.read_text(encoding='utf-8'))
                        if e.get('sesion')==self.sesion:self._procesar_evento(e)
            if self.base_alertas is None:
                corte=self.iniciado.replace(tzinfo=None)
                fila=consultar('''SELECT ISNULL((SELECT MAX(id_alerta) FROM alertas WHERE fecha_creacion<?),0) alertas,
                    ISNULL((SELECT MAX(id_anomalia) FROM anomalias_inventario WHERE fecha_creacion<? OR fecha_creacion IS NULL),0) anomalias,
                    ISNULL((SELECT MAX(id_movimiento) FROM movimientos WHERE fecha_creacion<?),0) movimientos''',corte,corte,corte)[0]
                self.base_alertas=fila['alertas'];self.base_anomalias=fila['anomalias']
                self.base_movimientos=fila['movimientos']
                for p in consultar('SELECT id_producto,stock_actual,stock_minimo FROM vw_inventario WHERE activo=1'):
                    self.estados_stock[p['id_producto']]=('AGOTADO' if p['stock_actual']<=0 else
                        'BAJO' if p['stock_actual']<=p['stock_minimo'] else 'NORMAL')
                    from core.event_bus import event_bus
                    # La linea base del dominio pertenece al servicio de inventario.
                # Un envío interrumpido no se repite sin conocer su resultado.
                from core.database import conectar
                c=conectar()
                try:
                    c.cursor().execute("UPDATE notificaciones_telegram SET estado='INCIERTO',detalle=N'Envío interrumpido; revisar antes de volver a enviar' WHERE estado='ENVIANDO' AND sesion<>?",self.sesion);c.commit()
                finally:c.close()
            self._observar()
            # Nunca recoger errores o pendientes de sesiones anteriores al arrancar.
            for n in consultar("SELECT referencia,contenido,intentos FROM notificaciones_telegram WHERE sesion=? AND estado='ERROR' AND intentos<? ORDER BY id_notificacion",self.sesion,MAX_INTENTOS):
                datos=json.loads(n['contenido'])
                if not datos.get('_reintentar'):continue
                referencia=n['referencia'];clave='entrega:'+referencia
                cuando=self.reintentos.get(clave)
                if cuando is None:self.reintentos[clave]=(time.monotonic()+5*n['intentos'],{'_entrega':referencia})
            for n in consultar("SELECT TOP 20 referencia FROM notificaciones_telegram WHERE sesion=? AND estado='PENDIENTE' ORDER BY id_notificacion",self.sesion):
                if self.detener.is_set():break
                self.entregar(n['referencia'])
            self.detalle='Servicio activo. Solo eventos nuevos de esta ejecución.'
        except Exception as error:
            self.detalle='No se pudo sincronizar Telegram; los eventos originales se conservan.'
            LOG.error('[TELEGRAM ERROR] observador: %s',_error_seguro(error))


def formatear_alerta(a):
    tipo=_normalizar(a['tipo'])
    titulo=('RIESGO DE AGOTAMIENTO' if 'PROXIMO' in tipo else 'ALERTA')
    return formatear_evento(dict(a,tipo_evento=titulo,categoria='Inventario' if a.get('producto') else 'Sistema',
        subtipo=a['tipo'],modulo='Alertas',descripcion=a['mensaje'],estado='Atendida' if a.get('atendida') else 'Pendiente'))


def formatear_anomalia(a):
    e=dict(a,tipo_evento='ANOMALÍA',categoria='Inventario',subtipo=a.get('tipo_anomalia') or 'Movimiento inusual',
        modulo='Anomalías',descripcion=a['motivo'])
    # Reutilizar los valores ya calculados, sin recalcular ni inventar estadísticas.
    for parte in str(a.get('referencia_historica') or '').split(';'):
        if ':' not in parte:continue
        clave,valor=parte.split(':',1)
        if _normalizar(clave.strip())=='PROMEDIO':e.setdefault('promedio',valor.strip())
        if _normalizar(clave.strip())=='DESVIACION':e.setdefault('desviacion',valor.strip())
    return formatear_evento(e)


def listar_notificaciones():
    from inventory.inventario_service import consultar
    return consultar('SELECT TOP 100 id_notificacion,referencia,tipo,nivel,estado,intentos,detalle,fecha_creacion,fecha_envio FROM notificaciones_telegram ORDER BY id_notificacion DESC')


servicio_telegram=ServicioTelegram()


def notificar_evento(tipo,titulo,mensaje,nivel='MEDIA',datos=None,imagen=None,video=None,referencia=None):
    # También funciona si el evento proviene de una ejecución sin la ventana principal.
    if servicio_telegram.detener.is_set():
        return dict(enviado=False,estado='ERROR',detalle='Telegram: servicio cerrado por la aplicación.')
    servicio_telegram.iniciar()
    return servicio_telegram.notificar(tipo,titulo,mensaje,nivel,datos,imagen,video,referencia)


def informar_estado_componente(nombre,correcto,detalle):
    servicio_telegram.informar_componente(nombre,correcto,detalle)


def notificar_rostro_desconocido(resultado,frame,camara='Cámara facial',zona='Sin zona configurada',referencia=None,crear_alerta=True):
    """Solo identidad SFace desconocida, con rostro evaluado y calidad suficiente."""
    estado=resultado.get('estado_identidad',resultado.get('estado'))
    if str(resultado.get('motor','sface')).lower() not in ('sface','embeddings'):return None
    if estado not in ('DESCONOCIDO','NO_RECONOCIDO') or resultado.get('reconocido'):
        return None
    if resultado.get('calidad_estado') not in (None,'CALIDAD_OK','CALIDAD_ACEPTABLE'):
        return None
    if estado=='NO_RECONOCIDO' and not resultado.get('identidad_evaluada'):return None
    referencia=referencia or 'facial:'+uuid.uuid4().hex
    datos=dict(resultado,tipo_evento='DESCONOCIDO',fecha_hora=datetime.now().astimezone().isoformat(timespec='seconds'),
        camara=camara,zona=zona,estado_identidad='NO_RECONOCIDO',motor_facial='SFace',
        categoria='Empleados',modulo='Empleados',subtipo='Persona no reconocida',clase='rostro',
        descripcion='No se encontró coincidencia facial válida con empleados registrados.',
        similitud_facial=resultado.get('similitud_facial',resultado.get('similitud')))
    datos.pop('confianza',None)  # En el escáner es similitud facial, no una detección YOLO.
    visual=evento_visual(datos);visual.update(tipo_evento='ALERTA',subtipo='Persona no reconocida')
    mensaje=formatear_evento(visual)
    evento=dict(tipo='facial',titulo='Persona no reconocida',mensaje=mensaje,nivel='ALTA',datos=datos,
        imagen=None,video=None,referencia=referencia,_crear_alerta_facial=crear_alerta)
    from core.audit_service import capture_context, audit
    evento['_audit_context']=capture_context()
    if frame is not None:evento['_frame']=frame.copy()
    with servicio_telegram.lock:
        if referencia in servicio_telegram.encoladas:
            audit.record('TELEGRAM','NOTIFICATION_DUPLICATE','SKIPPED',data={'reference':referencia});return None
        try:servicio_telegram.cola.put_nowait(evento)
        except queue.Full:
            LOG.error('Cola saturada; alerta facial no encolada.');return None
        servicio_telegram.encoladas.add(referencia)
        audit.record('TELEGRAM','NOTIFICATION_ENQUEUED',data={'reference':referencia,'type':'facial'})
        servicio_telegram.estados[referencia]=dict(tipo='facial',estado='PENDIENTE',detalle='En cola')
    return dict(encolado=True,estado='PENDIENTE',id_evento=referencia)


def notificar_reconocimiento_empleado(resultado,frame,referencia,camara='Cámara facial'):
    """Recibe la decisión SFace existente; no reclasifica ni calcula confianza."""
    if str(resultado.get('motor','sface')).lower() not in ('sface','embeddings'):return None
    if not resultado.get('reconocido') or not resultado.get('id_empleado') or frame is None:return None
    datos=dict(resultado,tipo_evento='RECONOCIMIENTO FACIAL',categoria='Empleados',modulo='Empleados',
        subtipo='Empleado reconocido',camara=camara,motor_facial='SFace',nivel='INFO',
        estado_identidad='EMPLEADO_RECONOCIDO',
        fecha_hora=datetime.now().astimezone().isoformat(timespec='seconds'),
        similitud_facial=resultado.get('similitud_facial',resultado.get('similitud')),
        descripcion='Se identificó correctamente a un empleado registrado.')
    datos.pop('confianza',None)
    evento=dict(tipo='facial',titulo='Empleado reconocido',mensaje=formatear_evento(datos),nivel='INFO',
        datos=datos,imagen=None,video=None,referencia=referencia,_frame=frame.copy())
    from core.audit_service import capture_context, audit
    evento['_audit_context']=capture_context()
    with servicio_telegram.lock:
        if referencia in servicio_telegram.encoladas:
            audit.record('TELEGRAM','NOTIFICATION_DUPLICATE','SKIPPED',data={'reference':referencia});return None
        try:servicio_telegram.cola.put_nowait(evento)
        except queue.Full:
            LOG.error('Cola saturada; reconocimiento no encolado.');return None
        servicio_telegram.encoladas.add(referencia)
        audit.record('TELEGRAM','NOTIFICATION_ENQUEUED',data={'reference':referencia,'type':'facial'})
        servicio_telegram.estados[referencia]=dict(tipo='facial',estado='PENDIENTE',detalle='En cola')
    return dict(encolado=True,estado='PENDIENTE',id_evento=referencia)


def texto_estado_entrega(referencia):
    e=servicio_telegram.estado_entrega(referencia) or {}
    partes=e.get('partes',{})
    enviados=[nombre+' enviada' for clave,nombre in (('foto','Foto'),('recorte','Captura'),('video','Clip'))
        if partes.get(clave,{}).get('enviado')]
    if partes.get('texto',{}).get('enviado'):enviados.append('Texto enviado')
    estado={'PENDIENTE':'Pendiente / En cola','ENVIANDO':'Enviando','ENVIADA':'Confirmado',
        'ERROR':'Error','INCIERTO':'Sin confirmación','OMITIDA':'Omitido por política'}.get(e.get('estado'),'Sin evento notificado')
    return ' · '.join(enviados+[estado])


def crear_estado_telegram(padre,categorias):
    """Solo consulta memoria desde Tkinter; no abre conexiones ni envía mensajes."""
    from tkinter import ttk
    categorias=set(categorias)
    etiqueta=ttk.Label(padre,text='Telegram: Sin eventos nuevos',wraplength=1000)
    etiqueta.pack(anchor='w',pady=(0,8))
    def actualizar():
        if not etiqueta.winfo_exists():return
        with servicio_telegram.lock:
            referencias=[r for r,e in servicio_telegram.estados.items() if e.get('tipo') in categorias]
        if referencias:
            ref=referencias[-1];etiqueta.configure(text='Telegram: '+texto_estado_entrega(ref)+' · '+ref)
        etiqueta.after(1000,actualizar)
    etiqueta.after(1000,actualizar)
    return etiqueta
