from ui.ui_components import insertar_fila
"""Filtros pertinentes, vista previa común y exportación en segundo plano."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from copy import deepcopy
from datetime import datetime,date
from core.formato_numerico import format_campo
from integrations.reporting.reportes import TIPOS,FILTROS,obtener_datos_reporte,exportar_excel,exportar_pdf,etiqueta,texto,nombre_archivo,ruta_disponible
from inventory.inventario_service import buscar_inventario
from inventory.productos import listar_categorias,listar_ubicaciones
from ui.ui_theme import crear_panel
from core.config_manager import ruta,obtener
from ui.tareas_ui import TrabajosUI
from ui.ui_components import organizar_acciones

class ReportesUI:
    def __init__(self,padre,root,tabla):
        self.root=root; self.padre=padre; self.tabla_factory=tabla; self.reporte=None; self.trabajo=TrabajosUI(root)
        self.exportaciones=TrabajosUI(root);self.pendiente=None;self.botones_exportar=[];self.solicitud=0
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Reportes del almacén','Vista previa y exportación de los mismos datos reales')
        self.panel=crear_panel(padre,SPACING_MD); self.panel.pack(fill='x',pady=(0,SPACING_MD))
        ttk.Label(self.panel,text='CONFIGURACIÓN DEL REPORTE',style='CardTitle.TLabel').grid(row=0,column=0,sticky='w',pady=(0,SPACING_SM))
        self.tipo=ttk.Combobox(self.panel,values=TIPOS,state='readonly',width=40); self.tipo.set(TIPOS[0]); self.tipo.grid(row=1,column=0,sticky='w')
        self.panel.columnconfigure(0,weight=1)
        self.campos=ttk.Frame(self.panel); self.campos.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(SPACING_SM,0))
        self.controles={}; self.mapas={}
        self.tipo.bind('<<ComboboxSelected>>',lambda _:self.cambiar())
        a=ttk.Frame(self.panel); a.grid(row=1,column=1,sticky='e'); self.acciones=a
        exportaciones=a
        for titulo,fn,estilo in [('Exportar PDF',lambda:self.exportar('pdf'),'Primary.TButton'),('Exportar Excel',lambda:self.exportar('xlsx'),'Secondary.TButton')]:
            b=ttk.Button(exportaciones,text=titulo,command=fn,style=estilo,state='disabled');b.pack(side='left',padx=SPACING_SM)
            self.botones_exportar.append(b)
        opciones=ttk.Menubutton(exportaciones,text='Más opciones ▼',style='Secondary.TMenubutton');menu=tk.Menu(opciones,tearoff=False)
        menu.add_command(label='Exportar predeterminado',command=lambda:self.exportar('pdf' if obtener('reportes','formato')=='PDF' else 'xlsx'))
        opciones.configure(menu=menu);opciones.pack(side='right')
        resumen_panel=crear_panel(padre,SPACING_SM); resumen_panel.pack(fill='x',pady=(0,SPACING_MD))
        cabecera=ttk.Frame(resumen_panel);cabecera.pack(fill='x')
        ttk.Label(cabecera,text='Resumen del reporte',style='CardTitle.TLabel').pack(side='left',padx=(0,SPACING_MD))
        self.resumen=ttk.Label(cabecera,text='Cargando reporte…',wraplength=700); self.resumen.pack(side='left')
        self.indicadores=ttk.Label(resumen_panel,text='',wraplength=950,style='CardTitle.TLabel'); self.indicadores.pack(anchor='w',pady=(SPACING_XS,0))
        resumen_panel.bind('<Configure>',lambda e:(self.resumen.configure(wraplength=max(300,e.width-30)),self.indicadores.configure(wraplength=max(300,e.width-30))))
        self.tabla_panel=crear_panel(padre,SPACING_MD); self.tabla_panel.pack(fill='both',expand=True); self.t=None
        self.version=0
        self.cambiar()
    def cambiar(self):
        if self.pendiente is not None:self.root.after_cancel(self.pendiente);self.pendiente=None
        self.solicitud+=1
        self.habilitar_exportacion(False)
        for w in self.campos.winfo_children(): w.destroy()
        self.version+=1; version=self.version; tipo=self.tipo.get()
        if FILTROS[tipo]: self.campos.grid()
        else: self.campos.grid_remove()
        self.reporte=None; self.controles={}; self.mapas={}; self.resumen.configure(text='Cargando reporte…')
        self.indicadores.configure(text='')
        for w in self.tabla_panel.winfo_children(): w.destroy()
        self.t=None
        ttk.Label(self.tabla_panel,text='Cargando reporte…',
            style='CardTitle.TLabel',justify='center',anchor='center').pack(fill='both',expand=True,pady=SPACING_LG)
        def catalogos():
            return {'producto':{p['codigo']+' · '+p['nombre']:p['id_producto'] for p in buscar_inventario()},
                'categoria':{c['nombre']:c['id_categoria'] for c in listar_categorias()},
                'ubicacion':{u['codigo_ubicacion']:u['id_ubicacion'] for u in listar_ubicaciones()},
                'almacen':{u['almacen']:u['almacen'] for u in listar_ubicaciones() if u.get('almacen')}}
        def crear(m):
            if version!=self.version: return
            for i,k in enumerate(FILTROS[tipo]):
                f=ttk.Frame(self.campos); f.grid(row=i//5,column=i%5,sticky='ew',padx=SPACING_SM,pady=SPACING_XS); self.campos.columnconfigure(i%5,weight=1)
                ttk.Label(f,text=etiqueta(k)+(' (YYYY-MM-DD)' if k in ('desde','hasta') else ''),style='CardTitle.TLabel').pack(anchor='w',pady=(0,SPACING_XS))
                if k in ('desde','hasta'): w=ttk.Entry(f)
                else:
                    estados=('PENDIENTE','REVISADA','JUSTIFICADA') if tipo=='Anomalías' else ('PENDIENTE','ATENDIDA') if tipo=='Alertas' else ('ACTIVO','INACTIVO') if tipo=='Empleados' else ('NORMAL','BAJO','CRÍTICO','AGOTADO')
                    opciones=m.get(k) or {v:v for v in (('Entrada','Salida','Transferencia','Ajuste entrada','Ajuste salida') if k=='movimiento' else ('BAJO','MEDIO','ALTO','CRÍTICO','SIN DATOS') if k=='riesgo' else estados if k=='estado' else ('BAJA','MEDIA','ALTA','CRÍTICA'))}
                    self.mapas[k]=opciones; w=ttk.Combobox(f,values=['Todos']+[v for v in opciones if v!='Todos'],state='readonly',width=15); w.set('Todos')
                w.pack(fill='x'); self.controles[k]=w
                if isinstance(w,ttk.Combobox):w.bind('<<ComboboxSelected>>',lambda _:self.programar(0))
                else:
                    variable=tk.StringVar(value=w.get());w.configure(textvariable=variable)
                    variable.trace_add('write',lambda *_:self.programar(400));w._variable=variable
            self.programar(0)
        def iniciar():
            if version!=self.version: return
            if self.trabajo.ocupado: self.root.after(100,iniciar)
            else: self.trabajo.ejecutar(catalogos,crear,lambda e:self.error(e) if version==self.version else None)
        iniciar()
    def habilitar_exportacion(self,habilitar):
        for b in self.botones_exportar:b.configure(state='normal' if habilitar else 'disabled')
    def error(self,error):
        self.reporte=None;self.habilitar_exportacion(False);self.resumen.configure(text='No se pudo cargar el reporte. Compruebe la conexión y actualice los filtros.')
    def programar(self,demora=400):
        self.solicitud+=1;self.reporte=None;self.habilitar_exportacion(False)
        self.resumen.configure(text='Cargando reporte…')
        if self.pendiente is not None:self.root.after_cancel(self.pendiente)
        self.pendiente=self.root.after(demora,self.previa)
    def al_entrar(self):
        if self.reporte is not None:self.programar(0)
    def filtros(self):
        return {k:self.mapas[k].get(w.get(),w.get()) if k in self.mapas else w.get().strip() for k,w in self.controles.items()}
    def previa(self):
        self.pendiente=None
        if self.trabajo.ocupado:
            self.pendiente=self.root.after(100,self.previa);return
        tipo=self.tipo.get(); filtros=self.filtros(); solicitud=self.solicitud
        self.reporte=None; self.resumen.configure(text='Cargando reporte…')
        etiquetas={k:self.controles[k].get() for k,v in filtros.items() if v not in ('','Todos','Todas',None)}
        def mostrar(r):
            if solicitud!=self.solicitud or self.tipo.get()!=tipo or self.filtros()!=filtros:return
            r['filtros_etiquetas']=etiquetas
            self.reporte=r
            for w in self.tabla_panel.winfo_children(): w.destroy()
            ttk.Label(self.tabla_panel,text='Vista previa · '+tipo,style='CardTitle.TLabel').pack(anchor='w',pady=(0,SPACING_SM))
            def tabla(padre,cols,filas):
                t=self.tabla_factory(padre,cols,tuple(etiqueta(k) for k in cols),tuple(260 if k in ('motivo','mensaje','observacion','ubicaciones') else 145 for k in cols))
                for f in filas: insertar_fila(t, '','end',values=tuple(format_campo(k,f.get(k)) if isinstance(f.get(k),(date,datetime)) else texto(f.get(k)) for k in cols))
                if len(cols)>8:t.configure(displaycolumns=cols[:8])
                def detalle(_=None):
                    from ui.ui_components import ver_detalle_fila
                    ver_detalle_fila(t,self.root)
                t.bind('<Double-1>',detalle);t.bind('<Return>',detalle)
                return t
            detalle=ttk.Notebook(self.tabla_panel); detalle.pack(fill='both',expand=True)
            principal=ttk.Frame(detalle); detalle.add(principal,text='Indicadores' if tipo=='Resumen general' else 'Detalle')
            self.t=tabla(principal,r['columnas'],r['filas'])
            for i,s in enumerate(r.get('secciones',[])):
                panel=ttk.Frame(detalle); detalle.add(panel,text=('Movimientos','Productos críticos','Riesgos','Anomalías','Estado')[i])
                ttk.Label(panel,text=s['titulo']).pack(anchor='w')
                tabla(panel,s['columnas'],s['filas'])
            self.resumen.configure(text=(f'Se encontraron {len(r["filas"])} registros. '+r['mensaje']) if r['filas'] else 'No hay datos para los filtros seleccionados.')
            self.habilitar_exportacion(True)
            indicadores={**r['indicadores'],**{k:v for k,v in r['totales'].items() if k.startswith('Stock ')}}
            from core.formato_numerico import format_moneda
            self.indicadores.configure(text=' · '.join(f'{k}: {format_moneda(v) if k.startswith("Valor") else texto(v)}' for k,v in indicadores.items()))
            graficos='\n'.join(g['titulo']+': '+', '.join(f'{k}: {texto(v)}' for k,v in g['datos'])+' ('+g['unidad']+')' for g in r['graficos'])
            informacion=ttk.Frame(detalle); detalle.add(informacion,text='Notas y gráficos')
            contenido=tk.Text(informacion,wrap='word',height=8,font=('Segoe UI',10),relief='flat',padx=SPACING_MD,pady=SPACING_MD)
            scroll=ttk.Scrollbar(informacion,orient='vertical',command=contenido.yview)
            scroll.pack(side='right',fill='y'); contenido.pack(fill='both',expand=True); contenido.configure(yscrollcommand=scroll.set)
            contenido.insert('1.0','Generado: '+texto(r['generado'])+'\nFiltros: '+(', '.join(f'{etiqueta(k)}: {v}' for k,v in etiquetas.items()) or 'Todos')+'\n\n'+'\n\n'.join(r['notas'])+('\n\nGráficos exportados:\n'+graficos if graficos else '')+('\n\n'+r['mensaje'] if r['mensaje'] else ''))
            contenido.configure(state='disabled')
        self.trabajo.ejecutar(lambda:obtener_datos_reporte(tipo,filtros),mostrar,
            lambda e:self.error(e) if solicitud==self.solicitud else None)
    def exportar(self,formato):
        if self.trabajo.ocupado or self.exportaciones.ocupado: return
        if not self.reporte or self.reporte['titulo']!=self.tipo.get() or self.reporte['filtros']!={k:v for k,v in self.filtros().items() if v not in ('','Todos','Todas',None)}:
            messagebox.showinfo('Reportes','Espere a que termine de cargar la vista previa actual.',parent=self.root); return
        carpeta=ruta('reportes','carpeta'); carpeta.mkdir(parents=True,exist_ok=True)
        sugerido=ruta_disponible(carpeta/nombre_archivo(self.reporte,formato))
        archivo=filedialog.asksaveasfilename(parent=self.root,initialdir=str(carpeta),initialfile=sugerido.name,defaultextension='.'+formato,filetypes=[(formato.upper(),'*.'+formato)])
        if not archivo: return
        r=deepcopy(self.reporte)
        self.exportaciones.ejecutar(lambda:(exportar_pdf(r,archivo) if formato=='pdf' else exportar_excel(r,archivo)),lambda destino:messagebox.showinfo('Reportes','Reporte exportado: '+str(destino),parent=self.root))
