"""Correspondencia física, ACK serial y conversación sin hardware ni escrituras SQL."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from core.config_manager import DEFAULTS, validar
from integrations.arduino.led_service import ServicioLED, validar_mapeo, validar_led, resolver_filas, LED_ENCENDIDO, LED_APAGADO, LED_ERROR
from inventory.organizacion_fisica import numero_led


class Puerto:
    def __init__(self, **kwargs):
        self.kwargs=kwargs; self.comandos=[]; self.respuestas=[]; self.closed=False
    def reset_input_buffer(self): pass
    def write(self, linea): self.comandos.append(linea)
    def read_until(self, *args, **kwargs): return self.respuestas.pop(0) if self.respuestas else b''
    def close(self): self.closed=True


class Servicio(unittest.TestCase):
    def setUp(self):
        self.cfg=deepcopy(DEFAULTS['arduino'])
        self.puerto=Puerto()
        self.s=ServicioLED(lambda:self.cfg,lambda **kwargs:self.puerto)
    def conectar(self):
        self.cfg.update(modo='hardware',habilitado=True,puerto='COM7',timeout=.2)
        self.puerto.respuestas=[b'READY\n',b'PONG\n']
        with patch('integrations.arduino.led_service.time.sleep'): self.s.conectar()
    def test_24_direcciones(self):
        self.assertEqual(validar_mapeo(),list(range(1,25)))
        self.assertEqual(numero_led(4,1,2),14)
    def test_rechaza_led_fuera_de_rango_y_no_enteros(self):
        for n in (0,25,-1,True,1.2,'14',None):
            with self.subTest(n=n),self.assertRaises(ValueError):validar_led(n)
        self.assertEqual(self.s.estado_conexion()['leds'][1],LED_APAGADO)
    def test_importar_y_simular_no_abre_serial(self):
        with patch('builtins.__import__', wraps=__import__) as importar:
            self.s.encender_varios([1,14,24]);self.s.apagar_led(1)
            self.assertFalse(any(c.args[0]=='serial' for c in importar.call_args_list))
        self.assertIsNone(self.s._serial)
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_ENCENDIDO)
        self.s.apagar_todos()
        self.assertEqual(set(self.s.estado_conexion()['leds'].values()),{LED_APAGADO})
    def test_ack_obligatorio(self):
        self.conectar();self.puerto.respuestas=[b'ERROR:OUTPUT_NOT_CONFIGURED\n']
        with self.assertRaisesRegex(ValueError,'rechazó'):self.s.encender_led(14)
        self.assertEqual(self.s.estado_conexion()['estado'],'Error')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_ERROR)
        self.assertTrue(self.puerto.closed)
    def test_protocolo_serial(self):
        self.conectar();self.puerto.respuestas=[b'OK\n']
        self.s.encender_led(14)
        self.assertEqual(self.puerto.comandos,[b'PING\n',b'LED:14:ON\n'])
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_ENCENDIDO)
        self.puerto.respuestas=[b'STATUS:'+b'0'*24+b'\n']
        self.s.consultar_estado_leds()
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_APAGADO)
    def test_timeout_y_reconexion(self):
        self.conectar()
        with self.assertRaisesRegex(ValueError,'no respondió'):self.s.apagar_todos()
        self.puerto.closed=False;self.puerto.respuestas=[b'PONG\n']
        with patch('integrations.arduino.led_service.time.sleep'):self.s.reconectar()
        self.assertEqual(self.s.estado_conexion()['estado'],'Conectado')
    def test_hardware_deshabilitado(self):
        self.cfg['modo']='hardware'
        with self.assertRaises(ValueError):self.s.conectar()
        with self.assertRaises(ValueError):self.s.encender_led(1)
        self.assertIsNone(self.s._serial)
    def test_sin_pyserial_sigue_disponible_simulacion(self):
        import sys
        s=ServicioLED(lambda:self.cfg)
        with patch.dict(sys.modules,{'serial':None}):
            s.encender_led(14)
            self.cfg.update(modo='hardware',habilitado=True,puerto='COM7')
            with self.assertRaisesRegex(ValueError,'Instale pyserial'):s.conectar()
            self.cfg['modo']='simulacion'
            s.encender_led(14)
        self.assertEqual(s.estado_conexion()['leds'][14],LED_ENCENDIDO)
    def test_cambio_modo_cierra_sin_conexion_automatica(self):
        self.conectar();self.cfg['modo']='simulacion'
        self.assertEqual(self.s.estado_conexion()['estado'],'Simulación activa')
        self.assertTrue(self.puerto.closed)
        self.cfg['modo']='hardware';self.s.estado_conexion()
        self.assertIsNone(self.s._serial)
    def test_snapshot_no_bloquea_con_worker_ocupado(self):
        import threading,time
        listo=threading.Event();terminar=threading.Event()
        def worker():
            with self.s._lock:listo.set();terminar.wait(2)
        t=threading.Thread(target=worker);t.start();listo.wait(1)
        try:
            inicio=time.monotonic();self.s.estado_conexion()
            self.assertLess(time.monotonic()-inicio,.1)
        finally:terminar.set();t.join()
    def test_resolver_actual_sin_tabla_paralela(self):
        filas=[dict(id_ubicacion=7,estante='04',nivel='01',posicion=2)]
        self.assertEqual(resolver_filas(filas)[0]['led'],14)
        with patch('inventory.mapa_almacen.ubicaciones_producto',return_value=filas) as sql:
            self.s.encender_por_producto(20);sql.assert_called_once_with(20)
        filas[0]['posicion']=1
        with patch('inventory.mapa_almacen.ubicaciones_producto',return_value=filas):self.s.encender_por_producto(20)
        self.assertEqual(self.s.estado_conexion()['leds'][13],LED_ENCENDIDO)
    def test_direccion_ambigua_y_posicion_invalida(self):
        filas=[dict(id_ubicacion=7,estante=4,nivel=1,posicion=2),dict(id_ubicacion=8,estante=4,nivel=1,posicion=2)]
        with self.assertRaises(ValueError):resolver_filas(filas)
        for p in (None,1.5,True,0,3):
            with self.assertRaises(ValueError):resolver_filas([dict(filas[0],posicion=p)])
    def test_varias_ubicaciones_y_stock_cero_conservan_posicion(self):
        filas=[dict(id_ubicacion=7,estante=4,nivel=1,posicion=2,cantidad=0),
               dict(id_ubicacion=9,estante=6,nivel=1,posicion=1,cantidad=5)]
        with patch('inventory.mapa_almacen.ubicaciones_producto',return_value=filas):
            r=self.s.encender_por_producto(20)
        self.assertEqual(r['leds'],[14,21])
        self.assertTrue(all(self.s.estado_conexion()['leds'][n]==LED_ENCENDIDO for n in (14,21)))
    def test_validar_lista_completa_antes_de_enviar(self):
        self.conectar()
        with self.assertRaises(ValueError):self.s.encender_varios([14,25])
        self.assertEqual(self.puerto.comandos,[b'PING\n'])
    def test_configuracion_invalida(self):
        for k,v in [('modo','otro'),('timeout',float('nan')),('baudrate',True),('timeout',0),('puerto','COM3\n')]:
            c=deepcopy(DEFAULTS);c['arduino'][k]=v
            with self.assertRaises(ValueError):validar(c)


class ConversacionLED(unittest.TestCase):
    def setUp(self):
        from jarvis import agente_inventario as agente
        self.a=agente;agente.reiniciar_contexto()
        self.productos=[dict(id_producto=1,codigo='TOR-001',nombre='Tornillo M8',stock_actual=20,stock_minimo=5,unidad_medida='Unidad'),
                        dict(id_producto=2,codigo='TOR-002',nombre='Tornillo M10',stock_actual=10,stock_minimo=5,unidad_medida='Unidad')]
        self.filas=[dict(id_ubicacion=7,codigo_ubicacion='E04-N01',estante='04',nivel='01',posicion=2,cantidad=20,unidad_medida='Unidad')]
        from jarvis import herramientas_jarvis as h
        self.s=ServicioLED(lambda:deepcopy(DEFAULTS['arduino']))
        parches=[patch.object(agente,'obtener_productos_activos',return_value=self.productos),
                 patch.object(h,'datos_inventario',return_value=self.productos),
                 patch.object(h,'datos_producto',side_effect=lambda i:next(p for p in self.productos if p['id_producto']==i)),
                 patch.object(h,'datos_ubicaciones',return_value=self.filas),
                 patch('inventory.mapa_almacen.ubicaciones_producto',return_value=self.filas),
                 patch('jarvis.agente_inventario.servicio_led',self.s)]
        for p in parches:p.start();self.addCleanup(p.stop)
    def q(self,texto):return self.a.procesar_consulta(texto,True)
    def test_ubicacion_ofrece_sin_encender(self):
        r=self.q('donde esta el Tornillo M8')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertEqual(r['acciones_opcionales'][-1]['etiqueta'],'Encender LED 14')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_APAGADO)
    def test_contexto_y_apagado(self):
        self.q('donde esta el Tornillo M8')
        r=self.q('Enciende la luz')
        self.assertIn('Simulación',r['respuesta']);self.assertIn('14',r['respuesta'])
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_ENCENDIDO)
        self.q('Apaga la luz')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_APAGADO)
    def test_explicito_y_todas(self):
        r=self.q('Jarvis, enciende la luz del Tornillo M8.')
        self.assertEqual(r['intencion'],'led');self.assertIn('Estante 4',r['respuesta'])
        self.q('Apaga todas las luces')
        self.assertEqual(set(self.s.estado_conexion()['leds'].values()),{LED_APAGADO})
    def test_ambiguedad_conserva_intencion(self):
        r=self.q('Enciende la luz de los tornillos')
        self.assertEqual(r['intencion'],'aclaracion')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_APAGADO)
        r=self.q('el primero')
        self.assertEqual(r['intencion'],'led')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_ENCENDIDO)
    def test_negacion_y_numero_invalido(self):
        self.q('No enciendas la luz del Tornillo M8')
        self.assertEqual(self.s.estado_conexion()['leds'][14],LED_APAGADO)
        self.assertIn('entre 1 y 24',self.q('Enciende LED 25')['respuesta'])
    def test_producto_sin_posicion(self):
        with patch('inventory.mapa_almacen.ubicaciones_producto',return_value=[]):
            self.assertIn('no tiene una posición',self.q('enciende la luz del Tornillo M8')['respuesta'])


if __name__=='__main__':unittest.main()
