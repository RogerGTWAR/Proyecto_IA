"""Evaluación por eventos; independiente de Tkinter y del transporte de Telegram."""
from core.paths import PROJECT_ROOT
from copy import deepcopy
from datetime import date,datetime
from decimal import Decimal
import json
import logging
from pathlib import Path
import os
import threading
import time

LOG=logging.getLogger('automatizacion_inventario')
VENTANAS=(7,30,60,90)


def _encode(value):
    if isinstance(value,datetime):return {'__tipo__':'datetime','valor':value.isoformat()}
    if isinstance(value,date):return {'__tipo__':'date','valor':value.isoformat()}
    if isinstance(value,Decimal):return {'__tipo__':'decimal','valor':str(value)}
    raise TypeError(type(value).__name__)


def _decode(value):
    tipos={'datetime':datetime.fromisoformat,'date':date.fromisoformat,'decimal':Decimal}
    return tipos[value['__tipo__']](value['valor']) if value.get('__tipo__') in tipos else value


class ResultadosPrediccion:
    """Últimos resultados por producto/ventana; sustitución atómica del archivo."""
    def __init__(self,ruta=None):
        self.ruta=Path(ruta) if ruta else PROJECT_ROOT/'outputs/predicciones/resultados.json'
        self.lock=threading.RLock();self.filas={}
        try:
            if self.ruta.is_file():self.filas=json.loads(self.ruta.read_text(encoding='utf-8'),object_hook=_decode)
        except Exception:
            LOG.exception('No se pudo cargar la última predicción persistida; se reconciliará desde SQL.')

    def guardar(self,producto,resultados):
        with self.lock:
            nuevas=deepcopy(self.filas)
            for ventana,r in resultados.items():nuevas[f'{producto}:{ventana}']=deepcopy(r)
            self.ruta.parent.mkdir(parents=True,exist_ok=True)
            destino=self.ruta.with_suffix('.writing')
            try:
                with destino.open('w',encoding='utf-8') as f:
                    json.dump(nuevas,f,ensure_ascii=False,default=_encode,allow_nan=False)
                    f.flush();os.fsync(f.fileno())
                os.replace(destino,self.ruta)
            finally:
                if destino.exists():destino.unlink()
            self.filas=nuevas

    def listar(self,ventana):
        with self.lock:return [deepcopy(r) for k,r in self.filas.items() if k.endswith(':'+str(ventana))]

    def obtener(self,producto,ventana):
        with self.lock:return deepcopy(self.filas.get(f'{producto}:{ventana}'))


