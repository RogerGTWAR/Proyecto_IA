"""Verifica salida de voz, fallback y cancelación sin depender del hardware."""
import contextlib
import importlib.util
import io
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

class MotorLocal:
    def __init__(self):
        self.propiedades = {'voice': 'en', 'voices': [
            type('Voz', (), {'id':'en','name':'English','languages':['en-US']})(),
            type('Voz', (), {'id':'es','name':'Español','languages':['es-MX']})()]}
        self.frases = []
        self.hilos = []
        self.ocupado = False
        self.sostener = False
        self.iniciado = threading.Event()
        self.detenciones = 0
    def getProperty(self, k): return self.propiedades[k]
    def setProperty(self, k, v): self.propiedades[k] = v
    def say(self, texto):
        self.frases.append(texto); self.hilos.append(threading.get_ident())
        self.ocupado = True; self.iniciado.set()
    def startLoop(self, externo): pass
    def iterate(self):
        if not self.sostener: self.ocupado = False
    def isBusy(self): return self.ocupado
    def endLoop(self): pass
    def stop(self): self.ocupado = False; self.detenciones += 1

class SintesisVoz(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('voz_aislada', ROOT/'jarvis/asistente_voz.py')
        self.v=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.v)
        self.c={'tts_habilitado':True,'tts_provider_preferido':'auto',
                'tts_rate_edge':'+10%','voz':'es-MX-JorgeNeural','velocidad':165,'volumen':.8}
        self.p=patch('core.config_manager.obtener', side_effect=lambda s,k:self.c[k]); self.p.start()
        self.com=patch.dict('sys.modules', {'pythoncom':Mock()});self.com.start()
    def tearDown(self):
        self.v.cerrar_audio()
        if self.v._hilo_tts: self.v._hilo_tts.join(2)
        self.p.stop();self.com.stop()
    def test_fallo_edge_una_vez_sin_tokens(self):
        error=RuntimeError('wss://servidor?TrustedClientToken=secreto&Sec-MS-GEC=x&ConnectionId=y')
        error.status=403
        salida=io.StringIO()
        with patch.object(self.v,'_hablar_edge',side_effect=error) as edge, patch.object(self.v,'_hablar_pyttsx3') as local, contextlib.redirect_stdout(salida):
            self.assertEqual(self.v.hablar('Uno'),'pyttsx3')
            self.assertEqual(self.v.hablar('Dos'),'pyttsx3')
        self.assertEqual(edge.call_count,1);self.assertEqual(local.call_count,2)
        self.assertIn('HTTP 403',salida.getvalue())
        self.assertNotIn('secreto',salida.getvalue());self.assertNotIn('wss:',salida.getvalue())
        self.assertEqual(salida.getvalue().count('[TTS]'),1)
    def test_modo_local_y_motor_reutilizado(self):
        self.c['tts_provider_preferido']='local';motor=MotorLocal()
        with patch('pyttsx3.init',return_value=motor) as init, patch.object(self.v,'_hablar_edge') as edge:
            self.v.hablar('Uno');self.v.hablar('Dos')
        init.assert_called_once();edge.assert_not_called()
        self.assertEqual(motor.propiedades['voice'],'es')
        self.assertEqual(motor.propiedades['rate'],165);self.assertEqual(motor.propiedades['volume'],.8)
        self.assertEqual(len(set(motor.hilos)),1)
        self.assertNotEqual(motor.hilos[0],threading.get_ident())
    def test_desactivado(self):
        self.c['tts_habilitado']=False
        with patch.object(self.v,'_hablar_edge') as edge,patch.object(self.v,'_hablar_pyttsx3') as local:
            self.assertIsNone(self.v.hablar('Hola'));edge.assert_not_called();local.assert_not_called()
    def test_cola_sin_superponer(self):
        self.c['tts_provider_preferido']='local';activos=0;maximo=0
        def reproducir(texto):
            nonlocal activos,maximo
            activos+=1;maximo=max(maximo,activos);time.sleep(.03);activos-=1
        with patch.object(self.v,'_hablar_pyttsx3',side_effect=reproducir):
            hilos=[threading.Thread(target=self.v.hablar,args=(str(i),)) for i in range(4)]
            for h in hilos:h.start()
            for h in hilos:h.join(2);self.assertFalse(h.is_alive())
        self.assertEqual(maximo,1)
    def test_detener_local_y_pendientes(self):
        self.c['tts_provider_preferido']='local';motor=MotorLocal();motor.sostener=True
        with patch('pyttsx3.init',return_value=motor):
            uno=threading.Thread(target=self.v.hablar,args=('Uno',));uno.start()
            self.assertTrue(motor.iniciado.wait(2))
            dos=threading.Thread(target=self.v.hablar,args=('Dos',));dos.start()
            limite=time.monotonic()+2
            while self.v._cola_tts.empty() and time.monotonic()<limite:time.sleep(.01)
            self.v.detener_voz();uno.join(2);dos.join(2)
            self.assertFalse(uno.is_alive());self.assertFalse(dos.is_alive())
        self.assertEqual(motor.frases,['Uno']);self.assertGreater(motor.detenciones,0)
    def test_cancelar_edge_sin_fallback(self):
        with patch.object(self.v,'_hablar_edge',side_effect=self.v._VozCancelada),patch.object(self.v,'_hablar_pyttsx3') as local:
            self.assertIsNone(self.v.hablar('Hola'));local.assert_not_called()
        self.assertTrue(self.v.edge_tts_disponible)
    def test_error_local_entendible(self):
        self.c['tts_provider_preferido']='local'
        with patch.object(self.v,'_hablar_pyttsx3',side_effect=RuntimeError('datos internos')):
            with self.assertRaisesRegex(RuntimeError,'Revisa las voces') as exc:self.v.hablar('Hola')
        self.assertNotIn('datos internos',str(exc.exception))
    def test_sin_voz_espanola_conserva_predeterminada(self):
        motor=MotorLocal();motor.propiedades['voices']=motor.propiedades['voices'][:1]
        self.assertEqual(self.v._seleccionar_voz_espanol(motor),'English')
        self.assertEqual(motor.propiedades['voice'],'en')

if __name__=='__main__':unittest.main()
