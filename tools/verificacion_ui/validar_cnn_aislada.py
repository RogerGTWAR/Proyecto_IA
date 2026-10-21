"""Interfaz real: resumen, auditoría de sesiones y aislamiento de SFace."""
from pathlib import Path
import hashlib
import json
import runpy
import sys
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ai.anomalies import deteccion_anomalias
from ai.facial import diagnostico_facial_basico as diagnostico
from tools.verificacion_ui.validar_tablas_presentacion import widgets


def comprobar(root,*args,**kwargs):
    errores=[];root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    def actualizar(segundos):
        limite=time.monotonic()+segundos
        while time.monotonic()<limite:root.update();time.sleep(.02)
    try:
        actualizar(2)
        selector=next(w for w in widgets(root) if w.winfo_class()=='TCombobox' and tuple(w.cget('values'))==('embeddings','cnn'))
        modo=next(w for w in widgets(root) if w.winfo_class()=='TCombobox' and tuple(w.cget('values'))==('Dataset actual','Validación estricta'))
        modo.set('Validación estricta')
        selector.set('cnn');selector.event_generate('<<ComboboxSelected>>');actualizar(.2)
        boton=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Validar dataset')
        with patch.object(diagnostico,'calibrar_registrados',side_effect=AssertionError('SFace no debe ejecutarse')) as sf,patch.object(diagnostico,'calibrar_cnn',side_effect=AssertionError('Auditar no debe calibrar')) as cnn:
            informe=Path('evaluacion_facial/cnn/dataset.json');marca=informe.stat().st_mtime_ns
            boton.invoke()
            limite=time.monotonic()+40
            resultado=[]
            while time.monotonic()<limite:
                actualizar(.1)
                resultado=[]
                for w in widgets(root):
                    try:
                        v=w.cget('textvariable')
                        if v:resultado.append(str(root.getvar(str(v))))
                    except tk.TclError:pass
                if informe.stat().st_mtime_ns!=marca and any('Sesiones mínimas por clase: 0/4' in t for t in resultado):break
            assert cnn.call_count==0
            assert sf.call_count==0
            assert any('Sesiones mínimas por clase: 0/4' in t and len(t)<600 and 'Sesiones completas: 1/64' in t for t in resultado),resultado
            entrenar=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Entrenar CNN')
            assert str(entrenar.cget('state'))=='disabled'
            tablas=[w for w in widgets(root) if w.winfo_class()=='Treeview']
            filas=[str(w.item(i,'values')) for w in tablas for i in w.get_children()]
            assert any('faltan sesiones (0/4)' in f for f in filas),filas
            assert any('faltan sesiones (1/4)' in f for f in filas),filas
            tabla=next(w for w in tablas if any('subject19' in str(w.item(i,'values')) for i in w.get_children()))
            fila=next(i for i in tabla.get_children() if 'subject19' in str(tabla.item(i,'values')))
            tabla.selection_set(fila)
            capturar=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Capturar sesión CNN')
            capturar.invoke();actualizar(.1)
            labels=[str(w.cget('text')) for w in widgets(root) if w.winfo_class()=='TLabel']
            assert 'Sesiones completadas: 1 / 4' in labels,labels
            assert any('Próxima sesión: Sesión 2' in t for t in labels),labels
            iniciar=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Iniciar captura')
            assert str(iniciar.cget('state'))=='disabled'
            from ai.facial.sesiones_cnn import VentanaSesionCNN,plan_subject
            from ai.facial.diagnostico_cnn import leer
            camara=VentanaSesionCNN(root,'Empleado seleccionado',lambda modo:None,plan_subject('subject19',leer('dataset.json')))
            assert not camara.solicitud_foto.is_set()
            next(w for w in widgets(camara.ventana) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Capturar imagen').invoke()
            assert camara.solicitud_foto.is_set()
            camara.publicar_info(guardadas=4);actualizar(.1)
            assert str(camara.boton_fin.cget('state'))=='normal'
            camara.cerrar()
            detalle=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Ver diagnóstico')
            detalle.invoke();actualizar(.1)
            textos=[w.get('1.0','end') for w in widgets(root) if w.winfo_class()=='Text']
            assert any('subject19' in t and 'subject02 → subject09' in t and 'sesiones 1/4' in t for t in textos)
            assert not errores,errores
        protegido=Path('evaluacion_facial/cnn/sface.json')
        hashes=json.loads(protegido.read_text(encoding='utf-8'))
        cambios=[p for p,h in hashes.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
        assert not cambios,cambios
        print('CNN: resumen 1/64, plan de subject19 sesión 2, confirmación de identidad, captura manual y finalización desde 4 imágenes correctos. SFace: cero llamadas y '+str(len(hashes))+' archivos idénticos.')
    finally:interfaz.cerrar_audio();root.destroy()


if __name__=='__main__':
    with patch.object(deteccion_anomalias,'guardar_hallazgos',return_value=None),patch.object(interfaz,'precalentar_voz',return_value=None),patch.object(tk.Misc,'mainloop',comprobar):
        runpy.run_path('main.py',run_name='__main__')
