"""Configuración validada y atómica; conserva el archivo facial existente."""
from core.paths import PROJECT_ROOT
from pathlib import Path
from copy import deepcopy
import json
import os
import threading
from urllib.parse import urlsplit

BASE=PROJECT_ROOT
ARCHIVO=BASE/'config_sistema.json'
_lock=threading.RLock()
DEFAULTS={
 'telegram':{'habilitado':True,'bot_habilitado':True,'inventario':True,'alertas':True,'prediccion':True,'anomalias':True,'vigilancia':True,
             'facial':True,'sistema':True,'nivel_minimo':'TODAS'},
 'vigilancia':{'yolo_model':'modelos/vigilancia/yolov8n.pt','confidence_threshold':0.45,
     'camera_source':0,'camera_name':'Cámara principal','intrusion_enabled':False,
     'telegram_enabled':False,'cooldown_seconds':45,'zone_name':'Zona restringida',
     'zone_polygon':[],'clip_before_seconds':3,'clip_after_seconds':5,
     'clip_fps':8,'image_size':640,'confirm_frames':3,'track_ttl_seconds':2.0,
     'camera_source_intrusion':None,'camera_source_employees':1,
     'camera_name_employees':'Sala de personal','room_name':'Habitación de empleados',
     'presence_confidence':0.45,'presence_image_size':480,'presence_fps_limit':8,
     'presence_confirm_frames':3,'presence_exit_timeout':3.0,'presence_face_interval':0.6,
     'presence_revalidate_seconds':60.0,'presence_unknown_frames':3,
     'presence_notify_unknown':True,'presence_notify_entries':False,
     'presence_notify_exits':False,'presence_notify_errors':True},
 'arduino':{'habilitado':False,'modo':'simulacion','puerto':'','baudrate':9600,'timeout':2.0},
 'general':{'nombre':'Sistema Inteligente de Inventario','idioma':'Español','tema':'flatly','ventana':'1366x768','inicio':'Dashboard'},
 'inventario':{'stock_minimo':0,'formato_fecha':'%Y-%m-%d'},
 'jarvis':{'microfono':-1,'volumen':0.8,'voz':'es-MX-JorgeNeural','velocidad':165,
           'modelo_vosk':'modelos_voz/vosk-model-small-es-0.42','respuesta_hablada':True,'activacion':False,
           'tts_habilitado':True,'tts_provider_preferido':'auto','tts_rate_edge':'+10%'},
 'prediccion':{'periodo':30,'minimo_historial':5,'horizonte':30},
 'anomalias':{'periodo':90,'minimo_historial':10,'sensibilidad':3.0,'metodo':'Estadística por producto y tipo'},
 'reportes':{'carpeta':'reportes_exportados','formato':'PDF','encabezado':'Estado real del almacén'},
 'facial':{'motor':'embeddings','fuente_video':0,'resolucion':[1920,1080],'backend':'cpu','debug':False,'roi':None,
           'detectar_cada':3,'cnn_interval_frames':3,'detector_score':0.9,'detector_nms':0.3,'intervalo_deteccion_s':0.25,'lado_deteccion':960,'tile':640,'max_rostros':16,'min_rostro':80,
           'blur_min':45,'blur_lado':160,'blur_rechazo':45,'iluminacion_min':45,'iluminacion_max':210,'roll_max':35,'yaw_max':0.65,
           'muestras_temporales':4,'ventana_temporal':7,'fraccion_consenso':0.8,'ttl_evidencia_s':2,
           'ttl_identidad_s':0.75,'timeout_track_s':1,'modo_basico':False}}

