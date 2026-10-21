"""Distribución adaptable de acciones y campos, compartida por las pantallas."""
from tkinter import ttk
from ui.ui_theme import SPACING_SM, SPACING_MD, SPACING_LG
from core.formato_numerico import format_campo


class ModuleHeader(ttk.Frame):
    def __init__(self, padre, title, subtitle='', actions=()):
        super().__init__(padre,style='App.TFrame')
        self.pack(fill='x',pady=(0,SPACING_MD))
        texto=ttk.Frame(self,style='App.TFrame');texto.pack(side='left',fill='x',expand=True)
        ttk.Label(texto,text=title,style='Titulo.TLabel').pack(anchor='w')
        if subtitle:
            label=ttk.Label(texto,text=subtitle,style='Subtitulo.TLabel',wraplength=700)
            label.pack(anchor='w',pady=(4,0))
            texto.bind('<Configure>',lambda e:label.configure(wraplength=max(200,e.width)))
        for titulo,comando in actions:
            ActionButton(self,text=titulo,command=comando,variant='SECONDARY').pack(side='right',padx=4)


class Card(ttk.Frame):
    def __init__(self,padre,title='',padding=SPACING_MD,**kwargs):
        super().__init__(padre,style='Card.TFrame',padding=padding,**kwargs)
        if title:ttk.Label(self,text=title,style='CardTitle.TLabel').pack(anchor='w',pady=(0,8))


def KpiCard(padre,title,variable,description='',tone='info'):
    from ui.ui_theme import crear_kpi
    return crear_kpi(padre,title,variable,description,tone)


class ActionButton(ttk.Button):
    def __init__(self,padre,variant='SECONDARY',**kwargs):
        estilos={'PRIMARY':'Primary','SECONDARY':'Secondary','DANGER':'Danger','GHOST':'Ghost','ICON':'Icon'}
        super().__init__(padre,style=estilos[variant.upper()]+'.TButton',**kwargs)


