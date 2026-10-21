"""Direcciones físicas compartidas, simulación y transporte serial opcional.

No abre puertos durante la importación ni al iniciar la aplicación.
Las consultas de productos reutilizan las existencias actuales del mapa.
"""
import logging
import threading
import time
import re
from inventory.organizacion_fisica import numero_led
from core.config_manager import cargar_configuracion

LOG = logging.getLogger('arduino')
if not LOG.handlers:
    salida=logging.StreamHandler()
    salida.setFormatter(logging.Formatter('%(message)s'))
    LOG.addHandler(salida)
LOG.setLevel(logging.INFO)
LOG.propagate=False
LED_APAGADO = 'LED_APAGADO'
LED_ENCENDIDO = 'LED_ENCENDIDO'
LED_ERROR = 'LED_ERROR'


def validar_led(numero):
    if type(numero) is not int or not 1 <= numero <= 24:
        raise ValueError('El LED debe ser un entero entre 1 y 24.')
    return numero


def validar_mapeo():
    direcciones = [numero_led(e, n, p) for e in range(1, 7)
                   for n in range(1, 3) for p in range(1, 3)]
    if direcciones != list(range(1, 25)):
        raise ValueError('La correspondencia física de los 24 LEDs no es única.')
    return direcciones


def resolver_filas(filas):
    """Rechaza direcciones ambiguas; nunca deduce una posición ausente."""
    resultado = []
    vistos = {}
    for fila in filas:
        if not re.fullmatch(r'[12]',str(fila.get('posicion',''))):
            raise ValueError('La posición física debe ser 1 o 2.')
        led = numero_led(fila['estante'], fila['nivel'], fila['posicion'])
        clave = (fila['id_ubicacion'], fila['posicion'])
        if led in vistos and vistos[led] != clave:
            raise ValueError('Varias ubicaciones SQL corresponden al mismo LED.')
        vistos[led] = clave
        if not any(r['led'] == led for r in resultado):
            resultado.append(dict(fila, led=led))
    return resultado


def resolver_producto(id_producto):
    from inventory.mapa_almacen import ubicaciones_producto
    return resolver_filas(ubicaciones_producto(id_producto))


def resolver_ubicacion(id_ubicacion, posicion):
    from inventory.inventario_service import consultar
    filas = consultar('''SELECT id_ubicacion,estante,nivel FROM dbo.ubicaciones
        WHERE id_ubicacion=? AND estado=1 AND fecha_eliminacion IS NULL''', id_ubicacion)
    if len(filas) != 1:
        raise ValueError('Ubicación inexistente o inactiva.')
    return resolver_filas([dict(filas[0], posicion=posicion)])[0]


def detectar_puertos():
    try:
        from serial.tools import list_ports
    except ImportError:
        raise ValueError('Instale pyserial para detectar puertos. La simulación sigue disponible.')
    return [p.device for p in list_ports.comports()]


