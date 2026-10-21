from ui.ui_components import insertar_fila
from core.formato_numerico import format_numero, format_moneda
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from ui.ui_theme import crear_panel,COLORES
from ui.tareas_ui import TrabajosUI
from ai.anomalies.deteccion_anomalias import analizar_movimientos,listar_anomalias,cambiar_estado_anomalia
from inventory.inventario_service import buscar_inventario
from ui.ui_components import organizar_acciones

class AnomaliasUI:
    def __init__(self,padre,root,tabla):
        self.root=root; self.trabajo=TrabajosUI(root); self.filas={}; self.productos={};self.ultimo_analisis=None
        from integrations.telegram.telegram_service import crear_estado_telegram
        crear_estado_telegram(padre,('anomalias',))
        from ui.ui_components import ModuleHeader,DetailPanel
        from ui.ui_theme import crear_kpi
        ModuleHeader(padre,'Anomalías del inventario','Comparación con el historial del producto y tipo de movimiento. El score no es una probabilidad.')
        kpis=ttk.Frame(padre,style='App.TFrame');kpis.pack(fill='x',pady=(0,8))
        self.kpis={k:tk.StringVar(value='—') for k in ('analizadas','anomalias','criticas','pendientes')}
        for i,(k,n) in enumerate(zip(self.kpis,('Analizadas','Anomalías','Críticas','Pendientes'))):
            crear_kpi(kpis,n,self.kpis[k],tono='danger' if k=='criticas' else 'info').grid(row=0,column=i,sticky='ew',padx=(0,8));kpis.columnconfigure(i,weight=1)
        f=crear_panel(padre,SPACING_CARD); f.pack(fill='x',pady=(0,SPACING_MD)); self.controles={}
        avanzados=ttk.Frame(f);avanzados.grid(row=1,column=0,columnspan=5,sticky='ew',pady=(SPACING_SM,0))
        principales={'desde':0,'hasta':1,'producto':2,'nivel':3}
        for i,(k,titulo,opciones) in enumerate((('desde','Desde YYYY-MM-DD',None),('hasta','Hasta YYYY-MM-DD',None),('producto','Producto',['Todos']),('tipo','Tipo',['Todos','Cantidad inusual']),('nivel','Nivel',['Todos','BAJA','MEDIA','ALTA','CRÍTICA']),('movimiento','Movimiento',['Todos','Entrada','Salida','Transferencia']))):
            secundario=k not in principales
            contenedor=avanzados if secundario else f
            col=(0 if k=='tipo' else 1) if secundario else principales[k]
            marco=ttk.Frame(contenedor); marco.grid(row=0,column=col,sticky='ew',padx=SPACING_XS);contenedor.columnconfigure(col,weight=2 if k=='producto' else 1)
            ttk.Label(marco,text=titulo).pack(anchor='w')
            w=ttk.Entry(marco) if opciones is None else ttk.Combobox(marco,values=opciones,state='readonly'); w.pack(fill='x')
            if opciones: w.set('Todos')
            self.controles[k]=w
            w.configure(width=14)
        avanzados.grid_remove()
        estado_grupo=ttk.Frame(avanzados);estado_grupo.grid(row=0,column=2,sticky='ew',padx=4);avanzados.columnconfigure(2,weight=1)
        ttk.Label(estado_grupo,text='Estado').pack(anchor='w')
        self.filtro_estado=ttk.Combobox(estado_grupo,values=['Todos','PENDIENTE','REVISADA','JUSTIFICADA'],state='readonly',width=14)
        self.filtro_estado.set('Todos');self.filtro_estado.pack(fill='x')
        def alternar():
            visible=bool(avanzados.winfo_manager())
            if visible:avanzados.grid_remove()
            else:avanzados.grid()
            toggle.configure(text='Filtros avanzados ▼' if visible else 'Filtros avanzados ▲')
        toggle=ttk.Button(f,text='Filtros avanzados ▼',command=alternar,style='Secondary.TButton')
        toggle.grid(row=0,column=4,sticky='se',padx=(SPACING_SM,0))
        a=ttk.Frame(padre); a.pack(fill='x',pady=SPACING_SM)
        for texto,fn in [('Reanalizar histórico',self.analizar),('Filtrar',self.refrescar),('Detalle',self.detalle)]: ttk.Button(a,text=texto,command=fn,style='Secondary.TButton').pack(side='left',padx=SPACING_XS)
        cambiar=ttk.Menubutton(a,text='Cambiar estado ▼',style='Secondary.TMenubutton');menu=tk.Menu(cambiar,tearoff=False)
        for titulo,estado in [('Pendiente','PENDIENTE'),('Revisada','REVISADA'),('Justificada','JUSTIFICADA')]:
            menu.add_command(label=titulo,command=lambda e=estado:self.estado(e))
        cambiar.configure(menu=menu);cambiar.pack(side='left',padx=SPACING_XS)
        self.resumen=ttk.Label(padre,text='Cargando…',wraplength=850); self.resumen.pack(anchor='w',pady=SPACING_SM)
        cuerpo=ttk.Frame(padre,style='App.TFrame');cuerpo.pack(fill='both',expand=True)
        self.panel_detalle=DetailPanel(cuerpo,'Explicación del hallazgo');self.panel_detalle.pack(side='right',fill='y',padx=(12,0))
        self.t=tabla(cuerpo,('fecha','producto','tipo_movimiento','cantidad','tipo_anomalia','nivel','score','motivo','estado'),('Fecha / hora','Producto','Movimiento','Cantidad','Tipo','Nivel','Score','Motivo','Estado'),(150,180,120,90,150,95,90,380,110))
        self.t.bind('<<TreeviewSelect>>',self.mostrar_detalle)
        self.t.configure(displaycolumns=('fecha','producto','tipo_movimiento','cantidad','nivel','score','estado'))
        for n,color in [('BAJA','info_bg'),('MEDIA','warning_bg'),('ALTA','warning_bg'),('CRÍTICA','danger_bg')]: self.t.tag_configure(n,background=COLORES[color],foreground=COLORES['texto'])
        self.t.bind('<Double-1>',lambda _:self.detalle())
        from ui.service_state_ui import EventBinding
        def evento(_):
            from core.automatizacion_inventario import automatizacion
            self.ultimo_analisis=automatizacion.ultima_evaluacion
            self.refrescar()
        self.binding=EventBinding(root,evento,padre,('ANOMALIA_DETECTADA','ANOMALIA_RESUELTA'))
        def iniciar(ps):
            self.productos={p['codigo']+' · '+p['nombre']:p['id_producto'] for p in ps}; self.controles['producto'].configure(values=['Todos']+list(self.productos)); self.refrescar()
        self.trabajo.ejecutar(buscar_inventario,iniciar)
    def parametros(self):
        f={k:w.get() or None for k,w in self.controles.items()}
        f['producto']=self.productos.get(f['producto'])
        f['fecha_desde']=f.pop('desde'); f['fecha_hasta']=f.pop('hasta')
        return f
    def refrescar(self):
        if self.trabajo.ocupado:self.refresco_pendiente=True;return
        self.refresco_pendiente=False
        from core.automatizacion_inventario import automatizacion
        f=self.parametros(); self.trabajo.ejecutar(lambda:{'filas':listar_anomalias(**f),'analisis':self.ultimo_analisis or automatizacion.ultima_evaluacion or {}},self.mostrar)
    def mostrar(self,r):
        filas=[a for a in r['filas'] if self.filtro_estado.get()=='Todos' or a['estado']==self.filtro_estado.get()]; analisis=r['analisis']
        self.t.delete(*self.t.get_children()); self.filas={str(a['id_anomalia']):a for a in filas}
        for i,a in self.filas.items(): insertar_fila(self.t, '','end',iid=i,values=tuple(f'{a[k]:.2f}' if k=='score' else a[k] for k in ('fecha','producto','tipo_movimiento','cantidad','tipo_anomalia','nivel','score','motivo','estado')),tags=(a['nivel'],))
        self.resumen.configure(text=f'{len(filas)} hallazgos. '+(analisis.get('mensaje','No hay anomalías para estos filtros.') if not filas else 'Seleccione una fila para revisar su explicación.'))
        for k,v in zip(self.kpis,(analisis.get('movimientos_analizados','—'),len(filas),sum(a['nivel']=='CRÍTICA' for a in filas),sum(a['estado']=='PENDIENTE' for a in filas))):self.kpis[k].set(str(v))
        self.panel_detalle.set('Seleccione un hallazgo para ver la explicación.' if filas else 'No hay anomalías para estos filtros.')
        if getattr(self,'refresco_pendiente',False):self.refrescar()
    def mostrar_detalle(self,_=None):
        a=self.seleccionado()
        if a:self.panel_detalle.set(a['producto']+'\n\n'+a['motivo']+'\n\n'+str(a.get('referencia_historica') or '')+'\n\nMovimiento #'+str(a['id_movimiento'])+' · '+a['estado'])
    def analizar(self):
        if self.trabajo.ocupado:return
        f=self.parametros();self.resumen.configure(text='Analizando movimientos…')
        def consultar():
            analisis=analizar_movimientos(True)
            return {'filas':listar_anomalias(**f),'analisis':analisis}
        def mostrar(r):
            self.ultimo_analisis=r['analisis'];self.mostrar(r)
            self.root.event_generate('<<AnomaliasActualizadas>>',when='tail')
        self.trabajo.ejecutar(consultar,mostrar)
    def seleccionado(self):
        return self.filas.get(self.t.selection()[0]) if self.t.selection() else None
    def detalle(self):
        a=self.seleccionado()
        if a: messagebox.showinfo('Detalle de anomalía',f'Movimiento #{a["id_movimiento"]} · {a["producto"]}\n{a["tipo_movimiento"]}: {a["cantidad"]}\nOrigen: {a["origen"] or "No aplica"} · Destino: {a["destino"] or "No aplica"}\nNivel {a["nivel"]} · Score {a["score"]:.2f}\n{a["motivo"]}\n{a["referencia_historica"]}\nEstado {a["estado"]}\n{a["observacion"]}',parent=self.root)
    def estado(self,estado):
        a=self.seleccionado()
        if not a: return
        nota=simpledialog.askstring('Revisión','Observación / justificación:',parent=self.root,initialvalue=a['observacion'])
        if nota is None: return
        self.trabajo.ejecutar(lambda:cambiar_estado_anomalia(a['id_anomalia'],estado,nota),lambda _:self.refrescar())