def validar(c):
    t=c['telegram']
    if any(type(t[k]) is not bool for k in ('habilitado','bot_habilitado','inventario','alertas','prediccion','anomalias','vigilancia','facial','sistema')):
        raise ValueError('Telegram: se requieren valores booleanos.')
    if t['nivel_minimo'] not in ('TODAS','MEDIO+','ALTO+','CRÍTICO'):raise ValueError('Telegram: nivel mínimo inválido.')
    v=c['vigilancia']
    from surveillance.vigilancia_yolo import validar_configuracion
    validar_configuracion(v)
    from surveillance.presencia_empleados import validar_configuracion_presencia
    validar_configuracion_presencia(v)
    a=c['arduino']
    if type(a['habilitado']) is not bool or a['modo'] not in ('simulacion','hardware'):
        raise ValueError('Arduino: habilitación o modo inválido.')
    if not isinstance(a['puerto'],str) or len(a['puerto'])>128 or any(ord(x)<32 for x in a['puerto']):
        raise ValueError('Arduino: puerto inválido.')
    if type(a['baudrate']) is not int or a['baudrate'] not in (9600,19200,38400,57600,115200):
        raise ValueError('Arduino: velocidad serial no admitida.')
    if type(a['timeout']) not in (int,float) or not .2<=a['timeout']<=10:
        raise ValueError('Arduino: timeout entre 0.2 y 10 segundos.')
    for s,k in [('jarvis','microfono'),('jarvis','velocidad'),('prediccion','minimo_historial'),('prediccion','horizonte'),('anomalias','minimo_historial'),('facial','detectar_cada'),('facial','min_rostro')]:
        if type(c[s][k]) is not int: raise ValueError(f'{k}: se requiere un número entero.')
    def rango(seccion,clave,minimo,maximo):
        valor=c[seccion][clave]
        if isinstance(valor,bool) or not isinstance(valor,(int,float)) or not minimo<=valor<=maximo: raise ValueError(f'{seccion}: {clave} debe estar entre {minimo} y {maximo}.')
    for s,k,a,b in [('inventario','stock_minimo',0,1000000),('jarvis','volumen',0,1),('jarvis','velocidad',80,300),
      ('jarvis','microfono',-1,10000),('prediccion','minimo_historial',5,365),('prediccion','horizonte',1,365),
      ('anomalias','minimo_historial',10,10000),('anomalias','sensibilidad',2,6),('facial','detectar_cada',1,30),('facial','min_rostro',32,1024)]: rango(s,k,a,b)
    for s,k in [('prediccion','periodo'),('anomalias','periodo')]:
        if type(c[s][k]) is not int or c[s][k] not in (7,30,60,90): raise ValueError('Período: seleccione 7, 30, 60 o 90 días.')
    if c['general']['tema']!='flatly' or c['general']['idioma']!='Español': raise ValueError('Esta versión utiliza el tema flatly y español.')
    for clave in ('blur_min','blur_rechazo'):rango('facial',clave,0,1000000)
    if c['facial']['blur_rechazo']>c['facial']['blur_min']:raise ValueError('El rechazo por nitidez debe ser menor o igual que la calidad objetivo.')
    for clave in ('cnn_interval_frames','blur_lado'):
        if type(c['facial'][clave]) is not int:raise ValueError('Se requiere un entero para '+clave)
    rango('facial','cnn_interval_frames',1,30);rango('facial','blur_lado',64,512)
    for clave in ('detector_score','detector_nms'):rango('facial',clave,.01,1)
    import re
    if not re.fullmatch(r'\d{3,4}x\d{3,4}',c['general']['ventana']): raise ValueError('Tamaño de ventana: ancho x alto.')
    w,h=map(int,c['general']['ventana'].split('x'))
    if not (1100<=w<=3840 and 650<=h<=2160): raise ValueError('La ventana debe tener al menos 1100x650.')
    if c['jarvis']['tts_provider_preferido'] not in ('auto','edge','local'): raise ValueError('Proveedor TTS: auto, edge o local.')
    if not isinstance(c['jarvis']['tts_rate_edge'],str) or not re.fullmatch(r'[+-]\d{1,3}%',c['jarvis']['tts_rate_edge']) or not -90<=int(c['jarvis']['tts_rate_edge'][:-1])<=100: raise ValueError('Velocidad Edge: porcentaje entre -90% y +100%.')
    if c['facial']['motor'] not in ('embeddings','cnn','comparacion'): raise ValueError('Motor facial inválido.')
    r=c['facial']['resolucion']
    if not isinstance(r,list) or len(r)!=2 or any(type(n)!=int or not 320<=n<=4096 for n in r): raise ValueError('Resolución facial inválida.')
    fuente=c['facial']['fuente_video']
    if not isinstance(fuente,(int,str)) or isinstance(fuente,bool): raise ValueError('Fuente de vídeo inválida.')
    if isinstance(fuente,int) and fuente<0: raise ValueError('El índice de cámara no puede ser negativo.')
    if isinstance(fuente,str):
        url=urlsplit(fuente)
        if url.username or url.password or url.query: raise ValueError('Use INVENTARIO_VIDEO_SOURCE para fuentes con credenciales o tokens; no se guardan en este JSON.')
        if url.scheme not in ('rtsp','http','https'): raise ValueError('Fuente: índice de cámara o URL RTSP/HTTP sin credenciales.')
    if c['inventario']['formato_fecha'] not in ('%Y-%m-%d','%d/%m/%Y'): raise ValueError('Formato de fecha inválido.')
    if c['reportes']['formato'] not in ('PDF','Excel'): raise ValueError('Formato de reporte inválido.')
    if c['anomalias']['metodo']!='Estadística por producto y tipo': raise ValueError('Método de anomalías no disponible.')
    for s,k in [('general','nombre'),('jarvis','voz'),('jarvis','modelo_vosk'),('reportes','carpeta'),('reportes','encabezado')]:
        if not isinstance(c[s][k],str) or not c[s][k].strip() or len(c[s][k])>256: raise ValueError(f'{k}: texto obligatorio, máximo 256 caracteres.')
    for s,k in [('jarvis','tts_habilitado'),('jarvis','respuesta_hablada'),('jarvis','activacion'),('facial','debug')]:
        if type(c[s][k]) is not bool: raise ValueError(f'{k}: valor booleano requerido.')
    return c