class ServicioLED:
    def __init__(self, configuracion=None, serial_factory=None):
        validar_mapeo()
        self._config = configuracion or (lambda: cargar_configuracion()['arduino'])
        self._factory = serial_factory
        self._lock = threading.RLock()
        self._serial = None
        self._firma = None
        self._leds = {n: LED_APAGADO for n in range(1, 25)}
        self._detalle = 'Simulación preparada; no se controla hardware.'
        self._revision = 0

    def _sincronizar(self):
        cfg = self._config()
        firma = tuple(cfg[k] for k in ('habilitado', 'modo', 'puerto', 'baudrate', 'timeout'))
        if firma != self._firma:
            self._cerrar()
            self._firma = firma
            self._leds = {n: LED_APAGADO if cfg['modo'] == 'simulacion' else LED_ERROR for n in range(1, 25)}
            self._detalle = 'Sin conexión física.'
            self._revision += 1
            from core.system_state import state_manager
            simulation=cfg['modo']=='simulacion'
            state_manager.update('ARDUINO','DEGRADED' if simulation else 'OFFLINE',self._detalle,
                details={'mode':'SIMULATION' if simulation else 'HARDWARE','port':cfg['puerto']},
                available=simulation,activity='SIMULATION' if simulation else 'IDLE',expected=True)
        return cfg

    def _cerrar(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                LOG.exception('[ARDUINO] Error al cerrar el puerto')
            self._serial = None

    def estado_conexion(self):
        adquirido = self._lock.acquire(blocking=False)
        try:
            cfg = self._sincronizar() if adquirido else self._config()
            from core.system_state import state_manager,format_service_state
            current=state_manager.get('ARDUINO')
            return dict(estado=format_service_state(current)['legacy_text'],status=current.status,
                        activity=current.activity,detalle=current.message,modo=cfg['modo'],
                        leds=dict(self._leds), revision=self._revision)
        finally:
            if adquirido: self._lock.release()

    def _enviar(self, comando, esperado='OK'):
        cfg = self._config()
        if self._serial is None:
            raise ValueError('Arduino está desconectado. Conéctelo desde Configuración.')
        try:
            self._serial.reset_input_buffer()
            self._serial.write((comando + '\n').encode('ascii'))
            limite = time.monotonic() + cfg['timeout']
            while time.monotonic() < limite:
                respuesta = self._serial.read_until(b'\n', size=80).decode('ascii', errors='replace').strip()
                if respuesta == 'READY' or not respuesta:
                    continue
                LOG.info('[ARDUINO] puerto=%s comando=%s respuesta=%s', cfg['puerto'], comando, respuesta)
                if (esperado != 'STATUS' and respuesta == esperado) or (esperado == 'STATUS' and re.fullmatch(r'STATUS:[01]{24}', respuesta)):
                    return respuesta
                raise ValueError('Arduino rechazó el comando: ' + respuesta)
            raise ValueError('Arduino no respondió.')
        except Exception as exc:
            self._cerrar()
            self._detalle = str(exc)
            self._leds = {n: LED_ERROR for n in self._leds}
            self._revision += 1
            from core.system_state import state_manager
            state_manager.update('ARDUINO','ERROR','El dispositivo no confirmó el comando.',error='ARDUINO_ACK_FAILED')
            raise ValueError(str(exc)) from exc

    def conectar(self):
        with self._lock:
            cfg = self._sincronizar()
            if cfg['modo'] == 'simulacion':
                return self.estado_conexion()
            if not cfg['habilitado'] or not cfg['puerto']:
                raise ValueError('Habilite Arduino y seleccione un puerto para conectar hardware.')
            self._cerrar()
            try:
                fabrica = self._factory
                if fabrica is None:
                    try: import serial
                    except ImportError:
                        raise ValueError('Instale pyserial para conectar Arduino. La simulación sigue disponible.')
                    fabrica = serial.Serial
                self._serial = fabrica(port=cfg['puerto'], baudrate=cfg['baudrate'],
                                       timeout=min(.2, cfg['timeout']), write_timeout=cfg['timeout'])
                # El UNO puede reiniciarse al abrir USB; espera acotada en el worker.
                time.sleep(2)
                self._enviar('PING', 'PONG')
                self._detalle = 'PING confirmado; las salidas se confirman por comando.'
                self._revision += 1
                from core.eventos_servicios import informar_estado_componente
                informar_estado_componente('Arduino',True,'PING confirmado.')
                return self.estado_conexion()
            except Exception as exc:
                self._cerrar()
                self._detalle = str(exc); self._revision += 1
                from core.system_state import state_manager
                state_manager.update('ARDUINO','ERROR','No se pudo conectar Arduino.',error='ARDUINO_CONNECT_FAILED')
                raise ValueError('No se pudo conectar Arduino: ' + str(exc)) from exc

    def desconectar(self):
        with self._lock:
            cfg = self._sincronizar()
            self._cerrar()
            if cfg['modo'] == 'hardware':
                self._leds = {n: LED_ERROR for n in self._leds}
            self._detalle = 'Conexión cerrada. Desconectar USB no confirma el apagado físico.'
            self._revision += 1
            if cfg['modo'] == 'hardware':
                from core.eventos_servicios import informar_estado_componente
                informar_estado_componente('Arduino',False,'Conexión cerrada por la aplicación.',esperado=True)
            return self.estado_conexion()

    def reconectar(self):
        self.desconectar()
        return self.conectar()

    def comprobar(self):
        with self._lock:
            cfg = self._sincronizar()
            if cfg['modo'] == 'hardware':
                self._enviar('PING', 'PONG')
            return self.estado_conexion()

    def consultar_estado_leds(self):
        with self._lock:
            cfg=self._sincronizar()
            if cfg['modo']=='hardware':
                respuesta=self._enviar('STATUS','STATUS')
                if not re.fullmatch(r'STATUS:[01]{24}',respuesta):
                    raise ValueError('Arduino no devolvió los 24 estados.')
                self._leds={i+1:LED_ENCENDIDO if valor=='1' else LED_APAGADO
                            for i,valor in enumerate(respuesta.split(':')[1])}
                self._revision+=1
            return self.estado_conexion()

    def _cambiar(self, numeros, encendido):
        from core.audit_service import operation
        with operation('ARDUINO','LED_ON' if encendido else 'LED_OFF',origin='desktop'):
            return self._cambiar_observado(numeros,encendido)

    def _cambiar_observado(self, numeros, encendido):
        numeros = list(dict.fromkeys(validar_led(n) for n in numeros))
        if not numeros:raise ValueError('Seleccione al menos un LED.')
        with self._lock:
            cfg = self._sincronizar()
            for n in numeros:
                if cfg['modo'] == 'hardware':
                    self._enviar(f'LED:{n}:{"ON" if encendido else "OFF"}')
                self._leds[n] = LED_ENCENDIDO if encendido else LED_APAGADO
                self._revision += 1
                LOG.info('[ARDUINO] modo=%s led=%s accion=%s', cfg['modo'], n, 'ON' if encendido else 'OFF')
                from core.system_state import state_manager
                state_manager.update('ARDUINO',details={'last_command':f'LED:{n}:{"ON" if encendido else "OFF"}'})
                from core.event_bus import emitir
                emitir('LED_ACTIVADO' if encendido else 'LED_DESACTIVADO','ARDUINO','led_service',
                       'LED encendido' if encendido else 'LED apagado',
                       ('Simulación' if cfg['modo']=='simulacion' else 'Confirmado por Arduino')+f': LED {n}.',
                       data={'led':n,'modo':cfg['modo'],'encendido':encendido})
            leds = ', '.join(f'{n:02}' for n in numeros)
            mensaje = ('Simulación: ' if cfg['modo'] == 'simulacion' else 'Arduino confirmó: ')
            mensaje += f'LED {leds} ' + ('encendido.' if encendido else 'apagado.')
            self._detalle = mensaje
            from core.system_state import state_manager
            state_manager.update('ARDUINO',message=mensaje)
            return dict(mensaje=mensaje, leds=numeros, modo=cfg['modo'])

    def encender_led(self, numero): return self._cambiar([numero], True)
    def apagar_led(self, numero): return self._cambiar([numero], False)
    def encender_varios(self, numeros): return self._cambiar(numeros, True)

    def apagar_todos(self):
        from core.audit_service import operation
        with operation('ARDUINO','ALL_LEDS_OFF',origin='desktop'):
            return self._apagar_todos()

    def _apagar_todos(self):
        with self._lock:
            cfg = self._sincronizar()
            if cfg['modo'] == 'hardware': self._enviar('ALL:OFF')
            self._leds = {n: LED_APAGADO for n in self._leds}
            self._revision += 1
            self._detalle = ('Simulación: ' if cfg['modo'] == 'simulacion' else 'Arduino confirmó: ') + 'todos los LEDs apagados.'
            from core.system_state import state_manager
            state_manager.update('ARDUINO',message=self._detalle,details={'last_command':'ALL:OFF'})
            LOG.info('[ARDUINO] modo=%s comando=ALL:OFF', cfg['modo'])
            from core.event_bus import emitir
            emitir('LED_DESACTIVADO','ARDUINO','led_service','LEDs apagados',self._detalle,
                   data={'leds':list(self._leds),'modo':cfg['modo']})
            return dict(mensaje=self._detalle, leds=list(self._leds), modo=cfg['modo'])

    def encender_por_ubicacion(self, id_ubicacion, posicion):
        return self.encender_led(resolver_ubicacion(id_ubicacion, posicion)['led'])

    def por_producto(self, id_producto, encendido=True):
        filas = resolver_producto(id_producto)
        if not filas: raise ValueError('El producto no tiene una posición física asignada.')
        r = self._cambiar([f['led'] for f in filas], encendido)
        from inventory.organizacion_fisica import describir_posicion
        r['mensaje'] += ' ' + '; '.join(describir_posicion(f) for f in filas) + '.'
        return r

    def encender_por_producto(self, id_producto): return self.por_producto(id_producto)

    def probar_led(self, numero):
        self.encender_led(numero)
        time.sleep(.8)
        return self.apagar_led(numero)


servicio_led = ServicioLED()
