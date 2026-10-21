"""Medición con ventana y cámara locales. No conserva fotografías ni crea alertas."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import threading
import time
from collections import Counter
from unittest.mock import patch
import tkinter as tk
import ttkbootstrap as tb

from ai.facial.pipeline_facial import escribir_json_atomico
from ai.facial.reconocimiento_cnn import reconocer_con_camara, detener_reconocimiento
from ui.ventanas_camara import VentanaCamara


def medir(motor, segundos=10):
    root=tb.Window(themename='flatly');root.title('Medición facial');root.geometry('320x80')
    from ui.ui_theme import configurar_estilos
    configurar_estilos(root)
    tiempos=[];estados=Counter();resultado={};terminado=threading.Event()
    class Vista(VentanaCamara):
        def _actualizar(self):
            if self._ultimo_frame is not None:tiempos.append(time.perf_counter())
            super()._actualizar()
        def publicar_info(self,**datos):
            estados[datos.get('estado','')]+=1
            super().publicar_info(**datos)
    vista=Vista(root,'escaner','',lambda modo:detener_reconocimiento())
    def ejecutar():
        try:
            with patch('ai.facial.reconocimiento_cnn.ControlAlertaDesconocido.procesar',return_value=None):
                resultado['ultimo']=reconocer_con_camara(presentador=vista,motor=motor)
        except Exception as error:resultado['error']=str(error)
        finally:terminado.set()
    worker=threading.Thread(target=ejecutar);worker.start();inicio=time.perf_counter()
    def observar():
        if tiempos and time.perf_counter()-tiempos[0]>=segundos:detener_reconocimiento()
        if time.perf_counter()-inicio>45:detener_reconocimiento()
        if terminado.is_set():vista.cerrar();root.destroy();return
        root.after(50,observar)
    root.after(50,observar);root.mainloop();worker.join(timeout=5)
    duracion=tiempos[-1]-tiempos[0] if len(tiempos)>1 else 0
    ultimo=resultado.get('ultimo',{})
    informe={'motor':motor,'frames_renderizados':len(tiempos),'segundos_video':duracion,
        'video_fps':(len(tiempos)-1)/duracion if duracion else None,
        'inferencia_fps':ultimo.get('fps_cnn',ultimo.get('fps_inferencia')),
        'latencia_cnn_ms':ultimo.get('latencia_cnn_ms_promedio') if motor=='cnn' else None,
        'estados':dict(estados),'error':resultado.get('error'),
        'nota':'Medición local con el rostro/escena presentes. No mide precisión poblacional ni distancia física. No se guardaron imágenes.'}
    escribir_json_atomico(Path('evaluacion_facial')/f'rendimiento_{motor}_actual.json',informe)
    print(informe)
    return informe

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('motor',choices=['embeddings','cnn'])
    args=parser.parse_args();medir(args.motor)