def cargar_configuracion():
    with _lock:
        c=deepcopy(DEFAULTS)
        try:
            f=json.loads((BASE/'reconocimiento_facial_config.json').read_text(encoding='utf-8'))
            c['facial'].update({k:v for k,v in f.items() if k in c['facial']})
        except (OSError,ValueError,TypeError,AttributeError): pass
        try:
            guardado=json.loads(ARCHIVO.read_text(encoding='utf-8'))
            for s in c:
                if isinstance(guardado.get(s),dict): c[s].update({k:v for k,v in guardado[s].items() if k in c[s]})
            if c['vigilancia']['camera_source_intrusion'] is not None:
                c['vigilancia']['camera_source']=c['vigilancia']['camera_source_intrusion']
            validar(c)
        except FileNotFoundError:
            try: validar(c)
            except (ValueError,TypeError): c=deepcopy(DEFAULTS)
        except (OSError,ValueError,TypeError,AttributeError):
            c=deepcopy(DEFAULTS) # Archivo inválido: valores seguros, no impedir el arranque.
        return c

def guardar_configuracion(c):
    # Solo persistir el esquema reconocido; descartar claves ajenas a esta etapa.
    c=validar({s:{k:deepcopy(c[s].get(k,v)) for k,v in opciones.items()} for s,opciones in DEFAULTS.items()})
    with _lock:
        temporal=ARCHIVO.with_suffix('.tmp')
        temporal.write_text(json.dumps(c,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        os.replace(temporal,ARCHIVO)

def obtener(seccion,clave): return cargar_configuracion()[seccion][clave]
def restaurar(): guardar_configuracion(deepcopy(DEFAULTS))

def ruta(seccion,clave):
    p=Path(obtener(seccion,clave)).expanduser()
    return p if p.is_absolute() else BASE/p
