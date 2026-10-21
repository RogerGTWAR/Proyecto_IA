"""Resumen de resultados existentes; no ejecuta detección de anomalías."""
import tkinter as tk
from tkinter import ttk
from copy import deepcopy
from ui.tareas_ui import TrabajosUI
from ui.ui_theme import crear_panel,SPACING_MD
from ai.anomalies.deteccion_anomalias import listar_anomalias


def resumir_predicciones(filas):
    riesgos=[r for r in filas if r.get('riesgo') in ('ALTO','CRÍTICO')]
    orden={'CRÍTICO':0,'ALTO':1,'MEDIO':2,'BAJO':3,'SIN DATOS':4}
    critico=min(filas,key=lambda r:(orden.get(r.get('riesgo'),4),
        r.get('dias_restantes_promedio') if r.get('dias_restantes_promedio') is not None else float('inf')),default=None)
    return len(riesgos),critico if critico and critico.get('riesgo')!='SIN DATOS' else None


class AnalisisUI:
    def __init__(self,padre,root,prediccion,anomalias,abrir_prediccion,abrir_anomalias):
        self.root=root;self.prediccion=prediccion;self.anomalias=anomalias;self.trabajo=TrabajosUI(root)
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Análisis IA','Resumen de predicción y hallazgos registrados. Cada módulo conserva sus herramientas.')
        self.textos={}
        for titulo,campos,accion in [('PREDICCIÓN',('riesgo','critico','ultima'),abrir_prediccion),
                                     ('ANOMALÍAS',('movimientos','hallazgos','criticas','pendientes'),abrir_anomalias)]:
            panel=crear_panel(padre,SPACING_MD);panel.pack(fill='x',pady=(0,SPACING_MD))
            ttk.Label(panel,text=titulo,style='CardTitle.TLabel').pack(anchor='w')
            for campo in campos:
                self.textos[campo]=tk.StringVar(value='Sin datos disponibles')
                ttk.Label(panel,textvariable=self.textos[campo],wraplength=1000).pack(anchor='w',pady=5)
            ttk.Button(panel,text='Ver predicciones' if titulo=='PREDICCIÓN' else 'Ver anomalías',
                       command=accion,style='Primary.TButton').pack(anchor='w',pady=8)
        self.estado=ttk.Label(padre,text='El resumen se actualiza al entrar.');self.estado.pack(anchor='w')
        root.bind('<<PrediccionesActualizadas>>',lambda _:self.predicciones(),add='+')
        root.bind('<<AnomaliasActualizadas>>',lambda _:self.cargar(),add='+')

    def predicciones(self):
        p=self.prediccion();n,critico=resumir_predicciones(list(p.resultados.values()))
        self.textos['riesgo'].set(f'Productos con riesgo alto / crítico: {n}' if p.ultima_prediccion else 'Productos con riesgo: sin resultados disponibles')
        self.textos['critico'].set('Producto más crítico: '+(critico['producto']+' · '+critico['riesgo'] if critico else 'Sin datos suficientes'))
        self.textos['ultima'].set('Última predicción de esta sesión: '+(p.ultima_prediccion.strftime('%d/%m/%Y %H:%M:%S') if p.ultima_prediccion else 'Sin cálculo registrado'))

    def cargar(self,actualizar_prediccion=False):
        if actualizar_prediccion:self.prediccion().cargar()
        self.predicciones()
        if self.trabajo.ocupado:return
        self.estado.configure(text='Cargando resumen…')
        def mostrar(filas):
            analisis=self.anomalias().ultimo_analisis
            self.textos['movimientos'].set('Movimientos analizados en la última ejecución de esta sesión: '+
                (str(analisis['movimientos_analizados']) if analisis else 'Sin ejecución registrada'))
            self.textos['hallazgos'].set(f'Anomalías registradas: {len(filas)}')
            self.textos['criticas'].set(f"Críticas: {sum(a['nivel']=='CRÍTICA' for a in filas)}")
            self.textos['pendientes'].set(f"Pendientes: {sum(a['estado']=='PENDIENTE' for a in filas)}")
            self.estado.configure(text='Resumen actualizado. No se ejecutó un nuevo análisis de anomalías.')
        self.trabajo.ejecutar(listar_anomalias,mostrar,lambda e:self.estado.configure(text='No se pudo cargar el resumen: '+str(e)))
