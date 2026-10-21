"""Opciones respaldadas por funciones reales; valores persistidos centralmente."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
from copy import deepcopy
from tkinter import ttk,messagebox
import tkinter as tk
from core.config_manager import cargar_configuracion,guardar_configuracion,restaurar
from ui.ui_theme import crear_pagina,crear_panel
from ui.tareas_ui import TrabajosUI

CAMPOS={
 'vigilancia':(('camera_source','Cámara 1: fuente USB o URL',str,None),('camera_name','Cámara 1: nombre',str,None),
    ('camera_source_employees','Cámara 2: fuente USB o URL',str,None),('camera_name_employees','Cámara 2: nombre',str,None),
    ('room_name','Habitación',str,None),('presence_face_interval','Intervalo facial (segundos)',float,None),
    ('presence_exit_timeout','Tiempo para salida (segundos)',float,None),
    ('presence_notify_unknown','Notificar desconocidos',bool,None),('presence_notify_entries','Notificar entradas de empleados',bool,None),
    ('presence_notify_exits','Notificar salidas de empleados',bool,None),('presence_notify_errors','Notificar errores de cámara',bool,None)),
 'telegram':(('habilitado','Habilitar notificaciones',bool,None),('inventario','Inventario',bool,None),
             ('bot_habilitado','Conversación con JARVIS',bool,None),
             ('alertas','Alertas',bool,None),('prediccion','Predicción',bool,None),
             ('anomalias','Anomalías',bool,None),('vigilancia','Vigilancia',bool,None),
             ('facial','Empleados / Facial',bool,None),('sistema','Sistema',bool,None),
             ('nivel_minimo','Nivel mínimo',str,['TODAS','MEDIO+','ALTO+','CRÍTICO'])),
 'arduino':(('habilitado','Habilitar conexión de hardware',bool,None),('modo','Modo',str,['simulacion','hardware']),('puerto','Puerto USB serial',str,['']),('baudrate','Baudrate',int,[9600,19200,38400,57600,115200]),('timeout','Tiempo máximo de respuesta (segundos)',float,None)),
 'general':(('nombre','Nombre del sistema',str,None),('idioma','Idioma disponible',str,['Español']),('tema','Tema disponible',str,['flatly']),('ventana','Ventana inicial (ancho x alto)',str,None),('inicio','Pantalla inicial',str,['Dashboard','Productos','JARVIS','Mapa','Predicción','Anomalías','Reportes','Estado','Configuración'])),
 'inventario':(('stock_minimo','Stock mínimo para productos nuevos',float,None),('formato_fecha','Formato de fecha en reportes',str,['%Y-%m-%d','%d/%m/%Y'])),
 'facial':(('fuente_video','Cámara: índice o URL sin credenciales',str,None),('resolucion','Resolución solicitada (ancho x alto)',str,None),('motor','Motor facial existente',str,['embeddings','cnn','comparacion']),('debug','Diagnóstico visible',bool,None),('detectar_cada','Detectar cada N frames',int,None),('min_rostro','Tamaño mínimo de rostro (píxeles)',int,None)),
 'jarvis':(('tts_habilitado','Síntesis de voz habilitada',bool,None),('tts_provider_preferido','Proveedor de voz',str,['auto','edge','local']),('tts_rate_edge','Velocidad Edge (porcentaje, +10%)',str,None),('microfono','Micrófono: índice, -1 = predeterminado',int,None),('volumen','Volumen (0 a 1)',float,None),('voz','Voz Edge TTS',str,None),('velocidad','Velocidad pyttsx3 (palabras / minuto)',int,None),('modelo_vosk','Ruta del modelo Vosk',str,None),('respuesta_hablada','Responder con voz al iniciar',bool,None),('activacion','Activación JARVIS al iniciar',bool,None)),
 'prediccion':(('periodo','Ventana de consumo (días)',int,[7,30,60,90]),('minimo_historial','Mínimo de días con salidas',int,None),('horizonte','Cobertura objetivo de compra (días)',int,None)),
 'anomalias':(('periodo','Historial analizado (días)',int,[7,30,60,90]),('minimo_historial','Mínimo de movimientos previos por producto y tipo',int,None),('sensibilidad','Límite de desviaciones o razón (2 a 6)',float,None)),
 'reportes':(('carpeta','Carpeta de exportación',str,None),('formato','Formato preferido',str,['PDF','Excel']),('encabezado','Encabezado de los reportes',str,None))}
TITULOS={'arduino':'Arduino / LEDs','general':'General','inventario':'Inventario','facial':'Reconocimiento facial','jarvis':'JARVIS','prediccion':'Predicción','anomalias':'Anomalías','reportes':'Reportes'}
TITULOS['telegram']='Telegram'
TITULOS['vigilancia']='Vigilancia · Cámaras y presencia'

class ConfiguracionUI:
    def __init__(self,padre,root,al_guardar=None):
        self.root=root; self.al_guardar=al_guardar; self.controles={}; self.trabajo=TrabajosUI(root)
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Configuración del sistema','Cambios guardados en config_sistema.json. Cámara, audio y ventana aplican al abrir una nueva sesión.')
        nb=ttk.Notebook(padre); nb.pack(fill='both',expand=True)
        general=ttk.Frame(nb,style='App.TFrame');nb.add(general,text='General')
        catalogos=ttk.Notebook(general);catalogos.pack(fill='both',expand=True)
        voz_claves={'tts_habilitado','tts_provider_preferido','tts_rate_edge','microfono','volumen','voz','velocidad','modelo_vosk'}
        vistas=[(s,campos,TITULOS[s],catalogos) for s,campos in CAMPOS.items() if s not in ('telegram','arduino','jarvis','vigilancia')]
        vistas.extend([('vigilancia',CAMPOS['vigilancia'],'Vigilancia',nb),('jarvis',tuple(c for c in CAMPOS['jarvis'] if c[0] not in voz_claves),'JARVIS',nb),
                       ('jarvis',tuple(c for c in CAMPOS['jarvis'] if c[0] in voz_claves),'Voz',nb),
                       ('telegram',CAMPOS['telegram'],'Telegram',nb)])
        for s,campos,titulo_pagina,contenedor in vistas+[('arduino',CAMPOS['arduino'],'Arduino',nb)]:
            p=crear_pagina(contenedor); contenedor.add(p.pagina,text=titulo_pagina); f=crear_panel(p,SPACING_CARD); f.pack(fill='x')
            for i,(k,titulo,convertir,opciones) in enumerate(campos):
                columnas=3 if s=='telegram' else 2
                compacto=True
                grupo=ttk.Frame(f);grupo.grid(row=i//columnas,column=i%columnas,columnspan=1 if compacto else 2,
                    sticky='ew',padx=(0,12) if compacto else 0,pady=(0,SPACING_MD if compacto else SPACING_LG))
                ttk.Label(grupo,text=titulo,wraplength=750).pack(anchor='w',pady=(0,SPACING_SM))
                if s=='telegram' and convertir is bool:
                    w=ttk.Checkbutton(grupo);w._variable=tk.BooleanVar();w.configure(variable=w._variable)
                else:w=ttk.Combobox(grupo,values=['Sí','No'] if convertir is bool else opciones,state='readonly') if convertir is bool or opciones else ttk.Entry(grupo)
                w.pack(fill='x')
                for columna in range(columnas):f.columnconfigure(columna,weight=1,uniform='campos')
                self.controles[(s,k)]=(w,convertir)
            if s=='arduino':
                f.columnconfigure(0,weight=1,uniform='arduino');f.columnconfigure(1,weight=1,uniform='arduino')
                from integrations.arduino.arduino_ui import ArduinoUI
                puerto=self.controles[('arduino','puerto')][0];puerto.configure(state='normal')
                self.arduino_ui=ArduinoUI(p,root,puerto)
            elif s=='telegram':
                for columna in range(3):f.columnconfigure(columna,weight=1,uniform='telegram')
            from ui.service_state_ui import StateBinding
            from core.system_state import format_service_state
            services={'jarvis':('JARVIS','TTS','VOSK'),'facial':('CAMARA','SFACE','YOLO'),'arduino':('ARDUINO',)}.get(s)
            if services:
                status_label=ttk.Label(p,wraplength=900);status_label.pack(anchor='w')
                def show_status(snapshot,names=services,label=status_label):
                    label.configure(text=' | '.join(name+': '+format_service_state(snapshot[name])['text'] for name in names))
                if not hasattr(self,'state_bindings'):self.state_bindings=[]
                self.state_bindings.append(StateBinding(root,show_status,status_label))
            if s=='facial': ttk.Label(p,text='Threshold: lo establece la calibración validada, no un ajuste manual.\nLa galería permanece en modelos/facial_embeddings/galeria.npz.\nFuentes con credenciales: use INVENTARIO_VIDEO_SOURCE; no se guardan en el JSON.',wraplength=780).pack(anchor='w',pady=SPACING_MD)
            elif s=='jarvis':
                ttk.Label(p,text='Salida: dispositivo predeterminado del sistema operativo. Push-to-talk siempre disponible.\nAuto y Edge usan voz local si Edge falla; no se reintenta hasta reiniciar. Local funciona sin Internet.\nPersonalidad: profesional y breve; no cambia las reglas de datos reales.',wraplength=780).pack(anchor='w',pady=SPACING_MD)
                ttk.Button(p,text='Ver dispositivos de audio',command=self.dispositivos).pack(anchor='w')
            elif s=='anomalias': ttk.Label(p,text='Mayor límite = menos sensible. Método: estadística por producto y tipo.\nEl score es una desviación estándar o razón respecto al promedio, no una probabilidad.',wraplength=780).pack(anchor='w',pady=SPACING_MD)
            elif s=='inventario': ttk.Label(p,text='Las alertas conservan el comportamiento de stock y vencimiento existente.\nEl mínimo por defecto no modifica productos registrados.',wraplength=780).pack(anchor='w',pady=SPACING_MD)
            elif s=='telegram':
                from integrations.telegram.telegram_service import estado_telegram,probar_telegram,servicio_telegram,comprobar_conexion
                estado=estado_telegram()
                self.estado_telegram_label=ttk.Label(p,text='Estado: '+estado['estado'],wraplength=900)
                self.estado_telegram_label.pack(anchor='w')
                from ui.service_state_ui import StateBinding
                from core.system_state import format_service_state
                def mostrar_telegram(snapshot):
                    value=snapshot['TELEGRAM'];view=format_service_state(value)
                    self.estado_telegram_label.configure(text=view['text']+' · '+value['message'],foreground=view['color'])
                self.telegram_binding=StateBinding(root,mostrar_telegram,self.estado_telegram_label)
                ttk.Label(p,text='Token: '+('configurado' if estado['token_configurado'] else 'no configurado')+
                    ' · Chat: '+('configurado' if estado['chat_configurado'] else 'no configurado')+
                    '\nCredenciales en .env. Los valores completos no se muestran.',wraplength=900).pack(anchor='w')
                ttk.Button(p,text='Probar Telegram',command=lambda:self.trabajo.ejecutar(probar_telegram,
                    lambda r:messagebox.showinfo('Telegram',r['detalle'],parent=root))).pack(anchor='w',pady=6)
                ttk.Button(p,text='Comprobar conexión sin enviar mensaje',command=lambda:self.trabajo.ejecutar(lambda:__import__('core.health_monitor', fromlist=["*"]).check_telegram(force=True).to_dict(),
                    lambda r:messagebox.showinfo('Telegram',r['message'],parent=root))).pack(anchor='w',pady=6)
                ttk.Label(p,text='Envío automático de eventos nuevos. Hasta 3 intentos por entrega; INCIERTO requiere revisar el chat.\nFotos y vídeos se adjuntan desde el servicio central. Las alertas anteriores al arranque no se envían.',wraplength=900).pack(anchor='w')
                self.tabla_telegram=ttk.Treeview(p,columns=('referencia','estado','intentos','fecha'),show='headings',height=4)
                for k,t in [('referencia','Referencia'),('estado','Estado'),('intentos','Intentos'),('fecha','Fecha de envío')]:
                    self.tabla_telegram.heading(k,text=t);self.tabla_telegram.column(k,width=170)
                self.tabla_telegram.pack(fill='x',pady=6)
                self.detalle_telegram=ttk.Label(p,text='',wraplength=900);self.detalle_telegram.pack(anchor='w')
                def detalle(_=None):
                    ids=self.tabla_telegram.selection()
                    if ids:self.detalle_telegram.configure(text=self.entregas_telegram.get(ids[0],{}).get('detalle',''))
                self.tabla_telegram.bind('<<TreeviewSelect>>',detalle)
                ttk.Button(p,text='Actualizar entregas',command=self.cargar_entregas).pack(anchor='w',pady=4)
                ttk.Button(p,text='Reintentar errores',command=lambda:self.trabajo.ejecutar(servicio_telegram.reintentar_errores,
                    lambda n:(messagebox.showinfo('Telegram',f'{n} notificaciones listas para reintento.',parent=root),self.cargar_entregas()))).pack(anchor='w')
        pie=ttk.Frame(padre); pie.pack(fill='x',pady=SPACING_MD)
        ttk.Button(pie,text='Guardar configuración',command=self.guardar,style='Primary.TButton').pack(side='right')
        ttk.Button(pie,text='Restaurar valores predeterminados',command=self.restaurar,style='Warning.TButton').pack(side='left')
        self.cargar()
    def cargar(self):
        self.datos=cargar_configuracion()
        for (s,k),(w,convertir) in self.controles.items():
            v=self.datos[s][k]
            if hasattr(w,'_variable'):w._variable.set(bool(v));continue
            # Los booleanos requieren texto explícito; los demás conservan el valor.
            if convertir is bool: v='Sí' if self.datos[s][k] else 'No'
            elif k=='resolucion': v='x'.join(map(str,self.datos[s][k]))
            else: v=self.datos[s][k]
            if isinstance(w,ttk.Combobox): w.set(str(v))
            else: w.delete(0,'end'); w.insert(0,str(v))
    def guardar(self):
        try:
            c=cargar_configuracion()
            for (s,k),(w,convertir) in self.controles.items():
                if hasattr(w,'_variable'):c[s][k]=w._variable.get();continue
                v=w.get().strip()
                c[s][k]=(v=='Sí') if convertir is bool else [int(n) for n in v.split('x')] if k=='resolucion' else int(v) if k in ('fuente_video','camera_source','camera_source_employees') and v.isdigit() else convertir(v)
            c['vigilancia']['camera_source_intrusion']=c['vigilancia']['camera_source']
            if c['vigilancia']['camera_source']!=self.datos['vigilancia']['camera_source']:
                c['vigilancia']['zone_polygon']=[]
            guardar_configuracion(c); self.datos=c
            if self.al_guardar: self.al_guardar(c)
            messagebox.showinfo('Configuración','Configuración guardada. Los cambios de modelo o audio se aplican en una nueva sesión o mediante recargar modelo.',parent=self.root)
        except Exception as e: messagebox.showerror('Configuración',str(e),parent=self.root)
    def restaurar(self):
        if messagebox.askyesno('Configuración','¿Restaurar los valores predeterminados? Los datos del inventario se conservarán.',parent=self.root):
            restaurar(); self.cargar()
            if self.al_guardar: self.al_guardar(self.datos)
    def dispositivos(self):
        from jarvis.asistente_voz import listar_dispositivos_audio
        self.trabajo.ejecutar(listar_dispositivos_audio,lambda ds:messagebox.showinfo('Dispositivos de audio','\n'.join(f'{i}: {d["name"]} · entrada {d["max_input_channels"]} canales' for i,d in enumerate(ds)) or 'Sin dispositivos.',parent=self.root))

    def cargar_entregas(self):
        from integrations.telegram.telegram_service import listar_notificaciones
        from core.formato_numerico import format_campo
        def mostrar(filas):
            self.tabla_telegram.delete(*self.tabla_telegram.get_children());self.entregas_telegram={}
            for f in filas:
                clave=str(f['id_notificacion']);self.entregas_telegram[clave]=f
                self.tabla_telegram.insert('','end',iid=clave,values=(f['referencia'],f['estado'],f['intentos'],format_campo('fecha',f['fecha_envio']) or 'Sin envío'))
            self.detalle_telegram.configure(text='No hay notificaciones registradas.' if not filas else 'Seleccione una entrega para ver el resultado.')
        self.trabajo.ejecutar(listar_notificaciones,mostrar,lambda e:self.detalle_telegram.configure(text='No se pudo consultar el estado de las entregas.'))
