from ui.ui_components import insertar_fila
from core.formato_numerico import format_numero, format_moneda
"""Vista comparativa y detalle del motor existente, sin escribir alertas."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
import tkinter as tk
from datetime import datetime
from ui.tareas_ui import TrabajosUI
from tkinter import ttk,messagebox
from ui.ui_theme import crear_kpi,crear_panel
from inventory.inventario_service import buscar_inventario
from core.automatizacion_inventario import listar_predicciones,automatizacion

class PrediccionUI:
    def __init__(self,padre,root,tabla):
        self.root=root; self.resultados={};self.ultima_prediccion=None;self.trabajo=TrabajosUI(root)
        from integrations.telegram.telegram_service import crear_estado_telegram
        crear_estado_telegram(padre,('prediccion',))
        from ui.ui_components import ModuleHeader,FilterBar,DetailPanel
        ModuleHeader(padre,'Predicción de stock','Cobertura estimada a partir de las salidas registradas. Los resultados no son garantías de consumo.')
        resumen=ttk.Frame(padre,style='App.TFrame');resumen.pack(fill='x',pady=(0,8))
        self.resumen_vars={k:tk.StringVar(value='—') for k in ('productos','alto','critico','calculo')}
        for i,(k,n) in enumerate(zip(self.resumen_vars,('Productos analizados','Riesgo alto','Riesgo crítico','Último cálculo'))):
            crear_kpi(resumen,n,self.resumen_vars[k],tono='danger' if k=='critico' else 'info').grid(row=0,column=i,sticky='ew',padx=(0,8));resumen.columnconfigure(i,weight=1)
        filtros=FilterBar(padre);filtros.pack(fill='x',pady=(0,8))
        self.busqueda=filtros.add('Buscar producto');self.riesgo=filtros.add('Riesgo',['Todos','BAJO','MEDIO','ALTO','CRÍTICO','SIN DATOS']);self.riesgo.set('Todos')
        self.busqueda.bind('<KeyRelease>',lambda _:self.filtrar());self.riesgo.bind('<<ComboboxSelected>>',lambda _:self.filtrar())
        acciones=ttk.Frame(padre); acciones.pack(fill='x')
        ttk.Label(acciones,text='Ventana de consumo:').pack(side='left')
        from core.config_manager import obtener
        self.ventana=ttk.Combobox(acciones,values=[7,30,60,90],state='readonly',width=8); self.ventana.set(str(obtener('prediccion','periodo'))); self.ventana.pack(side='left',padx=SPACING_SM)
        self.ventana.bind('<<ComboboxSelected>>',lambda _:self.cargar())
        ttk.Button(acciones,text='Actualizar vista',command=self.cargar,style='Secondary.TButton').pack(side='left')
        mas=ttk.Menubutton(acciones,text='Avanzado',style='Secondary.TMenubutton');menu=tk.Menu(mas,tearoff=False)
        menu.add_command(label='Recalcular resultados',command=self.recalcular);mas.configure(menu=menu);mas.pack(side='left',padx=8)
        cuerpo=ttk.Frame(padre,style='App.TFrame');cuerpo.pack(fill='both',expand=True,pady=(8,0))
        lateral=DetailPanel(cuerpo,'Producto seleccionado');lateral.pack(side='right',fill='y',padx=(12,0))
        lateral.label.pack_forget()
        self.t=tabla(cuerpo,('producto','stock','promedio','dias','riesgo'),('Producto','Stock','Consumo / día','Días restantes','Riesgo'),(240,100,120,120,120))
        fila=ttk.Frame(lateral.body); fila.pack(fill='x')
        self.kpis={k:tk.StringVar(value='—') for k in ('stock','consumo','dias','riesgo','fecha')}
        for i,(k,nombre) in enumerate(zip(self.kpis,('Stock actual','Consumo diario','Días restantes','Riesgo','Fecha estimada'))):
            linea=ttk.Frame(fila);linea.pack(fill='x',pady=(0,8))
            ttk.Label(linea,text=nombre,style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(linea,textvariable=self.kpis[k],font=('Segoe UI',11,'bold'),wraplength=230).pack(anchor='w')
        self.detalle=ttk.Label(lateral.body,text='Seleccione un producto para ver el respaldo de la estimación.',wraplength=230,justify='left'); self.detalle.pack(anchor='w',pady=SPACING_MD)
        ttk.Button(lateral.body,text='Ver consumo histórico',command=self.grafica,style='Secondary.TButton').pack(anchor='w')
        self.t.bind('<<TreeviewSelect>>',self.seleccionar)
        from ui.service_state_ui import EventBinding
        self.binding=EventBinding(root,lambda _:self.cargar(),padre,('PREDICCION_GENERADA',))
        self.cargar()

    def cargar(self):
        if self.trabajo.ocupado:self.refresco_pendiente=True;return
        self.refresco_pendiente=False
        ventana=int(self.ventana.get());self.detalle.configure(text='Cargando resultados disponibles…')
        def consultar():
            return listar_predicciones(ventana)
        def mostrar(filas):
            elegido=self.resultados.get(self.t.selection()[0],{}).get('id_producto') if self.t.selection() else None
            orden={'CRÍTICO':0,'ALTO':1,'MEDIO':2,'BAJO':3,'SIN DATOS':4}
            filas.sort(key=lambda r:(orden[r['riesgo']],r['dias_restantes_promedio'] if r['dias_restantes_promedio'] is not None else float('inf')))
            self.t.delete(*(i for i in self.resultados if self.t.exists(i))); self.resultados={}
            for i,r in enumerate(filas):
                self.resultados[str(i)]=r
                insertar_fila(self.t, '','end',iid=str(i),values=(r['producto'],r['stock_actual'],f'{r["consumo_promedio_diario"]:.2f}',f'{r["dias_restantes_promedio"]:.2f}' if r['datos_suficientes'] and r['dias_restantes_promedio'] is not None else 'Sin datos suficientes',r['riesgo']))
            self.ultima_prediccion=max((r['calculado_en'] for r in filas if r.get('calculado_en')),default=None)
            for k,v in zip(self.resumen_vars,(len(filas),sum(r['riesgo']=='ALTO' for r in filas),sum(r['riesgo']=='CRÍTICO' for r in filas),self.ultima_prediccion.strftime('%H:%M:%S') if self.ultima_prediccion else '—')):self.resumen_vars[k].set(str(v))
            self.filtrar()
            self.detalle.configure(text='Seleccione un producto para ver el respaldo de la estimación.' if filas else 'Sin datos disponibles.')
            for i,r in self.resultados.items():
                if elegido is not None and r.get('id_producto')==elegido:self.t.selection_set(i);self.seleccionar();break
            self.root.event_generate('<<PrediccionesActualizadas>>',when='tail')
            if self.refresco_pendiente:self.cargar()
        self.trabajo.ejecutar(consultar,mostrar,lambda e:self.detalle.configure(text='No se pudo calcular la predicción. Compruebe la conexión e intente actualizar.'))

    def recalcular(self):
        def programar(productos):
            for p in productos:
                if p['estado']:automatizacion.programar(p['id_producto'])
            self.detalle.configure(text='Recálculo solicitado al servicio automático.')
        self.trabajo.ejecutar(buscar_inventario,programar)

    def filtrar(self):
        texto=self.busqueda.get().strip().casefold();riesgo=self.riesgo.get()
        for i,r in self.resultados.items():
            if texto in r['producto'].casefold() and (riesgo=='Todos' or r['riesgo']==riesgo):self.t.reattach(i,'','end')
            else:
                self.t.selection_remove(i);self.t.detach(i)

    def seleccionar(self,_=None):
        if not self.t.selection(): return
        r=self.resultados[self.t.selection()[0]]
        from core.formato_numerico import format_campo
        valores=(format_numero(r['stock_actual']),f'{r["consumo_promedio_diario"]:.2f}',f'{r["dias_restantes_promedio"]:.2f}' if r['dias_restantes_promedio'] is not None else 'Sin datos',r['riesgo'],str(format_campo('fecha',r['fecha_agotamiento']) or 'Sin datos'))
        for variable,valor in zip(self.kpis.values(),valores): variable.set(valor)
        self.detalle.configure(text=(r['explicacion']+'\nTendencia de consumo: '+r['tendencia']+'\n'+r.get('recomendacion','')) if r['datos_suficientes'] else r['mensaje'])

    def grafica(self):
        if not self.t.selection(): return
        r=self.resultados[self.t.selection()[0]]
        if not r['consumo_diario']: messagebox.showinfo('Consumo','Sin datos suficientes.',parent=self.root); return
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(8,4))
        ax.plot([d['fecha'] for d in r['consumo_diario']],[d['cantidad'] for d in r['consumo_diario']],label='Histórico registrado',marker='o')
        if r['datos_suficientes']: ax.axhline(r['consumo_promedio_diario'],linestyle='--',label='Promedio observado; referencia de estimación')
        ax.set(title=r['producto'],xlabel='Fecha',ylabel='Cantidad salida / día'); ax.legend(); fig.autofmt_xdate(); fig.tight_layout(); plt.show()
