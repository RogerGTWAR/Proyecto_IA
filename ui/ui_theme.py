"""Sistema visual compartido: paleta, tipografía, espaciado y componentes."""
pass

import tkinter as tk
from tkinter import ttk


# ttkbootstrap aplica un tema automático también a widgets tk; conservar colores explícitos.
try:
    import ttkbootstrap
    _TK_OPTIONS = {"autostyle": False}
except ImportError:
    _TK_OPTIONS = {}

def marco_visual(padre, **opciones):
    return tk.Frame(padre, **opciones, **_TK_OPTIONS)

def etiqueta_visual(padre, **opciones):
    return tk.Label(padre, **opciones, **_TK_OPTIONS)

def lienzo_visual(padre, **opciones):
    return tk.Canvas(padre, **opciones, **_TK_OPTIONS)

def boton_visual(padre, **opciones):
    return tk.Button(padre, **opciones, **_TK_OPTIONS)

COLOR_HEADER = "#16324F"
COLOR_SECONDARY = "#214C73"
COLOR_ACTION = COLOR_SECONDARY
COLOR_SUCCESS = "#10B981"
COLOR_DANGER = "#EF4444"
COLOR_WARNING = "#F59E0B"
COLOR_BG = "#F4F7FB"
COLOR_PANEL = "#FFFFFF"
COLOR_BORDER = "#D9E2EC"
COLOR_TEXT = "#1F2937"
COLOR_MUTED = "#64748B"
COLORES = {
    "primario": COLOR_HEADER, "azul": COLOR_ACTION, "azul_claro": "#EAF0F6",
    "acento": "#14B8A6", "verde": COLOR_SUCCESS, "aviso": COLOR_WARNING,
    "peligro": COLOR_DANGER, "fondo": COLOR_BG, "tarjeta": COLOR_PANEL,
    "texto": COLOR_TEXT, "secundario": COLOR_MUTED, "borde": COLOR_BORDER,
    "azul_secundario": COLOR_SECONDARY, "texto_oscuro": COLOR_PANEL,
    "texto_header": "#C5D5E4", "seleccion": "#DCEAF5", "fila_alterna": "#F8FAFD",
    "success_bg": "#E7F7F0", "success_text": "#15803d",
    "danger_bg": "#FDECEC", "danger_text": "#b91c1c",
    "warning_bg": "#FFF4DF", "warning_text": "#a16207",
    "info_bg": "#EAF2FA", "info_text": "#2563eb",
    "video": "#102438", "chat_usuario": "#E0F3F0", "chat_agente": COLOR_PANEL,
}
PRIMARY, SECONDARY = COLOR_HEADER, COLOR_SECONDARY
BACKGROUND, SURFACE, BORDER = COLOR_BG, COLOR_PANEL, COLOR_BORDER
TEXT_PRIMARY, TEXT_SECONDARY = COLOR_TEXT, COLOR_MUTED
SUCCESS, WARNING, DANGER = COLORES['success_text'], COLORES['warning_text'], COLORES['danger_text']
INFO, SELECTED, DISABLED = COLORES['info_text'], COLORES['seleccion'], COLOR_MUTED
FONTS = {"titulo": ("Segoe UI", 20, "bold"), "seccion": ("Segoe UI", 12, "bold"),
         "cuerpo": ("Segoe UI", 10), "pequena": ("Segoe UI", 9),
         "kpi": ("Segoe UI", 17, "bold"), "boton": ("Segoe UI", 9, "bold")}
SPACING_XS=4
SPACING_SM=8
SPACING_MD=12
SPACING_LG=16
SPACING_XL=24
SPACING_CARD=16
XS, SM, MD, LG, XL = SPACING_XS, SPACING_SM, SPACING_MD, SPACING_LG, SPACING_XL
SPACING = {"pagina": (16,12), "tarjeta": SPACING_CARD, "separacion": SPACING_MD, "campo": SPACING_SM}
SIZES = {'ventana_minima':(1100,650),'fila_tabla':30,'sidebar':200,'detalle':260}


