"""Entrada de Telegram al motor JARVIS existente; sin lógica de inventario duplicada."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from core.config_manager import cargar_configuracion
from integrations.telegram.telegram_service import (BASE,LOG,_credenciales,_normalizar,consultar_bot,
    enviar_respuesta_chat,servicio_telegram)

_consumidor_local=threading.Lock()
TECLADO={'keyboard':[['Hablar con JARVIS'],['Estado del sistema','Alertas'],['Personas presentes'],['Salir de JARVIS','/help']],
    'resize_keyboard':True}
AYUDA=('Sistema Inteligente de Inventario conectado.\n\n'
    '/jarvis — Hablar con JARVIS\n/salir — Finalizar conversación\n'
    '/estado — Consultar el estado del sistema\n/alertas — Resumir alertas pendientes\n'
    '/presentes — Personas presentes en la habitación\n/help — Ver ayuda\n\nLas notificaciones automáticas continúan independientemente de la conversación.')


class ConsumidorUnico:
    """Exclusión local y entre procesos del proyecto para el mismo token."""
    def __init__(self,token):
        self.ruta=Path(tempfile.gettempdir())/('inventario_telegram_'+hashlib.sha256(token.encode()).hexdigest()+'.lock')
        self.archivo=None;self.local=False

    def adquirir(self):
        if not _consumidor_local.acquire(blocking=False):return False
        self.local=True
        try:
            self.archivo=self.ruta.open('a+b')
            self.archivo.seek(0,2)
            if not self.archivo.tell():self.archivo.write(b'0');self.archivo.flush()
            self.archivo.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.archivo.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.archivo,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return True
        except (OSError,ImportError):
            self.liberar();return False

    def liberar(self):
        if self.archivo:self.archivo.close();self.archivo=None
        if self.local:_consumidor_local.release();self.local=False


def resumen_alertas_actuales():
    from inventory.inventario_service import consultar
    # Consultar no refresca vencimientos ni crea alertas al abrir este resumen.
    filas=consultar('''SELECT a.nivel,t.nombre tipo FROM alertas a
        JOIN tipos_alerta t ON t.id_tipo_alerta=a.id_tipo_alerta
        WHERE a.atendida=0 AND a.fecha_eliminacion IS NULL''')
    criticas=sum(_normalizar(a.get('nivel')) in ('CRITICA','CRITICO') for a in filas)
    bajo=sum('STOCK BAJO' in _normalizar(a.get('tipo')) for a in filas)
    anomalias=sum(any(p in _normalizar(a.get('tipo')) for p in ('INUSUAL','ANORMAL','ANOMALIA')) for a in filas)
    return f'ALERTAS\n\nPendientes: {len(filas)}\nCríticas: {criticas}\nStock bajo: {bajo}\nAnomalías: {anomalias}'


def resumen_estado_actual():
    from core.estado_sistema import probar_base
    from surveillance.vigilancia_yolo import servicio_vigilancia
    try:base=probar_base()['estado']
    except Exception:base='DESCONECTADA'
    try:
        from jarvis.agente_inventario import procesar_consulta
        jarvis='DISPONIBLE' if callable(procesar_consulta) else 'NO DISPONIBLE'
    except Exception:jarvis='NO DISPONIBLE'
    v=servicio_vigilancia.obtener_estado()
    camara='ACTIVA' if v.get('activo') and v.get('frame') is not None else 'SIN VERIFICAR'
    if camara!='ACTIVA':
        from ai.facial.reconocimiento_cnn import _bloqueo_camara
        if _bloqueo_camara.locked():camara='EN USO POR RECONOCIMIENTO'
    vigilancia='ACTIVA' if v.get('activo') and v.get('estado')=='Activo' else v.get('estado','SIN VERIFICAR').upper()
    from surveillance.presencia_empleados import estado_camara
    presencia=estado_camara(2)['estado']
    return (f'ESTADO DEL SISTEMA\n\nBase de datos: {base}\nTelegram: CONECTADO\n'
        f'JARVIS: {jarvis}\nCámara 1: {camara}\nVigilancia: {vigilancia}\nCámara 2 · Presencia: {presencia}')


class TelegramBotService:
    def __init__(self):
        self.detener=threading.Event();self.lock=threading.Lock();self.hilo=None
        self.sessions={};self.offset=0;self.username=''
        self.estado='DETENIDO';self.detalle='Listener detenido.'
        self.ruta_cursor=None;self._cuenta=None

    def iniciar(self):
        with self.lock:
            if self.hilo and self.hilo.is_alive():return
            self.detener.clear()
            self.estado='INICIANDO';self.detalle='Preparando la entrada de Telegram.'
            self.hilo=threading.Thread(target=self._ejecutar,name='telegram-entrada',daemon=True)
            self.hilo.start()

    def cerrar(self):
        self.detener.set()

    def obtener_estado(self):
        return dict(estado=self.estado,detalle=self.detalle,activo=bool(self.hilo and self.hilo.is_alive()))

    def _preparar_cursor(self,token):
        cuenta=hashlib.sha256(token.encode()).hexdigest()
        if cuenta==self._cuenta:return
        self._cuenta=cuenta;self.sessions.clear();self.offset=0
        self.ruta_cursor=BASE/'outputs'/'telegram'/('bot_cursor_'+cuenta+'.json')
        try:
            valor=json.loads(self.ruta_cursor.read_text(encoding='utf-8'))['offset']
            if type(valor) is int and valor>=0:self.offset=valor
        except FileNotFoundError:pass
        except (OSError,ValueError,KeyError,TypeError):
            raise RuntimeError('No se pudo recuperar el cursor de Telegram.')

    def _guardar_cursor(self,offset):
        if self.ruta_cursor is None:raise RuntimeError('Cursor no inicializado.')
        self.ruta_cursor.parent.mkdir(parents=True,exist_ok=True)
        auxiliar=self.ruta_cursor.with_suffix('.tmp')
        auxiliar.write_text(json.dumps({'offset':offset}),encoding='utf-8')
        os.replace(auxiliar,self.ruta_cursor)
        self.offset=offset

    def _responder(self,chat,texto,teclado=None):
        if self.detener.is_set():return
        r=enviar_respuesta_chat(chat,texto,teclado)
        if r.get('enviado'):LOG.info('[JARVIS TELEGRAM] respuesta enviada')
        else:LOG.warning('[TELEGRAM BOT] respuesta sin confirmación; no se repite automáticamente')
        return r

    def procesar_actualizacion(self,actualizacion):
        from core.audit_service import use_context, operation
        mensaje=actualizacion.get('message') or {}
        chat=mensaje.get('chat',{}).get('id') if isinstance(mensaje,dict) else None
        trace=None
        # Reuse the pending conversation trace before recording the inbound confirmation.
        if type(chat) is int and str(chat)==_credenciales()[1]:
            from jarvis import agente_inventario as agente
            ctx=agente.obtener_contexto('telegram:'+str(chat))
            with ctx.lock:
                trace=(ctx.get('confirmacion_pendiente') or {}).get('_audit_context') or ctx.get('_audit_pending_context')
        with use_context(trace,origin='telegram'):
            with operation('TELEGRAM','MESSAGE_RECEIVED'):
                return self._procesar_actualizacion(actualizacion)

    def _procesar_actualizacion(self,actualizacion):
        mensaje=actualizacion.get('message')
        if not isinstance(mensaje,dict) or mensaje.get('from',{}).get('is_bot'):return
        chat=mensaje.get('chat',{}).get('id')
        if type(chat) is not int:return
        LOG.info('[TELEGRAM BOT] mensaje recibido')
        _,autorizado=_credenciales()
        if str(chat)!=autorizado:
            LOG.info('[TELEGRAM BOT] chat autorizado=False')
            return self._responder(chat,'Chat no autorizado.')
        LOG.info('[TELEGRAM BOT] chat autorizado=True')
        texto=mensaje.get('text')
        if not isinstance(texto,str):return self._responder(chat,'Por ahora JARVIS en Telegram acepta solo texto.')
        texto=texto.strip()
        if not texto:return
        if len(texto)>2000:return self._responder(chat,'Envía una consulta de hasta 2000 caracteres.')
        comando=texto.split()[0].lower() if texto.startswith('/') else None
        if comando and '@' in comando:
            comando,destinatario=comando.split('@',1)
            if not self.username or destinatario!=self.username.lower():return
        natural=_normalizar(texto).strip(' .!¡¿?')
        if natural in ('HABLAR CON JARVIS','QUIERO HABLAR CON JARVIS','ACTIVAR JARVIS'):comando='/jarvis'
        if natural in ('SALIR DE JARVIS','DEJAR DE HABLAR CON JARVIS'):comando='/salir'
        if natural=='ESTADO DEL SISTEMA':comando='/estado'
        if natural=='ALERTAS':comando='/alertas'
        if natural=='PERSONAS PRESENTES':comando='/presentes'
        if comando:LOG.info('[TELEGRAM BOT] comando=%s',comando if comando in ('/start','/help','/jarvis','/salir','/estado','/alertas') else 'desconocido')
        sesion=self.sessions.setdefault(str(chat),dict(modo_jarvis=False,jarvis_session_id='telegram:'+str(chat),ultima_actividad=time.time()))
        sesion['ultima_actividad']=time.time()
        try:
            from jarvis.jarvis_personality import mensaje_telegram
            if comando=='/start':return self._responder(chat,mensaje_telegram('inicio'),TECLADO)
            if comando=='/help':return self._responder(chat,AYUDA,TECLADO)
            if comando=='/presentes':
                from surveillance.presencia_empleados import resumen_presencia
                return self._responder(chat,resumen_presencia(),TECLADO)
            if comando=='/jarvis':
                sesion['modo_jarvis']=True
                LOG.info('[TELEGRAM BOT] modo_jarvis=True')
                return self._responder(chat,mensaje_telegram('conversar'),TECLADO)
            if comando=='/salir':
                if sesion['modo_jarvis']:
                    from jarvis.agente_inventario import reiniciar_contexto
                    reiniciar_contexto(sesion['jarvis_session_id'])
                sesion['modo_jarvis']=False
                LOG.info('[TELEGRAM BOT] modo_jarvis=False')
                return self._responder(chat,mensaje_telegram('salir'),TECLADO)
            if comando=='/estado':return self._responder(chat,resumen_estado_actual())
            if comando=='/alertas':return self._responder(chat,resumen_alertas_actuales())
            if comando:return self._responder(chat,'Comando no disponible. Usa /help para ver las opciones.')
            if not sesion['modo_jarvis']:return self._responder(chat,mensaje_telegram('espera'),TECLADO)
            from jarvis.jarvis import procesar
            LOG.info('[JARVIS TELEGRAM] procesando mensaje')
            respuesta=procesar(texto,session_id=sesion['jarvis_session_id'],origen='telegram').to_dict()
            # Las acciones UI y la versión hablada pertenecen a la interfaz desktop.
            from core.audit_service import use_context
            with use_context(respuesta.get('audit_context')):
                return self._responder(chat,respuesta['respuesta'])
        except Exception as error:
            LOG.error('[TELEGRAM BOT] error al procesar: %s',type(error).__name__)
            return self._responder(chat,'No pude completar la consulta en este momento. Inténtalo de nuevo.')

    def _consumir_lote(self,actualizaciones):
        for a in actualizaciones:
            if self.detener.is_set():break
            if not isinstance(a,dict) or type(a.get('update_id')) is not int:continue
            if a['update_id']<self.offset:continue
            # Persistir antes de ejecutar: tras una caída no se repiten comandos.
            self._guardar_cursor(a['update_id']+1)
            self.procesar_actualizacion(a)

    def _ejecutar(self):
        consumidor=None;cuenta=None;verificado=False;fallos=0
        try:
            while not self.detener.is_set():
                token,chat=_credenciales()
                habilitado=cargar_configuracion()['telegram'].get('bot_habilitado',True)
                if not habilitado or not token or not re.fullmatch(r'-?\d+',chat):
                    if consumidor:consumidor.liberar();consumidor=None
                    self.estado='DESACTIVADO' if not habilitado else 'SIN CONFIGURAR'
                    self.detalle='Conversación desactivada.' if not habilitado else 'Se requiere token y TELEGRAM_CHAT_ID numérico.'
                    cuenta=None;verificado=False;self.detener.wait(3);continue
                nueva_cuenta=(token,chat)
                if cuenta!=nueva_cuenta:
                    if consumidor:consumidor.liberar()
                    consumidor=ConsumidorUnico(token)
                    if not consumidor.adquirir():
                        self.estado='CONFLICTO';self.detalle='Ya existe un listener local para este bot.'
                        LOG.error('[TELEGRAM BOT] consumidor duplicado bloqueado');return
                    self._preparar_cursor(token);cuenta=nueva_cuenta;verificado=False
                    self.sessions.clear()
                if not verificado:
                    webhook=consultar_bot('getWebhookInfo')
                    if not webhook.get('ok'):
                        self.estado='ERROR';self.detalle=webhook['detalle'];self.detener.wait(5);continue
                    if webhook.get('result',{}).get('url'):
                        self.estado='CONFLICTO';self.detalle='Hay un webhook configurado; no se inicia getUpdates.'
                        LOG.error('[TELEGRAM BOT] webhook activo; listener detenido');return
                    identidad=consultar_bot('getMe')
                    if not identidad.get('ok'):
                        self.estado='ERROR';self.detalle=identidad['detalle'];self.detener.wait(5);continue
                    self.username=identidad.get('result',{}).get('username','');verificado=True
                r=consultar_bot('getUpdates',{'offset':self.offset,'timeout':15,'limit':20,
                    'allowed_updates':json.dumps(['message'])},timeout=22)
                if self.detener.is_set():break
                if _credenciales()!=cuenta:continue
                if not cargar_configuracion()['telegram'].get('bot_habilitado',True):continue
                if not r.get('ok'):
                    self.estado='CONFLICTO' if r.get('http')==409 else 'ERROR';self.detalle=r['detalle']
                    if r.get('http')==409:
                        LOG.error('[TELEGRAM BOT] HTTP 409; detener otros consumidores o revisar webhook');return
                    fallos+=1
                    self.detener.wait(min(30,max(2**min(fallos,5),r.get('retry_after',0))));continue
                self.estado='ESCUCHANDO';self.detalle='Entrada de texto disponible.';fallos=0
                lote=r.get('result')
                if not isinstance(lote,list):raise ValueError('Lote de actualizaciones no válido.')
                self._consumir_lote(lote)
        except Exception as error:
            self.estado='ERROR';self.detalle='El listener se interrumpió. Revise el registro de Telegram.'
            LOG.error('[TELEGRAM BOT] listener interrumpido: %s',type(error).__name__)
            servicio_telegram.informar_componente('Listener Telegram',False,self.detalle)
        finally:
            if consumidor:consumidor.liberar()
            if self.detener.is_set():self.estado='DETENIDO';self.detalle='Listener detenido.'


servicio_bot_telegram=TelegramBotService()