class FilterBar(Card):
    """Campos compactos en una rejilla que se adapta al ancho disponible."""
    def __init__(self,padre,**kwargs):
        super().__init__(padre,**kwargs);self.fields=[]
        self.bind('<Configure>',self._layout)
    def add(self,title,values=None,variable=None,width=18):
        f=ttk.Frame(self,style='Card.TFrame')
        ttk.Label(f,text=title,style='CardTitle.TLabel').pack(anchor='w',pady=(0,4))
        options={'width':width}
        if variable is not None:options['textvariable']=variable
        w=ttk.Entry(f,**options) if values is None else ttk.Combobox(f,values=values,state='readonly',**options)
        w.pack(fill='x');self.fields.append(f);self._layout();return w
    def _layout(self,_=None):
        cols=max(1,min(len(self.fields) or 1,max(1,self.winfo_width())//180))
        for c in range(len(self.fields)):self.columnconfigure(c,weight=1 if c<cols else 0)
        for i,f in enumerate(self.fields):f.grid(row=i//cols,column=i%cols,sticky='ew',padx=(0,8),pady=(0,4))


def StatusBadge(padre,variable):
    from ui.ui_theme import crear_badge
    return crear_badge(padre,variable)


class EmptyState(ttk.Label):
    def __init__(self,padre,text='No se encontraron resultados.',**kwargs):
        super().__init__(padre,text=text,style='CardTitle.TLabel',anchor='center',justify='center',**kwargs)


class LoadingState(EmptyState):
    def __init__(self,padre,text='Cargando…',**kwargs):super().__init__(padre,text=text,**kwargs)


class DetailPanel(Card):
    def __init__(self,padre,title='Detalle',**kwargs):
        import tkinter as tk
        from ui.ui_theme import SIZES,lienzo_visual,COLOR_PANEL
        super().__init__(padre,width=SIZES['detalle'],**kwargs)
        self.pack_propagate(False)
        ttk.Label(self,text=title,style='Seccion.TLabel').pack(anchor='w',pady=(0,8))
        canvas=lienzo_visual(self,background=COLOR_PANEL,highlightthickness=0,width=1,height=1)
        scroll=ttk.Scrollbar(self,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        self.body=ttk.Frame(canvas,style='Card.TFrame')
        item=canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=max(1,e.width)))
        self.value=tk.StringVar(value='Seleccione un registro para ver su detalle.')
        self.label=ttk.Label(self.body,textvariable=self.value,wraplength=SIZES['detalle']-40,justify='left')
        self.label.pack(fill='x',anchor='nw')
        self.body.bind('<Configure>',lambda e:self.label.configure(wraplength=max(100,e.width)),add='+')
    def set(self,text):self.value.set(text)


class Tooltip:
    """Texto complementario sin alterar el contenido ni capturar el foco."""
    def __init__(self,widget,text):
        self.widget=widget;self.text=text;self.window=None;self.pending=None
        widget.bind('<Enter>',self.schedule,add='+');widget.bind('<Leave>',self.hide,add='+')
        widget.bind('<Destroy>',self.hide,add='+')
    def schedule(self,_=None):
        self.hide();self.pending=self.widget.after(600,self.show)
    def show(self):
        import tkinter as tk
        self.pending=None
        if not self.widget.winfo_exists():return
        texto=self.text() if callable(self.text) else self.text
        if not texto:return
        self.window=tk.Toplevel(self.widget);self.window.overrideredirect(True)
        self.window.geometry('+%d+%d'%(self.widget.winfo_pointerx()+12,self.widget.winfo_pointery()+16))
        ttk.Label(self.window,text=texto,wraplength=420,padding=8).pack()
    def hide(self,_=None):
        if self.pending:
            try:self.widget.after_cancel(self.pending)
            except Exception:pass
            self.pending=None
        if self.window:
            try:self.window.destroy()
            except Exception:pass
            self.window=None


def StandardTreeview(padre,columnas,titulos,anchos,horizontal=True):
    """Tabla común con scroll, selección, bandas y mensaje de vacío."""
    from ui.ui_theme import COLORES
    zona=ttk.Frame(padre,style='Card.TFrame',padding=1);zona.pack(fill='both',expand=True,pady=(8,0))
    tree=ttk.Treeview(zona,columns=columnas,show='headings',selectmode='browse',height=6)
    tree.grid(row=0,column=0,sticky='nsew');zona.rowconfigure(0,weight=1);zona.columnconfigure(0,weight=1)
    for c,t,a in zip(columnas,titulos,anchos):tree.heading(c,text=t);tree.column(c,width=a,minwidth=60)
    sy=ttk.Scrollbar(zona,orient='vertical',command=tree.yview);sy.grid(row=0,column=1,sticky='ns');tree.configure(yscrollcommand=sy.set)
    sx=None
    if horizontal:
        sx=ttk.Scrollbar(zona,orient='horizontal',command=tree.xview);sx.grid(row=1,column=0,sticky='ew');tree.configure(xscrollcommand=sx.set)
    for tag,color in (('par','tarjeta'),('impar','fila_alterna')):tree.tag_configure(tag,background=COLORES[color])
    ajustar_columnas(tree,zona,anchos,sx)
    empty=EmptyState(tree);pending={'id':None}
    def check(_=None):
        pending['id']=None
        if not tree.winfo_exists():return
        if tree.get_children():empty.place_forget()
        else:empty.place(relx=.5,rely=.55,anchor='center')
        pending['id']=tree.after(300,check)
    def close(event):
        if event.widget==tree and pending['id']:
            tree.after_cancel(pending['id']);pending['id']=None
    tree.bind('<Destroy>',close,add='+');check()
    tooltip=Tooltip(tree,lambda:celda['texto']);celda={'clave':None,'texto':''}
    def move(event):
        fila=tree.identify_row(event.y);col=tree.identify_column(event.x)
        clave=(fila,col)
        if clave==celda['clave']:return
        celda['clave']=clave;tooltip.hide();celda['texto']=''
        if fila and col and col!='#0':
            visibles=tree['displaycolumns']
            if visibles in ('#all',('#all',)):visibles=tree['columns']
            indice=int(col[1:])-1
            if indice<len(visibles):celda['texto']=str(tree.set(fila,visibles[indice]));tooltip.schedule()
    tree.bind('<Motion>',move,add='+')
    tree.bind('<Double-1>',lambda _:ver_detalle_fila(tree,padre.winfo_toplevel()))
    tree.bind('<Return>',lambda _:ver_detalle_fila(tree,padre.winfo_toplevel()))
    return tree


def ver_detalle_fila(tabla,root,titulo='Detalle del registro'):
    """Vista de solo lectura de todas las columnas, incluidas las no visibles."""
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
    if not tabla.selection():return
    valores=tabla.item(tabla.selection()[0],'values')
    ventana=tk.Toplevel(root);ventana.title(titulo);ventana.transient(root)
    ventana.geometry(f'{min(760,root.winfo_screenwidth()-80)}x{min(500,root.winfo_screenheight()-100)}')
    cuerpo=ttk.Frame(ventana,padding=16);cuerpo.pack(fill='both',expand=True)
    ttk.Label(cuerpo,text=titulo,style='Seccion.TLabel').pack(anchor='w',pady=(0,12))
    texto=ScrolledText(cuerpo,wrap='word',font=('Segoe UI',10),padx=12,pady=12,relief='flat')
    texto.pack(fill='both',expand=True)
    texto.insert('1.0','\n\n'.join(f'{tabla.heading(c,"text")}: {v}' for c,v in zip(tabla['columns'],valores)))
    texto.configure(state='disabled')
    ttk.Button(cuerpo,text='Cerrar',command=ventana.destroy,style='Secondary.TButton').pack(anchor='e',pady=(12,0))
    return ventana


def agrupar_acciones(marco,titulo,botones):
    """Presenta comandos existentes en un menú, conservando sus estados y callbacks."""
    import tkinter as tk
    menu_boton=ttk.Menubutton(marco,text=titulo,style='Secondary.TMenubutton')
    menu=tk.Menu(menu_boton,tearoff=False)
    for b in botones:
        b.pack_forget();b.grid_forget();b.accion_agrupada=True
        menu.add_command(label=b.cget('text'),command=b.invoke)
    def sincronizar():
        for i,b in enumerate(botones):
            menu.entryconfigure(i,label=b.cget('text'),state='disabled' if b.instate(['disabled']) else 'normal')
    menu.configure(postcommand=sincronizar);menu_boton.configure(menu=menu)
    menu_boton.pack(side='left',padx=4)
    return menu_boton


def ajustar_columnas(tabla,zona,anchos,barra=None):
    """Reparto visual proporcional: respeta columnas ocultas y conserva sus valores."""
    from tkinter import font as tkfont
    fuente=tkfont.Font(font=('Segoe UI',9,'bold'))
    estado={'pendiente':None,'clave':None}
    pesos=dict(zip(tabla['columns'],anchos))
    def distribuir():
        estado['pendiente']=None
        if not tabla.winfo_exists():return
        visibles=tabla['displaycolumns']
        if visibles in ('#all',('#all',)):visibles=tabla['columns']
        ancho=max(1,zona.winfo_width()-20);clave=(ancho,tuple(visibles))
        if clave==estado['clave']:return
        estado['clave']=clave
        minimos={c:max(58,min(128,fuente.measure(tabla.heading(c,'text'))+18)) for c in visibles}
        sobrante=max(0,ancho-sum(minimos.values()))
        total=sum(pesos.get(c,100) for c in visibles) or 1
        for c in visibles:
            tabla.column(c,minwidth=minimos[c],width=minimos[c]+int(sobrante*pesos.get(c,100)/total),stretch=True)
        if barra is not None:
            if sum(minimos.values())>ancho:barra.grid()
            else:barra.grid_remove()
    def programar(_=None):
        if estado['pendiente'] is None:estado['pendiente']=tabla.after_idle(distribuir)
    zona.bind('<Configure>',programar,add='+');tabla.bind('<Configure>',programar,add='+')
    def cerrar(event):
        if event.widget==tabla and estado['pendiente']:
            try:tabla.after_cancel(estado['pendiente'])
            except Exception:pass
    tabla.bind('<Destroy>',cerrar,add='+');programar()


def insertar_fila(tree, parent='', index='end', iid=None, values=None,
                  tags=None, columnas=None, **kwargs):
    """Formatear una copia de la fila e insertar una vez sin reemplazar métodos."""
    if values is not None:
        claves = tuple(tree['columns'] if columnas is None else columnas)
        kwargs['values'] = tuple(
            format_campo(claves[i], valor) if i < len(claves) else valor
            for i, valor in enumerate(values)
        )
    if isinstance(tags, str):
        tags = tree.tk.splitlist(tags)
    semanticas = tuple(tags or ())
    banda = 'par' if len(tree.get_children(parent)) % 2 == 0 else 'impar'
    # Los estados conservan prioridad visual sobre el fondo alternado.
    kwargs['tags'] = ((banda,) + semanticas
                      if not semanticas or semanticas == ('normal',) else semanticas)
    return tree.insert(parent, index, iid=iid, **kwargs)

def organizar_acciones(marco):
    """Reubicar los botones existentes sin cambiar comandos ni estados."""
    pendiente={'id':None,'distribucion':None}
    def distribuir():
        pendiente['id']=None
        if not marco.winfo_exists():return
        botones=[w for w in marco.winfo_children() if isinstance(w,(ttk.Button,ttk.Menubutton)) and not getattr(w,'accion_agrupada',False)]
        if not botones:return
        ancho=max(1,marco.winfo_width()); fila=col=ocupado=0
        clave=(ancho,tuple(w.winfo_reqwidth() for w in botones))
        if pendiente['distribucion']==clave:return
        pendiente['distribucion']=clave
        for w in botones:
            w.pack_forget();w.grid_forget()
        for w in botones:
            requerido=w.winfo_reqwidth()+SPACING_MD
            peligro='Danger' in str(w.cget('style'))
            if ocupado and (ocupado+requerido>ancho or peligro):fila+=1;col=ocupado=0
            w.grid(row=fila,column=col,sticky='w',padx=(0,SPACING_SM),pady=(SPACING_SM if peligro else 0,SPACING_SM))
            col+=1;ocupado+=requerido
    def programar(_=None):
        if pendiente['id'] is None:pendiente['id']=marco.after_idle(distribuir)
    marco.bind('<Configure>',programar,add='+');programar()
    def limpiar(event):
        if event.widget==marco and pendiente['id']:
            try:marco.after_cancel(pendiente['id'])
            except Exception:pass
    marco.bind('<Destroy>',limpiar,add='+')
    return marco

def encabezado_tarjeta(padre,titulo,descripcion=''):
    ttk.Label(padre,text=titulo,style='CardTitle.TLabel').pack(anchor='w',pady=(0,SPACING_MD))
    if descripcion:ttk.Label(padre,text=descripcion,wraplength=750).pack(anchor='w',pady=(0,SPACING_LG))