def tono_estado(estado):
    """Semántica visual común; no decide el estado de ningún servicio."""
    import unicodedata
    clave=''.join(c for c in unicodedata.normalize('NFD',str(estado).upper()) if not unicodedata.combining(c))
    if any(v in clave for v in ('OFFLINE','ERROR','AGOTADO','CRITIC','SIN CONEXION')): return 'danger'
    if any(v in clave for v in ('DEGRA','SIMULA','PENDIENT','BAJO','ALTA','ALTO','MEDIA','MEDIO','VERIFICANDO','SIN VERIFICAR')): return 'warning'
    if any(v in clave for v in ('ONLINE','NORMAL','RESUELT','ATENDIDA','REVISADA','EN LINEA','LISTO','CALIBRADO','DISPONIBLE','CONECTADA')): return 'success'
    return 'info'


def configurar_estilos(ventana):
    estilo = getattr(ventana, "style", None) or ttk.Style(ventana)
    ventana.option_add("*Text.Font", FONTS["cuerpo"])
    ventana.option_add("*Toplevel.background", COLOR_BG)
    ventana.option_add("*TButton.cursor", "hand2")
    estilo.configure(".", font=FONTS["cuerpo"])
    estilo.configure("TFrame", background=COLOR_PANEL)
    estilo.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=FONTS["cuerpo"])
    for nombre,color in (("App",COLOR_BG),("Card",COLOR_PANEL),("Header",COLOR_HEADER),("Sidebar",COLOR_HEADER)):
        estilo.configure(nombre+".TFrame", background=color, relief="flat", borderwidth=0)
    estilo.configure("HeaderTitle.TLabel", background=COLOR_HEADER, foreground=COLOR_PANEL, font=('Segoe UI',16,'bold'))
    estilo.configure("HeaderSub.TLabel", background=COLOR_HEADER, foreground=COLORES["texto_header"], font=FONTS["pequena"])
    for nombre,fuente,color in (("Titulo",FONTS["titulo"],COLOR_TEXT),("Seccion",FONTS["seccion"],COLOR_TEXT),("Subtitulo",FONTS["cuerpo"],COLOR_MUTED)):
        estilo.configure(nombre+".TLabel", background=COLOR_BG, foreground=color, font=fuente)
    estilo.configure("CardTitle.TLabel", background=COLOR_PANEL, foreground=COLOR_MUTED, font=FONTS["pequena"])
    estilo.configure("CardValue.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=FONTS["kpi"])
    for nombre,fondo,activo,texto in (("Primary",COLOR_HEADER,COLOR_SECONDARY,COLOR_PANEL),
            ("Action",COLOR_SECONDARY,COLOR_HEADER,COLOR_PANEL),
            ("Success",COLORES['success_text'],"#066B4D",COLOR_PANEL),
            ("Danger",COLOR_DANGER,"#D73343",COLOR_PANEL),
            ("Warning",COLORES['warning_bg'],COLOR_WARNING,COLORES['warning_text']),
            ("Secondary",COLORES["azul_claro"],"#DCE6F0",COLOR_HEADER)):
        estilo.configure(nombre+".TButton", background=fondo, foreground=texto, padding=(SPACING_MD,6),
                         font=FONTS["boton"], borderwidth=0, relief="flat", focusthickness=2, focuscolor=COLORES["acento"])
        estilo.map(nombre+".TButton", background=[("disabled",COLORES["azul_claro"]),("pressed",activo),("active",activo)],
                   foreground=[("disabled",COLOR_MUTED)])
    for nombre in ('Ghost','Icon'):
        estilo.configure(nombre+'.TButton',background=COLOR_PANEL,foreground=COLOR_SECONDARY,
                         padding=(SPACING_MD,6),font=FONTS['boton'],borderwidth=0)
        estilo.map(nombre+'.TButton',background=[('active',COLORES['azul_claro'])],foreground=[('disabled',DISABLED)])
    estilo.configure("TButton", padding=(SPACING_MD,6), font=FONTS["boton"])
    estilo.configure('Secondary.TMenubutton',padding=(SPACING_MD,6),font=FONTS['boton'],background=COLORES['azul_claro'],foreground=COLOR_HEADER)
    estilo.configure("Treeview", background=COLOR_PANEL, fieldbackground=COLOR_PANEL, foreground=COLOR_TEXT,
                     rowheight=SIZES['fila_tabla'],borderwidth=0,font=FONTS["cuerpo"])
    estilo.configure("Treeview.Heading", background=COLORES["azul_claro"],foreground=COLOR_HEADER,
                     relief="flat",padding=(SPACING_MD,SPACING_SM),font=FONTS["boton"])
    estilo.map("Treeview",background=[("selected",COLORES["seleccion"])],foreground=[("selected",COLOR_HEADER)])
    estilo.configure("TNotebook",background=COLOR_BG,borderwidth=0)
    estilo.configure("Workspace.TNotebook",background=COLOR_BG,borderwidth=0)
    estilo.layout("Workspace.TNotebook.Tab",[])
    estilo.configure("TNotebook.Tab",padding=(SPACING_CARD,SPACING_MD),font=FONTS["boton"])
    estilo.configure("TLabelframe",background=COLOR_PANEL,relief="flat",borderwidth=0)
    estilo.configure("TLabelframe.Label",background=COLOR_PANEL,foreground=COLOR_HEADER,font=("Segoe UI",11,"bold"))
    estilo.configure("TEntry",padding=(SPACING_SM,5),fieldbackground=COLOR_PANEL,foreground=COLOR_TEXT,bordercolor=COLOR_BORDER)
    estilo.map("TEntry",bordercolor=[("focus",COLORES["acento"])])
    estilo.configure("TCombobox",padding=(SPACING_SM,5),fieldbackground=COLOR_PANEL,foreground=COLOR_TEXT,bordercolor=COLOR_BORDER)
    estilo.map("TCombobox",fieldbackground=[("readonly",COLOR_PANEL)],foreground=[("readonly",COLOR_TEXT)])
    estilo.configure("TCheckbutton",background=COLOR_PANEL,font=FONTS["pequena"])
    estilo.configure("Status.TFrame",background=COLOR_BG)
    estilo.configure("Status.TLabel",background=COLOR_BG,foreground=COLOR_MUTED,font=FONTS["pequena"])
    return estilo


def crear_panel(padre,padding=SPACING_CARD):
    return ttk.Frame(padre,style="Card.TFrame",padding=padding)


def crear_titulo(padre,texto):
    return ttk.Label(padre,text=texto,style="Seccion.TLabel")


def crear_subtitulo(padre,texto):
    return ttk.Label(padre,text=texto,style="Subtitulo.TLabel")


def crear_indicador(padre,texto,color=COLOR_SUCCESS):
    return etiqueta_visual(padre,text="●  "+texto,bg=COLORES["success_bg"],fg=COLORES["success_text"],font=('Segoe UI',8),padx=SPACING_SM,pady=SPACING_XS)


def crear_kpi(padre,titulo,variable,descripcion="",tono="info"):
    tarjeta=crear_panel(padre,(SPACING_MD,SPACING_SM))
    franja=marco_visual(tarjeta,bg=COLORES[tono+"_text"],height=3)
    franja.pack(fill="x",pady=(0,6))
    nombre=ttk.Label(tarjeta,text=titulo,style="CardTitle.TLabel",wraplength=180);nombre.pack(anchor='w')
    tarjeta.bind('<Configure>',lambda e:nombre.configure(wraplength=max(90,e.width-24)),add='+')
    valor=ttk.Label(tarjeta,textvariable=variable,style="CardValue.TLabel")
    valor.pack(anchor="w",pady=(SPACING_XS,0))
    def actualizar_fuente(*_):
        largo=len(variable.get())
        valor.configure(font=('Segoe UI',17 if largo<=5 else 15 if largo<=8 else 12,'bold'))
    identificador=variable.trace_add('write',actualizar_fuente)
    def limpiar_fuente(event):
        if event.widget==tarjeta:
            try:variable.trace_remove('write',identificador)
            except tk.TclError:pass
    tarjeta.bind('<Destroy>',limpiar_fuente);actualizar_fuente()
    if descripcion:
        ttk.Label(tarjeta,text=descripcion,style="CardTitle.TLabel").pack(anchor="w",pady=(1,0))
    return tarjeta


def crear_badge(padre,variable):
    etiqueta=etiqueta_visual(padre,textvariable=variable,font=FONTS["boton"],padx=SPACING_MD,pady=SPACING_SM)
    def pintar(*_):
        tono=tono_estado(variable.get())
        etiqueta.configure(bg=COLORES[tono+"_bg"],fg=COLORES[tono+"_text"])
    identificador=variable.trace_add("write",pintar)
    def limpiar(_):
        try: variable.trace_remove("write",identificador)
        except tk.TclError: pass
    etiqueta.bind("<Destroy>",limpiar); pintar()
    return etiqueta


class Navegacion(ttk.Frame):
    """Páginas existentes agrupadas en una navegación lateral."""
    def __init__(self,padre):
        super().__init__(padre,style="App.TFrame")
        self.sidebar=marco_visual(self,bg=COLOR_HEADER,width=SIZES['sidebar'])
        self.sidebar.pack(side="left",fill="y"); self.sidebar.pack_propagate(False)
        etiqueta_visual(self.sidebar,text="INVENTARIO IA",bg=COLOR_HEADER,fg=COLOR_PANEL,
                        font=("Segoe UI",12,"bold")).pack(anchor="w",padx=SPACING_CARD,pady=(SPACING_CARD,SPACING_XS))
        etiqueta_visual(self.sidebar,text="CONTROL DEL ALMACÉN",bg=COLOR_HEADER,
                        fg=COLORES["texto_header"],font=("Segoe UI",8)).pack(anchor="w",padx=SPACING_CARD,pady=(0,SPACING_SM))
        contenedor_menu=marco_visual(self.sidebar,bg=COLOR_HEADER)
        contenedor_menu.pack(fill="both",expand=True,pady=(0,SPACING_XS))
        self.canvas_menu=lienzo_visual(contenedor_menu,bg=COLOR_HEADER,highlightthickness=0)
        barra_menu=ttk.Scrollbar(contenedor_menu,orient="vertical",command=self.canvas_menu.yview)
        barra_menu.pack(side="right",fill="y")
        self.canvas_menu.configure(yscrollcommand=barra_menu.set)
        self.canvas_menu.pack(side="left",fill="both",expand=True)
        self.menu=marco_visual(self.canvas_menu,bg=COLOR_HEADER)
        self.menu_item=self.canvas_menu.create_window((0,0),window=self.menu,anchor="nw")
        self.menu.bind("<Configure>",lambda _:self.canvas_menu.configure(scrollregion=self.canvas_menu.bbox("all")))
        self.canvas_menu.bind("<Configure>",lambda e:self.canvas_menu.itemconfigure(self.menu_item,width=e.width))
        self.canvas_menu.bind("<MouseWheel>",lambda e:self.canvas_menu.yview_scroll(-int(e.delta/120),"units"))
        self.notebook=ttk.Notebook(self,style="Workspace.TNotebook")
        self.notebook.pack(side="left",fill="both",expand=True)
        self.botones=[]; self.paginas=[];self.encabezados=[]
        self.sin_acceso=ttk.Label(self.notebook,text="Sin páginas disponibles.",style="Subtitulo.TLabel",wraplength=650)
        self.notebook.bind("<<NotebookTabChanged>>",self._seleccion)
        etiqueta_visual(self.sidebar,text="GESTIÓN INTELIGENTE",bg=COLOR_HEADER,
                        fg=COLORES["texto_header"],font=("Segoe UI",8)).pack(side="bottom",pady=SPACING_SM)
    def add(self,pagina,text):
        boton=boton_visual(self.menu,text="·   "+text,anchor="w",bd=0,relief="flat",
            cursor="hand2",font=("Segoe UI",9),padx=SPACING_MD,pady=2,bg=COLOR_HEADER,
            fg=COLORES["texto_header"],activebackground=COLOR_SECONDARY,
            activeforeground=COLOR_PANEL,command=lambda:self._abrir(pagina,text),takefocus=True,wraplength=170)
        boton.bind("<MouseWheel>",lambda e:self.canvas_menu.yview_scroll(-int(e.delta/120),"units"))
        boton.bind('<Enter>',lambda _,b=boton:b.configure(bg=COLOR_SECONDARY))
        boton.bind('<Leave>',lambda _,b=boton,p=pagina:b.configure(bg=COLOR_SECONDARY if self.notebook.select()==str(p) else COLOR_HEADER))
        self.paginas.append((pagina,text,boton))
        self.botones.append((str(pagina),boton))
        self.refrescar()
    def _abrir(self,pagina,titulo):
        self.notebook.select(pagina)
    def refrescar(self):
        for w in self.encabezados:w.destroy()
        self.encabezados=[]
        indice=0
        for pagina,text,boton in self.paginas:
            self.notebook.insert("end" if indice>=len(self.notebook.tabs()) else indice,pagina,text=text)
            boton.pack_forget(); indice+=1
        grupos=(('',('Dashboard',)),('ALMACÉN',('Productos','Movimientos','Historial','Mapa','Alertas','Conteo de inventario')),
                ('INTELIGENCIA',('Análisis IA','Predicción','Anomalías','JARVIS','Vigilancia')),('PERSONAL',('Empleados',)),
                ('SISTEMA',('Reportes','Estado','Configuración')))
        ubicados=set()
        for grupo,nombres in grupos:
            disponibles=[(p,t,b) for p,t,b in self.paginas if t in nombres]
            if not disponibles:continue
            if grupo:
                titulo=etiqueta_visual(self.menu,text=grupo,bg=COLOR_HEADER,fg=COLORES['texto_header'],font=('Segoe UI',8,'bold'))
                titulo.pack(anchor='w',padx=SPACING_CARD,pady=(SPACING_SM,SPACING_XS));self.encabezados.append(titulo)
            for p,t,b in disponibles:b.pack(fill='x',padx=SPACING_SM,pady=1);ubicados.add(t)
        for p,t,b in self.paginas:
            if t not in ubicados:b.pack(fill='x',padx=SPACING_MD,pady=SPACING_XS)
        if indice: self.sin_acceso.place_forget()
        else: self.sin_acceso.place(relx=.5,rely=.5,anchor="center")
        self._seleccion()
    def _seleccion(self,*_):
        actual=self.notebook.select()
        for pagina,boton in self.botones:
            boton.configure(bg=COLOR_SECONDARY if actual==pagina else COLOR_HEADER,
                fg=COLOR_PANEL if actual==pagina else COLORES["texto_header"],
                font=("Segoe UI",9,"bold" if actual==pagina else "normal"))
            if actual==pagina: self.after_idle(lambda b=boton:self._mostrar_seleccion(b))
    def _mostrar_seleccion(self,boton):
        if not boton.winfo_exists() or not boton.winfo_manager(): return
        alto=max(1,self.menu.winfo_height())
        inicio=self.canvas_menu.canvasy(0)
        fin=inicio+self.canvas_menu.winfo_height()
        arriba=boton.winfo_y(); abajo=arriba+boton.winfo_height()
        if arriba<inicio: self.canvas_menu.yview_moveto(arriba/alto)
        elif abajo>fin: self.canvas_menu.yview_moveto((abajo-self.canvas_menu.winfo_height())/alto)


class ChatConversacion(ttk.Frame):
    """Mensajes en tarjetas; únicamente presentación, sin lógica del agente."""
    def __init__(self,padre,**_):
        super().__init__(padre,style="App.TFrame")
        self.canvas=lienzo_visual(self,bg=COLOR_BG,highlightthickness=0,height=200)
        barra=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=barra.set)
        barra.pack(side="right",fill="y"); self.canvas.pack(side="left",fill="both",expand=True)
        self.mensajes=marco_visual(self.canvas,bg=COLOR_BG)
        self.item=self.canvas.create_window((0,0),window=self.mensajes,anchor="nw")
        self.etiquetas=[]
        self.canvas.bind("<Configure>",self._ajustar)
        self.mensajes.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<MouseWheel>",self._rueda)
        self.mensajes.bind("<MouseWheel>",self._rueda)
    def _rueda(self,event):
        self.canvas.yview_scroll(-int(event.delta/120),"units"); return "break"
    def _ajustar(self,event):
        self.canvas.itemconfigure(self.item,width=event.width)
        for label in self.etiquetas: label.configure(wraplength=max(40,int((event.width-32)*.68)-24))
    def agregar(self,autor,texto,acciones=None):
        usuario=autor in {"Usuario","Tú"}
        fila=marco_visual(self.mensajes,bg=COLOR_BG); fila.pack(fill="x",padx=SPACING_MD,pady=6)
        color=COLORES["chat_usuario"] if usuario else COLORES["chat_agente"]
        burbuja=marco_visual(fila,bg=color,padx=12,pady=8,highlightthickness=1,highlightbackground=COLOR_BORDER)
        burbuja.pack(side="right" if usuario else "left")
        etiqueta_visual(burbuja,text="TÚ" if usuario else "JARVIS",bg=color,fg=COLOR_SECONDARY,font=("Segoe UI",9,"bold")).pack(anchor="w",pady=(0,SPACING_SM))
        label=etiqueta_visual(burbuja,text=texto,bg=color,fg=COLOR_TEXT,font=FONTS["cuerpo"],justify="left",wraplength=max(40,int((self.canvas.winfo_width()-32)*.68)-24))
        label.pack(anchor="w"); self.etiquetas.append(label)
        for titulo,comando in acciones or ():
            ttk.Button(burbuja,text=titulo,command=comando,style='Secondary.TButton').pack(anchor='w',pady=(SPACING_SM,0))
        for w in (fila,burbuja,label): w.bind("<MouseWheel>",self._rueda)
        self.update_idletasks(); self.canvas.configure(scrollregion=self.canvas.bbox("all")); self.canvas.yview_moveto(1)
    def limpiar(self):
        for hijo in self.mensajes.winfo_children(): hijo.destroy()
        self.etiquetas.clear(); self.canvas.configure(scrollregion=(0,0,0,0))


