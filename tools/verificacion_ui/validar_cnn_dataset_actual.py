"""Recorrido de interfaz CNN provisional; el resto del inventario conserva SQL."""
from pathlib import Path
import json
import runpy
import sys
import time
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ai.anomalies import deteccion_anomalias
from tools.verificacion_ui.validar_tablas_presentacion import widgets


def comprobar(root,*args,**kwargs):
    errores=[];root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    def actualizar(segundos=.1):
        limite=time.monotonic()+segundos
        while time.monotonic()<limite:root.update();time.sleep(.02)
    try:
        actualizar(2)
        selector=next(w for w in widgets(root) if w.winfo_class()=='TCombobox' and tuple(w.cget('values'))==('embeddings','cnn'))
        modo=next(w for w in widgets(root) if w.winfo_class()=='TCombobox' and tuple(w.cget('values'))==('Dataset actual','Validación estricta'))
        with patch.object(interfaz,'listar_empleados',side_effect=AssertionError('CNN actual no consulta empleados')),\
             patch.object(interfaz,'listar_relaciones',side_effect=AssertionError('CNN actual no consulta relaciones')),\
             patch('ai.facial.rostros_empleados.obtener_subjects_activos',side_effect=AssertionError('CNN actual no consulta etiquetas SQL')):
            selector.set('cnn');selector.event_generate('<<ComboboxSelected>>');actualizar()
            assert modo.get()=='Dataset actual'
            botones={str(w.cget('text')):w for w in widgets(root) if w.winfo_class()=='TButton'}
            assert str(botones['Entrenar CNN'].cget('state'))=='normal'
            assert str(botones['Reconocer con cámara'].cget('state'))=='normal'
            assert str(botones['Calibrar motores'].cget('state'))=='disabled'
            # Invocar entrenar verifica la ruta del botón sin repetir el ajuste de pesos.
            from ai.facial.cnn_dataset_actual import estado
            with patch('ai.facial.cnn_dataset_actual.entrenar',return_value=estado()['metricas']) as entrenar:
                botones['Entrenar CNN'].invoke();actualizar(.5);assert entrenar.call_count==1
            botones['Validar dataset'].invoke()
            limite=time.monotonic()+15
            while time.monotonic()<limite:
                actualizar()
                textos=[]
                for w in widgets(root):
                    try:
                        v=w.cget('textvariable')
                        if v:textos.append(str(root.getvar(str(v))))
                    except tk.TclError:pass
                if any('Dataset revisado: 182 imágenes válidas' in t for t in textos):break
            assert any('Dataset revisado: 182 imágenes válidas' in t for t in textos),textos
            botones['Ver diagnóstico'].invoke();actualizar()
            assert any('Evaluación provisional' in w.get('1.0','end') and 'subject19' in w.get('1.0','end') for w in widgets(root) if w.winfo_class()=='Text')
            # La ventana de cámara queda limitada a subject, score y estado.
            with patch.object(interfaz,'reconocer_con_camara',return_value={'estado':'RECONOCIDO','reconocido':True,'nombre':'subject19','confianza':.99}) as camara:
                botones['Reconocer con cámara'].invoke();actualizar(.5)
                assert camara.call_args.kwargs['modo_cnn']=='Dataset actual'
                assert camara.call_args.kwargs['callback_alerta'] is None
            assert not errores,errores
        print('Interfaz CNN: Dataset actual por defecto, entrenar/cámara habilitados, recorrido sin consultas de empleados SQL, diagnóstico y validación correctos.')
    finally:interfaz.cerrar_audio();root.destroy()


if __name__=='__main__':
    with patch.object(deteccion_anomalias,'guardar_hallazgos',return_value=None),patch.object(interfaz,'precalentar_voz',return_value=None),patch.object(tk.Misc,'mainloop',comprobar):
        runpy.run_path('main.py',run_name='__main__')
