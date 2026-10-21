from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
from tkinter import ttk
from ui.ui_theme import crear_panel,COLORES
from ui.tareas_ui import TrabajosUI
from core.estado_sistema import obtener_estado_sistema,comprobar,ACCIONES

class EstadoUI:
    def __init__(self,padre,root,al_actualizar=None):
        self.root=root; self.trabajo=TrabajosUI(root); self.al_actualizar=al_actualizar
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Estado del sistema','Disponibilidad central y actividad de los servicios.',[('Actualizar',self.actualizar)])
        self.actualizado=ttk.Label(padre,text='Sin comprobar'); self.actualizado.pack(anchor='w',pady=SPACING_SM)
        f=ttk.Frame(padre,style='App.TFrame'); f.pack(fill='both',expand=True)
        from core.system_state import NAMES
        from ui.ui_components import StandardTreeview,DetailPanel
        self.detalle=DetailPanel(f,'Servicio seleccionado');self.detalle.pack(side='right',fill='y',padx=(12,0))
        self.t=StandardTreeview(f,('servicio','estado','actividad','detalle','actualizado'),
            ('Servicio','Estado','Actividad','Detalle','Última actualización'),(140,110,100,240,150))
        self.filas={}
        self.t.bind('<<TreeviewSelect>>',self.seleccionar)
        ttk.Button(self.detalle.body,text='Comprobar componente',command=self.probar_seleccion,style='Secondary.TButton').pack(anchor='w',pady=(12,0))
        for tono in ('success','warning','danger','info'):
            self.t.tag_configure(tono,background=COLORES[tono+'_bg'],foreground=COLORES[tono+'_text'])
        self.actualizar()
        from ui.service_state_ui import StateBinding
        self.binding=StateBinding(root,self.mostrar_snapshot,self.actualizado)

    def mostrar_snapshot(self,snapshot):
        from core.system_state import NAMES
        from datetime import datetime
        self.mostrar({'componentes':{NAMES.get(k,k):v for k,v in snapshot.items()},
                      'snapshot':snapshot,'actualizado':datetime.now().astimezone()})

    def mostrar(self,r):
        from core.formato_numerico import format_campo
        self.actualizado.configure(text='Última actualización: '+str(format_campo('fecha',r['actualizado'])))
        for n,c in r['componentes'].items(): self.pintar(n,c)
        self.seleccionar()
        if self.al_actualizar: self.al_actualizar(r)
    def pintar(self,n,c):
        from core.system_state import format_service_state
        from core.formato_numerico import format_campo
        from ui.ui_theme import tono_estado
        view=format_service_state(c);self.filas[n]=c
        values=(n,view['text'],c.get('activity','IDLE'),c['message'],format_campo('fecha',c.get('updated_at')) or '—')
        options={'values':values,'tags':(tono_estado(view['text']),)}
        if self.t.exists(n):self.t.item(n,**options)
        else:self.t.insert('','end',iid=n,**options)
    def seleccionar(self,_=None):
        if not self.t.selection():return
        n=self.t.selection()[0];c=self.filas[n]
        from core.system_state import format_service_state
        self.detalle.set(n+'\n\n'+format_service_state(c)['text']+'\n\n'+c['message'])
    def probar_seleccion(self):
        if not self.t.selection():return
        n=self.t.selection()[0]
        check={'SFace':'Reconocimiento facial','Vosk':'Reconocimiento de voz','Voz de JARVIS':'Motor TTS'}.get(n,n)
        if check in ACCIONES:self.probar(check)
        else:self.detalle.set(n+'\n\nSe verifica durante su uso; no requiere una comprobación independiente.')
    def actualizar(self):self.mostrar(obtener_estado_sistema())
    def probar(self,n):self.trabajo.ejecutar(lambda:comprobar(n),lambda r:self.actualizar())