def crear_pagina(notebook):
    """Contenido adaptable con scroll cuando la altura disponible es insuficiente."""
    pagina=ttk.Frame(notebook,style="App.TFrame")
    canvas=lienzo_visual(pagina,bg=COLOR_BG,highlightthickness=0)
    barra=ttk.Scrollbar(pagina,orient="vertical",command=canvas.yview)
    canvas.configure(yscrollcommand=barra.set)
    canvas.pack(side="left",fill="both",expand=True)
    contenido=ttk.Frame(canvas,style="App.TFrame",padding=SPACING["pagina"])
    contenido.pagina=pagina
    item=canvas.create_window((0,0),window=contenido,anchor="nw")
    pendiente={"id":None}
    def ajustar():
        pendiente["id"]=None
        ancho=max(1,canvas.winfo_width())
        alto=max(canvas.winfo_height(),contenido.winfo_reqheight())
        canvas.itemconfigure(item,width=ancho,height=alto)
        canvas.configure(scrollregion=(0,0,ancho,alto))
        if contenido.winfo_reqheight()>canvas.winfo_height()+1:
            if not barra.winfo_manager(): barra.pack(side="right",fill="y")
        elif barra.winfo_manager():
            barra.pack_forget(); canvas.yview_moveto(0)
    def programar(_=None):
        if pendiente["id"] is None: pendiente["id"]=canvas.after_idle(ajustar)
    canvas.bind("<Configure>",programar); contenido.bind("<Configure>",programar)
    def rueda(event):
        objetivo=event.widget
        while objetivo is not None:
            if objetivo==contenido or objetivo==canvas:
                if contenido.winfo_reqheight()>canvas.winfo_height():
                    canvas.yview_scroll(-int(event.delta/120),"units")
                    return "break"
                return
            if isinstance(objetivo,(ttk.Treeview,tk.Text)):
                return
            objetivo=getattr(objetivo,"master",None)
    # Bind propio del toplevel: no reemplaza bindings de widgets ni otras ventanas.
    identificador=pagina.winfo_toplevel().bind("<MouseWheel>",rueda,add="+")
    def destruir(event):
        if event.widget!=pagina: return
        if pendiente["id"] is not None:
            try: canvas.after_cancel(pendiente["id"])
            except tk.TclError: pass
        try: pagina.winfo_toplevel().unbind("<MouseWheel>",identificador)
        except tk.TclError: pass
    pagina.bind("<Destroy>",destruir)
    return contenido