class AutomatizacionInventario:
    """FIFO del bus para anomalías; un worker para predicción coalescente."""
    def __init__(self,bus=None,resultados=None,debounce=1.5,periodo=3600):
        from core.event_bus import event_bus
        self.bus=bus if bus is not None else event_bus
        self.resultados=resultados if resultados is not None else ResultadosPrediccion()
        self.debounce=debounce;self.periodo=periodo
        self.lock=threading.RLock();self.wake=threading.Event();self.stop=threading.Event()
        self.pendientes={};self.suscripcion=None;self.worker=None;self.iniciado=False
        self.proxima_revision=0;self.ultima_evaluacion=None;self.reconciliado=False
        self.ultimos_movimientos={}
        self.contextos={}

    def iniciar(self):
        with self.lock:
            if self.worker and self.worker.is_alive():return
            self.iniciado=True;self.stop.clear()
            self.suscripcion=self.bus.subscribe('MOVIMIENTO_REGISTRADO',self.movimiento,
                name='automatizacion-inventario',asynchronous=True,capacity=4096)
            self.worker=threading.Thread(target=self._ejecutar,name='prediccion-incremental',daemon=True)
            self.worker.start()

    def programar(self,producto,notificar=True,inmediato=False):
        from core.audit_service import capture_context, audit
        with self.lock:
            context=capture_context()
            anteriores=self.contextos.setdefault(int(producto),[])
            if not any(c['correlation_id']==context['correlation_id'] for c in anteriores):
                anteriores.append(context)
            viejo=self.pendientes.get(int(producto))
            ahora=time.monotonic();primero=viejo[2] if viejo else ahora
            self.pendientes[int(producto)]=(min(ahora+(0 if inmediato else self.debounce),primero+max(5,self.debounce)),
                bool(notificar or (viejo and viejo[1])),primero)
        self.wake.set()
        audit.record('PREDICCION','RECALCULATION_SCHEDULED',entity_type='producto',entity_id=int(producto))

    def _error(self,servicio,producto,error):
        from core.audit_service import audit
        audit.record(servicio,'AUTOMATIC_EVALUATION','FAILED',error=error,level='ERROR',
                     entity_type='producto',entity_id=producto)
        from core.system_event import SystemEvent
        from core.system_state import state_manager
        LOG.exception('Falló %s para producto %s',servicio,producto)
        state_manager.update(servicio,'ERROR','No se pudo completar la evaluación automática.',error=type(error).__name__)
        self.bus.publish(SystemEvent(type=servicio+'_ERROR',category=servicio,
            source='automatizacion_inventario',title='Evaluación no disponible',
            message='El movimiento confirmado se conserva.',severity='ALTA',
            data={'id_producto':producto,'error':type(error).__name__}))

    def movimiento(self,event):
        from core.system_event import thaw
        from core.eventos_servicios import publicar_stock
        datos=thaw(event.data);producto=datos['id_producto']
        identificador=datos['id_movimiento']
        # El publicador de movimientos ya confirmó SQL. Las alertas son consumidoras independientes.
        # La referencia de transición existente del bus es el tracker de dominio.
        try:
            if identificador>self.ultimos_movimientos.get(producto,-1) and all(k in datos for k in ('stock_anterior','stock_nuevo','stock_minimo')):
                previo=Decimal(str(datos['stock_anterior']));minimo=Decimal(str(datos['stock_minimo']))
                self.bus.seed_state('stock:'+str(producto),'AGOTADO' if previo==0 else 'BAJO' if previo<=minimo else 'NORMAL')
                publicar_stock(producto,Decimal(str(datos['stock_nuevo'])),minimo,datos.get('producto',''),datos.get('codigo',''),
                               alertas_actualizadas=False,bus=self.bus)
                self.ultimos_movimientos[producto]=identificador
        except Exception:LOG.exception('No se pudo publicar la transición de stock del producto %s.',producto)
        try:
            from ai.anomalies.deteccion_anomalias import evaluar_movimiento_incremental
            self.ultima_evaluacion=evaluar_movimiento_incremental(datos['id_movimiento'],producto)
        except Exception as error:
            self._error('ANOMALIAS',producto,error)
        finally:
            if datos.get('tipo_movimiento')!='Transferencia':self.programar(producto)

    def calcular(self,producto,notificar):
        from core.audit_service import operation
        with operation('PREDICCION','PREDICTION_UPDATE',entity_type='producto',entity_id=producto) as record:
            from core.config_manager import obtener
            ventana=obtener('prediccion','periodo')
            previo=self.resultados.obtener(producto,ventana)
            self._calcular(producto,notificar)
            nuevo=self.resultados.obtener(producto,ventana)
            record.update(before={'riesgo':(previo or {}).get('riesgo')},
                          after={'riesgo':(nuevo or {}).get('riesgo')},data={'persisted':True,'windows':VENTANAS})

    def _calcular(self,producto,notificar):
        from ai.prediction.prediccion_stock import predecir_agotamiento
        from core.config_manager import obtener
        from core.eventos_servicios import publicar_prediccion
        resultados={}
        for ventana in VENTANAS:
            r=predecir_agotamiento(producto,actualizar_alertas=False,ventana=ventana,publicar=False)
            resultados[ventana]=dict(r,id_producto=producto,calculado_en=datetime.now().astimezone(),disponible=True)
        self.resultados.guardar(producto,resultados)
        actual=resultados[obtener('prediccion','periodo')]
        publicar_prediccion(producto,actual,notificar=notificar,bus=self.bus)

    def reconciliar(self):
        from inventory.inventario_service import buscar_inventario
        from core.config_manager import obtener
        from core.event_types import normalizar
        from inventory.alertas import verificar_alertas_stock
        for p in buscar_inventario():
            if self.stop.is_set():return
            if not p.get('estado'):continue
            pid=p['id_producto']
            with self.lock:
                if pid not in self.ultimos_movimientos:
                    stock=p['stock_actual'];minimo=p['stock_minimo']
                    self.bus.seed_state('stock:'+str(pid),'AGOTADO' if stock==0 else 'BAJO' if stock<=minimo else 'NORMAL')
            verificar_alertas_stock(pid,publicar=self.reconciliado)
            # La primera reconciliación es silenciosa; luego la política horaria puede detectar cambios.
            self.programar(pid,notificar=self.reconciliado,inmediato=True)
        self.reconciliado=True
        self.proxima_revision=time.monotonic()+self.periodo
        from core.system_event import SystemEvent
        self.bus.publish(SystemEvent('ALERTA_ACTUALIZADA','ALERTAS','automatizacion_inventario',
            'Estado de alertas cargado','Reconciliación de las condiciones actuales.',
            data={'inicial':True},metadata={'derivada':True,'reconciliacion':True}))

    def _ejecutar(self):
        while not self.stop.is_set():
            if time.monotonic()>=self.proxima_revision:
                try:self.reconciliar()
                except Exception as error:
                    self._error('PREDICCION',None,error);self.proxima_revision=time.monotonic()+60
            with self.lock:
                ahora=time.monotonic();listos=[(p,n,self.contextos.pop(p,[])) for p,(fecha,n,_) in self.pendientes.items() if fecha<=ahora]
                for p,_,_ in listos:self.pendientes.pop(p,None)
            for producto,notificar,contexts in listos:
                if self.stop.is_set():break
                self.procesar_prediccion(producto,notificar,_contexts=contexts)
            self.wake.wait(.2);self.wake.clear()

    def procesar_prediccion(self,producto,notificar=True,_contexts=None):
        from core.audit_service import use_context, audit
        with self.lock: contexts=self.contextos.pop(int(producto),[]) if _contexts is None else _contexts
        with use_context(contexts[-1] if contexts else None,origin='automatic'):
            if len(contexts)>1:
                audit.record('PREDICCION','COALESCED_RECALCULATION',
                             data={'linked_correlation_ids':[c['correlation_id'] for c in contexts]})
                for previous in contexts[:-1]:
                    with use_context(previous):
                        audit.record('PREDICCION','RECALCULATION_LINKED',
                                     data={'executing_correlation_id':contexts[-1]['correlation_id']})
            result=self._procesar_prediccion(producto,notificar)
            if not result:
                with self.lock:
                    newer=self.contextos.setdefault(int(producto),[])
                    self.contextos[int(producto)]=contexts+newer
            return result

    def _procesar_prediccion(self,producto,notificar=True):
        try:self.calcular(producto,notificar);return True
        except Exception as error:
            self._error('PREDICCION',producto,error)
            with self.lock:
                ahora=time.monotonic();self.pendientes.setdefault(producto,(ahora+30,notificar,ahora+30))
            return False

    def cerrar(self):
        if self.suscripcion:self.suscripcion.unsubscribe()
        self.stop.set();self.wake.set()
        if self.worker and self.worker is not threading.current_thread():self.worker.join(timeout=10)
        self.iniciado=False


automatizacion=AutomatizacionInventario()


def listar_predicciones(ventana=None):
    from core.config_manager import obtener
    return automatizacion.resultados.listar(ventana or obtener('prediccion','periodo'))


def obtener_prediccion(producto,actualizar_alertas=False,ventana=None,**_):
    """Lectura pura: nunca calcula ni crea alertas al consultar."""
    from core.config_manager import obtener
    r=automatizacion.resultados.obtener(producto,ventana or obtener('prediccion','periodo'))
    if r is not None:return r
    return dict(id_producto=producto,producto='Sin predicción disponible',disponible=False,
        datos_suficientes=False,stock_actual=None,stock_minimo=None,consumo_promedio_diario=None,
        dias_restantes_promedio=None,fecha_agotamiento=None,riesgo='SIN DATOS',tendencia='SIN DATOS',
        estado='Sin resultado disponible',consumo_diario=[],explicacion='',
        mensaje='Aún no hay una predicción calculada para este producto. El servicio la actualizará en segundo plano.')
