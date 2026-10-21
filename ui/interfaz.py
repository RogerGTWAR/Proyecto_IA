from core.formato_numerico import format_numero
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, ttk, font as tkfont
from tkinter.scrolledtext import ScrolledText

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None

from jarvis.agente_inventario import reiniciar_contexto, establecer_producto_visual
from jarvis.jarvis import procesar_consulta
from jarvis.asistente_voz import (EscuchaSinTexto, extraer_consulta_activada, cerrar_audio, detener_voz,
                           escuchar_pregunta, hablar, precalentar_voz,
                           registrar_tiempo_jarvis, obtener_estado_tts)
from inventory.alertas import eliminar_alerta, listar_alertas, marcar_alerta_atendida
from ai.anomalies.deteccion_anomalias import analizar_movimientos
from inventory.movimientos import (buscar_movimientos, listar_empleados_activos,
                         registrar_entrada, registrar_salida,
                         registrar_transferencia)
from inventory.productos import (buscar_productos, listar_categorias, listar_productos,
                       listar_ubicaciones, obtener_producto_por_id,
                       registrar_producto, ver_ubicaciones_producto,
                       actualizar_producto, eliminar_producto, crear_categoria,
                       actualizar_categoria, eliminar_categoria,
                       registrar_ubicacion, actualizar_ubicacion, eliminar_ubicacion)
from ai.prediction.prediccion_stock import predecir_agotamiento
from inventory.empleados import (actualizar_empleado, eliminar_empleado, listar_empleados,
                       registrar_empleado)
from ai.facial.captura_rostros import capturar_rostros_nuevo_empleado
from ai.facial.reconocimiento_cnn import (detener_reconocimiento, obtener_estado_cnn,
                                reconocer_con_camara)
from ai.facial.dataset_rostros import cargar_dataset, resumir_dataset
from ai.facial.entrenar_cnn_rostros import entrenar_modelo_cnn
from ai.facial.rostros_empleados import (asignar_etiqueta_empleado,
                               actualizar_relacion, eliminar_relacion, listar_etiquetas_disponibles,
                               listar_relaciones)
from ui.ventanas_camara import VentanaCamara
from ai.facial.pipeline_facial import cargar_configuracion
from ui.inventario_ui import InventarioUI, ConteoUI, abrir_movimiento as dialogo_movimiento
from ui.dashboard import Dashboard
from ui.ui_components import organizar_acciones, insertar_fila,agrupar_acciones
from ui.ui_theme import (COLORES, FONTS, SPACING, configurar_estilos, crear_indicador,
                      crear_kpi, crear_badge, crear_pagina, Navegacion, ChatConversacion, marco_visual, etiqueta_visual)


UNIDADES = ("Unidad", "Caja", "Paquete", "Metro", "Kilogramo", "Litro")
TIPOS_MOVIMIENTO = ("Todos", "Entrada", "Salida", "Transferencia",
                    "Ajuste entrada", "Ajuste salida")

def crear_tarjeta(padre, padding=16):
    tarjeta = ttk.Frame(padre, style="Card.TFrame", padding=padding)
    return tarjeta


def crear_boton_accion(padre, texto, comando, variante="Secondary", **opciones):
    boton=ttk.Button(padre,text=texto,command=(comando),
                     style=f"{variante}.TButton",cursor="hand2",**opciones)
    return boton


def centrar_ventana(ventana, ancho, alto, padre=None):
    ventana.update_idletasks()
    referencia = padre or ventana.master
    if referencia and referencia.winfo_exists():
        x = referencia.winfo_rootx() + max(0, (referencia.winfo_width() - ancho) // 2)
        y = referencia.winfo_rooty() + max(0, (referencia.winfo_height() - alto) // 2)
    else:
        x = (ventana.winfo_screenwidth() - ancho) // 2
        y = (ventana.winfo_screenheight() - alto) // 2
    ancho = min(ancho, ventana.winfo_screenwidth() - 60)
    alto = min(alto, ventana.winfo_screenheight() - 100)
    x = min(max(0, x), ventana.winfo_screenwidth() - ancho)
    y = min(max(0, y), ventana.winfo_screenheight() - alto - 60)
    ventana.configure(background=COLORES["fondo"])
    ventana.geometry(f"{ancho}x{alto}+{x}+{y}")


def encabezado_seccion(padre, titulo, subtitulo):
    from ui.ui_components import ModuleHeader
    return ModuleHeader(padre,titulo,subtitulo)


def encabezado_modal(ventana, titulo, subtitulo="Complete la información solicitada"):
    zona = marco_visual(ventana, background=COLORES["primario"], padx=SPACING_LG, pady=SPACING_MD)
    zona.pack(fill="x")
    etiqueta_visual(zona, text=titulo, background=COLORES["primario"], foreground="white",
             font=("Segoe UI", 13, "bold")).pack(anchor="w")
    etiqueta_visual(zona, text=subtitulo, background=COLORES["primario"], foreground=COLORES["texto_header"],
             font=("Segoe UI", 8)).pack(anchor="w", pady=(SPACING_XS, 0))


def aplicar_estilo_tabla(tabla):
    tabla.tag_configure("par", background=COLORES["fila_alterna"])
    tabla.tag_configure("impar", background=COLORES["tarjeta"])


def _error(error, padre):
    """Muestra el error real y deja el traceback en consola para depuración."""
    print("\n========================================")
    print("ERROR REAL")
    print("========================================")
    print("Tipo:", type(error).__name__)
    print("Detalle:", repr(error))
    print("========================================")
    traceback.print_exc()

    mensaje = str(error).strip() if isinstance(error,ValueError) else 'No se pudo completar la operación. Compruebe la conexión y vuelva a intentarlo.'
    if not mensaje:
        mensaje = "Ocurrió un error inesperado."

    messagebox.showerror(
        "Error",
        mensaje,
        parent=padre
    )


def _tabla(marco, columnas, titulos, anchos, horizontal=True):
    from ui.ui_components import StandardTreeview
    return StandardTreeview(marco,columnas,titulos,anchos,horizontal)


def iniciar_aplicacion():
    from core.event_subscribers import iniciar_eventos,cerrar_eventos
    iniciar_eventos()
    from integrations.telegram.telegram_service import servicio_telegram
    servicio_telegram.iniciar()
    from integrations.telegram.telegram_bot_service import servicio_bot_telegram
    servicio_bot_telegram.iniciar()
    reiniciar_contexto()
    from core.config_manager import cargar_configuracion as cargar_configuracion_sistema
    configuracion=cargar_configuracion_sistema()
    from core.system_state import state_manager,format_service_state,health_summary
    from core.health_monitor import health_monitor
    state_manager.initialize(configuracion)
    from jarvis.tools import instalar
    instalar()
    from jarvis import jarvis_router
    state_manager.update('JARVIS','ONLINE','Núcleo, router y herramientas cargados.')
    state_manager.update('EVENT_BUS','ONLINE','Bus central inicializado.')
    health_monitor.start()
    from core.automatizacion_inventario import automatizacion
    automatizacion.iniciar()
    ventana = tb.Window(themename="flatly") if tb is not None else tk.Tk()
    ventana.title(configuracion['general']['nombre'])
    ventana.geometry(configuracion['general']['ventana'])
    ventana.minsize(1100, 650)
    ventana.configure(background=COLORES["fondo"])
    configurar_estilos(ventana)

    principal = ttk.Frame(ventana, padding=(0, 0, 0, SPACING_XS), style="App.TFrame")
    principal.pack(fill="both", expand=True)
    cabecera = ttk.Frame(principal, padding=(24,10), style="Header.TFrame")
    cabecera.pack(fill="x", pady=(0, SPACING_XS))
    identidad = ttk.Frame(cabecera, style="Header.TFrame"); identidad.pack(side="left", fill="x", expand=True)
    nombre_sistema=tk.StringVar(value=configuracion['general']['nombre'])
    ttk.Label(identidad, textvariable=nombre_sistema, style="HeaderTitle.TLabel").pack(anchor="w")
    texto_sesion = tk.StringVar(value="Gestión inteligente, análisis y asistencia del almacén")
    ttk.Label(identidad, textvariable=texto_sesion,
              style="HeaderSub.TLabel").pack(anchor="w", pady=(SPACING_XS, 0))
    usuario = ttk.Frame(cabecera, style="Header.TFrame"); usuario.pack(side="right", padx=(SPACING_XL, 0))
    panel_badges=ttk.Frame(usuario,style='Header.TFrame'); panel_badges.pack(side='left')
    badges={}
    for i,n in enumerate(('Sistema','Base de datos','JARVIS','Cámara')):
        b=crear_indicador(panel_badges,n+': sin verificar')
        if i:b.grid(row=0,column=i-1,padx=SPACING_XS,pady=SPACING_XS)
        b.configure(background=COLORES['info_bg'],foreground=COLORES['info_text'])
        from ui.ui_components import Tooltip
        Tooltip(b,lambda widget=b:getattr(widget,'estado_detalle','Sin verificar'))
        badges[n]=b
    navegacion = Navegacion(principal)
    navegacion.pack(fill="both", expand=True)
    notebook = navegacion.notebook
    pestana_dashboard = crear_pagina(notebook)
    pestana_productos = crear_pagina(notebook)
    pestana_movimientos = crear_pagina(notebook)
    pestana_historial = crear_pagina(notebook)
    pestana_alertas = crear_pagina(notebook)
    pestana_empleados = crear_pagina(notebook)
    pestana_ia = crear_pagina(notebook)
    pestana_agente = crear_pagina(notebook)
    navegacion.add(pestana_dashboard.pagina, text="Dashboard")
    navegacion.add(pestana_productos.pagina, text="Productos")
    navegacion.add(pestana_movimientos.pagina, text="Movimientos")
    navegacion.add(pestana_historial.pagina, text="Historial")
    navegacion.add(pestana_alertas.pagina, text="Alertas")
    navegacion.add(pestana_empleados.pagina, text="Empleados")
    navegacion.add(pestana_ia.pagina, text="Análisis IA")
    navegacion.add(pestana_agente.pagina, text="JARVIS")
    barra_inferior = ttk.Frame(principal, style="Status.TFrame", padding=(SPACING_LG, SPACING_XS))
    barra_inferior.pack(fill="x", side="bottom", padx=SPACING_LG, pady=(SPACING_SM, 0))
    ttk.Label(barra_inferior, text="Sistema listo", style="Status.TLabel").pack(side="left")
    ttk.Label(barra_inferior, text="SQL Server local", style="Status.TLabel").pack(side="left", padx=SPACING_XL)
    estado_footer=ttk.Label(barra_inferior,text='JARVIS: Sin verificar',style='Status.TLabel')
    estado_footer.pack(side='right')

    from inventory.mapa_almacen import MapaAlmacenUI
    pestana_mapa=crear_pagina(notebook)
    navegacion.add(pestana_mapa.pagina,text="Mapa")
    mapa_almacen=MapaAlmacenUI(pestana_mapa,ventana,_tabla,
                               ver_producto=lambda producto_id:inventario_ui.ficha(producto_id))
    def mostrar_producto_en_mapa(producto_id):
        resultado=mapa_almacen.mostrar_producto_en_mapa(producto_id)
        notebook.select(pestana_mapa.pagina)
        return resultado
    ventana.mostrar_producto_en_mapa=mostrar_producto_en_mapa
    def abrir_jarvis():
        seleccion=inventario_ui.tabla.selection() if notebook.select()==str(pestana_productos.pagina) else ()
        if seleccion:
            producto=inventario_ui.datos.get(int(seleccion[0]))
            if producto:establecer_producto_visual(producto['id_producto'],producto['nombre'])
        notebook.select(pestana_agente.pagina)
    ttk.Button(usuario,text='Abrir JARVIS',command=abrir_jarvis,style='Secondary.TButton').pack(side='left',padx=SPACING_SM)

    inventario_ui = InventarioUI(pestana_productos, ventana, _tabla, lambda:actualizar_todo())
    pagina_previa={'id':notebook.select()}
    def contexto_al_abrir_jarvis(evento=None):
        actual=notebook.select()
        if actual==str(pestana_agente.pagina) and pagina_previa['id']==str(pestana_productos.pagina):
            seleccion=inventario_ui.tabla.selection()
            if seleccion:
                producto=inventario_ui.datos.get(int(seleccion[0]))
                if producto:establecer_producto_visual(producto['id_producto'],producto['nombre'])
        pagina_previa['id']=actual
    notebook.bind('<<NotebookTabChanged>>',contexto_al_abrir_jarvis,add='+')
    cargar_productos = inventario_ui.refrescar
    nuevo_producto = inventario_ui.nuevo_producto
    from ui.prediccion_ui import PrediccionUI
    pestana_prediccion=crear_pagina(notebook)
    navegacion.add(pestana_prediccion.pagina,text='Predicción')
    prediccion_ui=PrediccionUI(pestana_prediccion,ventana,_tabla)

    # Pestaña Historial
    encabezado_seccion(pestana_historial, "Historial de movimientos", "Consulta y filtra todas las operaciones del inventario")
    filtros = crear_tarjeta(pestana_historial, SPACING_MD); filtros.pack(fill="x", pady=(0, SPACING_MD))
    ttk.Label(filtros, text="FILTROS", foreground=COLORES["primario"], font=FONTS["boton"]).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, SPACING_MD))
    ttk.Label(filtros, text="Buscar código, producto o empleado", foreground=COLORES["secundario"]).grid(row=1, column=0, sticky="w", pady=(0, SPACING_SM))
    filtro_texto = ttk.Entry(filtros, width=22); filtro_texto.grid(row=2, column=0, sticky="ew", padx=(0, SPACING_MD))
    ttk.Label(filtros, text="Tipo", foreground=COLORES["secundario"]).grid(row=1, column=1, sticky="w", pady=(0, SPACING_SM))
    filtro_tipo = ttk.Combobox(filtros, values=TIPOS_MOVIMIENTO, state="readonly", width=16); filtro_tipo.set("Todos")
    filtro_tipo.grid(row=2, column=1, sticky="ew", padx=(0, SPACING_MD))
    ttk.Label(filtros, text="Fecha desde · AAAA-MM-DD", foreground=COLORES["secundario"]).grid(row=1, column=2, sticky="w", pady=(0, SPACING_SM))
    fecha_desde = ttk.Entry(filtros, width=12); fecha_desde.grid(row=2, column=2, sticky="ew", padx=(0, SPACING_MD))
    ttk.Label(filtros, text="Fecha hasta · AAAA-MM-DD", foreground=COLORES["secundario"]).grid(row=1, column=3, sticky="w", pady=(0, SPACING_SM))
    fecha_hasta = ttk.Entry(filtros, width=12); fecha_hasta.grid(row=2, column=3, sticky="ew")
    for columna in range(4): filtros.columnconfigure(columna, weight=1)
    historial_categorias={c['nombre']:c['id_categoria'] for c in listar_categorias()}
    historial_productos={p['codigo']+' · '+p['nombre']:p['id_producto'] for p in listar_productos()}
    historial_ubicaciones={u['codigo_ubicacion']:u['id_ubicacion'] for u in listar_ubicaciones()}
    filtro_producto=ttk.Combobox(filtros,values=['Todos']+list(historial_productos),state='readonly'); filtro_producto.set('Todos')
    filtro_categoria=ttk.Combobox(filtros,values=['Todas']+list(historial_categorias),state='readonly'); filtro_categoria.set('Todas')
    filtro_ubicacion=ttk.Combobox(filtros,values=['Todas']+list(historial_ubicaciones),state='readonly'); filtro_ubicacion.set('Todas')
    for columna,(titulo,control) in enumerate([('Producto',filtro_producto),('Categoría',filtro_categoria),('Ubicación',filtro_ubicacion)]):
        ttk.Label(filtros,text=titulo).grid(row=3,column=columna,sticky='w',pady=(SPACING_MD,SPACING_XS))
        control.grid(row=4,column=columna,sticky='ew',padx=(0,SPACING_MD))
    busqueda_historial_after = {"id": None}
    cols_h = ("fecha_movimiento", "tipo_movimiento", "empleado", "codigo_producto", "producto", "cantidad",
              "ubicacion_origen", "ubicacion_destino", "motivo", "referencia", "stock_anterior", "stock_nuevo", "observacion")
    tabla_h = _tabla(pestana_historial, cols_h,
        ("Fecha", "Tipo", "Empleado", "Código", "Producto", "Cantidad", "Origen", "Destino", "Motivo", "Referencia", "Stock anterior", "Stock nuevo", "Observación"),
        (145, 100, 210, 90, 160, 70, 90, 90, 170, 120, 90, 90, 220), True)
    tabla_h.configure(displaycolumns=('fecha_movimiento','tipo_movimiento','empleado','producto','cantidad',
        'ubicacion_origen','ubicacion_destino','stock_anterior','stock_nuevo'))
    def ver_detalle_historial(_=None):
        from ui.ui_components import ver_detalle_fila
        ver_detalle_fila(tabla_h,ventana,'Detalle del movimiento')
    tabla_h.bind('<Double-1>',ver_detalle_historial);tabla_h.bind('<Return>',ver_detalle_historial)

    def cargar_historial():
        historial_categorias.clear(); historial_categorias.update({c['nombre']:c['id_categoria'] for c in listar_categorias()})
        historial_productos.clear(); historial_productos.update({p['codigo']+' · '+p['nombre']:p['id_producto'] for p in listar_productos()})
        historial_ubicaciones.clear(); historial_ubicaciones.update({u['codigo_ubicacion']:u['id_ubicacion'] for u in listar_ubicaciones()})
        filtro_producto.configure(values=['Todos']+list(historial_productos)); filtro_categoria.configure(values=['Todas']+list(historial_categorias)); filtro_ubicacion.configure(values=['Todas']+list(historial_ubicaciones))
        try: datos = buscar_movimientos(filtro_texto.get(), filtro_tipo.get(), fecha_desde.get().strip() or None, fecha_hasta.get().strip() or None, id_producto=historial_productos.get(filtro_producto.get()), id_categoria=historial_categorias.get(filtro_categoria.get()), id_ubicacion=historial_ubicaciones.get(filtro_ubicacion.get()))
        except Exception as exc: _error(exc, ventana); return
        tabla_h.delete(*tabla_h.get_children())
        for m in datos:
            insertar_fila(tabla_h, "", "end", values=tuple("—" if m[c] is None else m[c] for c in cols_h))
    def programar_busqueda_historial(evento=None):
        if busqueda_historial_after["id"]:
            ventana.after_cancel(busqueda_historial_after["id"])
        fechas = (fecha_desde.get().strip(), fecha_hasta.get().strip())
        if any(fecha and len(fecha) < 10 for fecha in fechas):
            return
        busqueda_historial_after["id"] = ventana.after(300, cargar_historial)
    def limpiar_historial():
        for e in (filtro_texto, fecha_desde, fecha_hasta): e.delete(0, tk.END)
        filtro_tipo.set("Todos"); filtro_producto.set("Todos"); filtro_categoria.set("Todas"); filtro_ubicacion.set("Todas"); cargar_historial()
    # Dos filas de filtros; la reubicación conserva widgets, valores y callbacks.
    for hijo in filtros.winfo_children():
        if isinstance(hijo,ttk.Label):hijo.grid_remove()
    controles_historial=[('Buscar',filtro_texto),('Tipo',filtro_tipo),('Producto',filtro_producto),('Categoría',filtro_categoria),
        ('Desde · AAAA-MM-DD',fecha_desde),('Hasta · AAAA-MM-DD',fecha_hasta),('Ubicación',filtro_ubicacion)]
    for i,(titulo,control) in enumerate(controles_historial):
        fila=(i//4)*2;col=i%4
        ttk.Label(filtros,text=titulo,style='CardTitle.TLabel').grid(row=fila,column=col,sticky='w',pady=(0,SPACING_XS))
        control.grid_configure(row=fila+1,column=col,sticky='ew',padx=(0,SPACING_SM),pady=(0,SPACING_SM if fila==0 else 0))
    acciones_historial=ttk.Frame(filtros);acciones_historial.grid(row=3,column=3,sticky='e')
    crear_boton_accion(acciones_historial,'Limpiar',limpiar_historial).pack(side='left',padx=SPACING_XS)
    crear_boton_accion(filtros,'Actualizar',cargar_historial,'Primary').grid(row=1,column=4,rowspan=3,padx=(SPACING_SM,0),sticky='e')
    crear_boton_accion(acciones_historial,'Detalle',ver_detalle_historial).pack(side='left')
    filtro_texto.bind("<KeyRelease>", programar_busqueda_historial)
    filtro_tipo.bind("<<ComboboxSelected>>", programar_busqueda_historial)
    for control in (filtro_producto,filtro_categoria,filtro_ubicacion): control.bind("<<ComboboxSelected>>",programar_busqueda_historial)
    fecha_desde.bind("<KeyRelease>", programar_busqueda_historial)
    fecha_hasta.bind("<KeyRelease>", programar_busqueda_historial)
    fecha_desde.bind("<FocusOut>", programar_busqueda_historial)
    fecha_hasta.bind("<FocusOut>", programar_busqueda_historial)

    # Pestaña Alertas
    from integrations.telegram.telegram_service import crear_estado_telegram
    crear_estado_telegram(pestana_alertas,('inventario','alertas','anomalias','prediccion','facial'))
    encabezado_seccion(pestana_alertas, "Alertas del sistema", "Eventos detectados por inventario, IA y reconocimiento facial")
    resumen_alertas = ttk.Frame(pestana_alertas, style="App.TFrame")
    resumen_alertas.pack(fill="x", pady=(0, SPACING_MD))
    valores_alertas = {k: tk.StringVar(value="0") for k in ("activas", "altas", "stock", "desconocidos")}
    for columna, (titulo, clave) in enumerate((("Pendientes", "activas"), ("Críticas", "altas"),
                                               ("Stock bajo", "stock"), ("No reconocidos", "desconocidos"))):
        tarjeta = crear_kpi(resumen_alertas, titulo, valores_alertas[clave], "",
                            "danger" if clave in {"altas", "desconocidos"} else "warning")
        tarjeta.grid(row=0, column=columna, sticky="nsew", padx=(0 if columna == 0 else SPACING_SM, 0))
        resumen_alertas.columnconfigure(columna, weight=1)
    barra_a = crear_tarjeta(pestana_alertas, SPACING_MD); barra_a.pack(fill="x", pady=(0, SPACING_MD))
    from ui.ui_components import FilterBar
    filtros_alerta=FilterBar(pestana_alertas);filtros_alerta.pack(fill='x',before=barra_a,pady=(0,8))
    buscar_alerta=filtros_alerta.add('Buscar en alertas')
    tipo_alerta=filtros_alerta.add('Tipo',['Todos']);tipo_alerta.set('Todos')
    nivel_alerta=filtros_alerta.add('Nivel',['Todos','Baja','Media','Alta','Critica','Crítica']);nivel_alerta.set('Todos')
    solo_pendientes = tk.BooleanVar(value=True)
    contador_alertas = tk.StringVar(value="0 pendientes")
    ttk.Checkbutton(barra_a, text="Mostrar solamente pendientes", variable=solo_pendientes).pack(side="left")
    ttk.Label(barra_a, textvariable=contador_alertas, background=COLORES["tarjeta"], foreground=COLORES["peligro"],
              font=("Segoe UI", 10, "bold")).pack(side="left", padx=SPACING_LG)
    from ui.ui_components import DetailPanel
    cuerpo_alertas=ttk.Frame(pestana_alertas,style='App.TFrame');cuerpo_alertas.pack(fill='both',expand=True)
    panel_alerta=DetailPanel(cuerpo_alertas,'Alerta seleccionada');panel_alerta.pack(side='right',fill='y',padx=(12,0))
    cols_a = ("fecha_generacion", "tipo", "nivel", "producto", "mensaje", "estado")
    tabla_a = _tabla(cuerpo_alertas, cols_a, ("Fecha", "Tipo", "Nivel", "Producto", "Descripción", "Estado"),
                     (155, 145, 80, 175, 270, 90))
    tabla_a.configure(displaycolumns=('fecha_generacion','tipo','nivel','mensaje','estado'))
    detalle_alerta=tk.StringVar(value='Seleccione una alerta para ver el detalle completo.')
    panel_alerta.label.configure(textvariable=detalle_alerta)
    alertas_por_id={}
    def seleccionar_alerta(_=None):
        seleccion=tabla_a.selection()
        a=alertas_por_id.get(seleccion[0]) if seleccion else None
        if a:
            from core.formato_numerico import format_campo
            detalle_alerta.set(f'{format_campo("fecha",a["fecha_generacion"])} · {a["tipo"]} · {a["nivel"]} · {a["estado"]}\n'
                f'{a.get("producto") or "Sin producto asociado"}\n{a["mensaje"]}')
    tabla_a.bind('<<TreeviewSelect>>',seleccionar_alerta)
    tabla_a.tag_configure("Critica", background=COLORES["danger_bg"], foreground=COLORES["danger_text"])
    tabla_a.tag_configure("Alta", background=COLORES["danger_bg"], foreground=COLORES["danger_text"])
    tabla_a.tag_configure("Media", background=COLORES["warning_bg"], foreground=COLORES["warning_text"])
    tabla_a.tag_configure("Baja", background=COLORES["info_bg"], foreground=COLORES["info_text"])
    from ui.tareas_ui import TrabajosUI
    trabajo_alertas=TrabajosUI(ventana);alertas_pendientes={'valor':False}
    def cargar_alertas():
        if trabajo_alertas.ocupado:
            alertas_pendientes['valor']=True;return
        alertas_pendientes['valor']=False;pendientes=solo_pendientes.get()
        def mostrar(datos):
            mostrar_alertas(datos)
            if alertas_pendientes['valor']:cargar_alertas()
        trabajo_alertas.ejecutar(lambda:listar_alertas(pendientes,refrescar=False),mostrar,
            lambda error:_error(error,ventana))
    def mostrar_alertas(datos):
        tipo_alerta.configure(values=['Todos']+sorted({str(a['tipo']) for a in datos}))
        texto=buscar_alerta.get().strip().casefold()
        datos=[a for a in datos if (tipo_alerta.get()=='Todos' or str(a['tipo'])==tipo_alerta.get())
               and (nivel_alerta.get()=='Todos' or str(a['nivel'])==nivel_alerta.get())
               and (not texto or texto in ' '.join(str(a.get(c) or '') for c in cols_a).casefold())]
        tabla_a.delete(*tabla_a.get_children())
        alertas_por_id.clear();alertas_por_id.update({str(a['id_alerta']):a for a in datos})
        detalle_alerta.set('Seleccione una alerta para ver el detalle completo.' if datos else 'No hay alertas para el filtro seleccionado.')
        for a in datos:
            insertar_fila(tabla_a, "", "end", iid=str(a["id_alerta"]), tags=(a["nivel"],),
                           values=tuple(a[c] for c in cols_a))
        valores_alertas["activas"].set(str(sum(str(a["estado"]).lower() == "pendiente" for a in datos)))
        valores_alertas["altas"].set(str(sum(str(a["nivel"]).lower() in {"critica", "crítica"} for a in datos)))
        valores_alertas["stock"].set(str(sum("stock" in str(a["tipo"]).lower() for a in datos)))
        valores_alertas["desconocidos"].set(str(sum("reconoc" in str(a["tipo"]).lower() for a in datos)))
        contador_alertas.set(f"{len(datos)} {'pendiente' if len(datos) == 1 else 'pendientes'}" if solo_pendientes.get() else f"{len(datos)} alertas")
    def atender_alerta():
        seleccion = tabla_a.selection()
        if not seleccion:
            messagebox.showwarning("Alerta", "Seleccione una alerta.", parent=ventana); return
        try: marcar_alerta_atendida(int(seleccion[0]))
        except Exception as exc: _error(exc, ventana); return
        messagebox.showinfo("Alerta", "Alerta marcada como atendida.", parent=ventana); cargar_alertas()
    def eliminar_alerta_ui():
        seleccion=tabla_a.selection()
        if not seleccion: messagebox.showwarning("Alerta","Seleccione una alerta.",parent=ventana); return
        if messagebox.askyesno("Eliminar alerta","¿Desea eliminar lógicamente esta alerta?",parent=ventana):
            try: eliminar_alerta(int(seleccion[0])); cargar_alertas()
            except Exception as exc: _error(exc,ventana)
    acciones_alertas=crear_tarjeta(barra_a,0);acciones_alertas.pack(side='right')
    crear_boton_accion(acciones_alertas, "Marcar como atendida", atender_alerta, "Success").pack(side="left", padx=SPACING_SM)
    crear_boton_accion(acciones_alertas, "Actualizar", cargar_alertas).pack(side="left")
    crear_boton_accion(acciones_alertas, "Eliminar", eliminar_alerta_ui, "Danger").pack(side="right", padx=SPACING_SM)
    solo_pendientes.trace_add("write", lambda *_: cargar_alertas())
    buscar_alerta.bind('<Return>',lambda _:cargar_alertas())
    for control in (tipo_alerta,nivel_alerta):control.bind('<<ComboboxSelected>>',lambda _:cargar_alertas())
    from ui.service_state_ui import EventBinding
    alertas_binding=EventBinding(ventana,lambda _:cargar_alertas(),pestana_alertas,
                               ('ALERTA_CREADA','ALERTA_ACTUALIZADA','ALERTA_RESUELTA'))

    # Pestaña Movimientos y formulario común
    encabezado_seccion(pestana_movimientos, "Movimientos de inventario",
                       "Registra entradas, salidas y transferencias entre ubicaciones")
    botones_m = ttk.Frame(pestana_movimientos, style="App.TFrame"); botones_m.pack(fill="x", pady=(SPACING_SM, 0))

    def abrir_movimiento(tipo):
        dialogo_movimiento(ventana, tipo, actualizar_todo)

    tipo_nuevo=ttk.Combobox(botones_m,values=('Entrada','Salida','Transferencia','Ajuste'),state='readonly',width=18)
    tipo_nuevo.set('Entrada');tipo_nuevo.pack(side='left',padx=(0,8))
    crear_boton_accion(botones_m,'+ Registrar movimiento',lambda:abrir_movimiento(tipo_nuevo.get()),'Primary').pack(side='left')
    crear_boton_accion(botones_m,'Ver historial',lambda:notebook.select(pestana_historial.pagina)).pack(side='left',padx=8)
    cols_recientes=('fecha_movimiento','tipo_movimiento','producto','cantidad','ubicacion_origen','ubicacion_destino','empleado')
    tabla_recientes=_tabla(pestana_movimientos,cols_recientes,('Fecha','Tipo','Producto','Cantidad','Origen','Destino','Empleado'),(160,110,220,90,130,130,160))
    def reflejar_movimientos(_=None):
        if notebook.select()!=str(pestana_movimientos.pagina):return
        try:datos=buscar_movimientos()
        except Exception as exc:_error(exc,ventana);return
        tabla_recientes.delete(*tabla_recientes.get_children())
        for m in datos[:100]:insertar_fila(tabla_recientes,values=tuple('—' if m.get(c) is None else m[c] for c in cols_recientes))
    notebook.bind('<<NotebookTabChanged>>',reflejar_movimientos,add='+')
    pestana_conteo=crear_pagina(notebook)
    navegacion.add(pestana_conteo.pagina,text="Conteo de inventario")
    conteo_ui=ConteoUI(pestana_conteo,ventana,_tabla,lambda:actualizar_todo())

    # Pestaña Empleados: la persona frente a la cámara se reconoce directamente.
    encabezado_seccion(pestana_empleados, "Empleados", "Personal del almacén y herramientas de reconocimiento facial")
    crear_estado_telegram(pestana_empleados,('facial',))
    tabs_empleados=ttk.Notebook(pestana_empleados);tabs_empleados.pack(fill='both',expand=True)
    lista_empleados=ttk.Frame(tabs_empleados,style='App.TFrame',padding=8)
    herramientas_faciales=ttk.Frame(tabs_empleados,style='App.TFrame',padding=8)
    tabs_empleados.add(lista_empleados,text='Personal');tabs_empleados.add(herramientas_faciales,text='Reconocimiento facial')
    panel_cnn = crear_tarjeta(herramientas_faciales, SPACING_CARD)
    panel_cnn.pack(fill="x", pady=(0, SPACING_MD))
    ttk.Label(panel_cnn, text="RECONOCIMIENTO FACIAL", background=COLORES["tarjeta"], foreground=COLORES["texto"],
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
    estado_cnn = tk.StringVar(value="Comprobando...")
    estado_detector = tk.StringVar(value="Comprobando...")
    estado_dataset = tk.StringVar(value="Comprobando...")
    estado_modelo = tk.StringVar(value="modelo_rostros.keras")
    empleados_activos_ui = tk.StringVar(value="0")
    rostros_registrados_ui = tk.StringVar(value="0")
    rostros_pendientes_ui = tk.StringVar(value="0")
    resultado_cnn = tk.StringVar(value="Persona: —    Confianza: —")
    resumen_personal=ttk.Frame(lista_empleados,style='App.TFrame');resumen_personal.pack(fill='x',pady=(0,8))
    for i,(titulo,variable) in enumerate((('Empleados activos',empleados_activos_ui),('Rostros registrados',rostros_registrados_ui),('Pendientes de registro',rostros_pendientes_ui))):
        crear_kpi(resumen_personal,titulo,variable).grid(row=0,column=i,sticky='ew',padx=(0,8));resumen_personal.columnconfigure(i,weight=1)
    acciones_empleado=ttk.Frame(lista_empleados);acciones_empleado.pack(fill='x',pady=(0,8))
    tarjetas_cnn = ttk.Frame(panel_cnn, style="Card.TFrame")
    tarjetas_cnn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING_MD, SPACING_SM))
    for columna, (titulo, variable) in enumerate((("Empleados activos", empleados_activos_ui),
                                                  ("Rostros registrados", rostros_registrados_ui),
                                                  ("Pendientes", rostros_pendientes_ui),
                                                  ("Diagnóstico del modelo", estado_cnn))):
        tarjeta = crear_tarjeta(tarjetas_cnn, SPACING_MD); tarjeta.grid(row=0, column=columna, sticky="ew", padx=(0 if columna == 0 else SPACING_SM, 0))
        ttk.Label(tarjeta, text=titulo, style="CardTitle.TLabel").pack(anchor="w")
        if titulo == "Diagnóstico del modelo":
            crear_badge(tarjeta, variable).pack(anchor="w", pady=(SPACING_SM, 0))
        else:
            ttk.Label(tarjeta, textvariable=variable, style="CardValue.TLabel").pack(anchor="w", pady=(SPACING_XS, 0))
        tarjetas_cnn.columnconfigure(columna, weight=1)
    etiqueta_resultado_facial=ttk.Label(panel_cnn, textvariable=resultado_cnn, background=COLORES["tarjeta"], foreground=COLORES["texto"],
              font=("Segoe UI", 10, "bold"),wraplength=900)
    etiqueta_resultado_facial.grid(row=2, column=0,columnspan=2,sticky="ew", pady=(SPACING_SM, SPACING_XS))
    panel_cnn.bind('<Configure>',lambda e:etiqueta_resultado_facial.configure(wraplength=max(250,e.width-40)))
    controles_cnn = ttk.Frame(panel_cnn, style="Card.TFrame")
    controles_cnn.grid(row=4, column=0, columnspan=2, pady=(SPACING_MD, 0), sticky="w")
    progreso_cnn = ttk.Progressbar(panel_cnn, mode="indeterminate")
    progreso_cnn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(SPACING_MD, 0))
    panel_cnn.columnconfigure(0, weight=1)

    camara_en_uso = {"valor": False}
    entrenamiento_en_curso = {"valor": False}
    aplicacion_cerrando = {"valor": False}

    eventos_faciales = queue.Queue()

    def publicar_facial(funcion, *argumentos):
        eventos_faciales.put((funcion, argumentos))

    def consumir_eventos_faciales():
        if aplicacion_cerrando["valor"]:
            return
        while True:
            try:
                funcion, argumentos = eventos_faciales.get_nowait()
            except queue.Empty:
                break
            funcion(*argumentos)
        ventana.after(50, consumir_eventos_faciales)

    selector_motor = ttk.Combobox(controles_cnn, state="readonly", width=12,
                                  values=("embeddings", "cnn"))
    selector_motor.set(cargar_configuracion()["motor"])
    selector_motor.pack(side="left", padx=SPACING_XS)
    ttk.Label(controles_cnn,text='Modo CNN:').pack(side='left',padx=SPACING_XS)
    selector_modo_cnn=ttk.Combobox(controles_cnn,state='readonly',width=23,
        values=('Dataset actual','Validación estricta'))
    selector_modo_cnn.set('Dataset actual');selector_modo_cnn.pack(side='left',padx=SPACING_XS)
    acciones_motor=ttk.Frame(panel_cnn);acciones_motor.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(SPACING_MD,0))

    def actualizar_estado_cnn(evento=None,mostrar_detalle=True):
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        try:
            estado = obtener_estado_cnn(selector_motor.get(),modo_cnn=selector_modo_cnn.get())
            es_cnn=selector_motor.get()=='cnn'
            actual=es_cnn and selector_modo_cnn.get()=='Dataset actual'
            selector_modo_cnn.configure(state='readonly' if es_cnn else 'disabled')
            boton_calibrar_facial.configure(state='disabled' if actual else 'normal')
            boton_captura_sesion_cnn.configure(state='disabled' if actual else 'normal')
            boton_validar_facial.configure(text='Validar dataset' if es_cnn else 'Diagnóstico facial')
            boton_diagnostico_cnn.configure(state='normal' if es_cnn else 'disabled')
            boton_regenerar.configure(state='disabled' if es_cnn else 'normal')
            estado_detector.set("Activo" if estado["detector_listo"] else "Faltan modelos")
            boton_entrenar.configure(text="Entrenar CNN")
            if estado["motor"] in ("embeddings","comparacion"):
                boton_entrenar.configure(state='disabled')
                estado_modelo.set("Comparacion tecnica: SFace + CNN" if estado["motor"]=="comparacion" else "YuNet + SFace")
                estado_dataset.set(f"{estado['muestras']} muestras · {len(estado['subjects'])} personas")
                estado_cnn.set("Calibrado" if estado["modelo_valido"] else "Sin calibrar" if estado["modelo_existe"] else "Instalar modelos")
                # Se permite observar y evaluar aun sin autorizar identidades.
                boton_camara.configure(state="normal" if estado["modelo_existe"] else "disabled")
            else:
                if actual:
                    from ai.facial.cnn_dataset_actual import resumen
                    estado_modelo.set('CNN · Dataset actual')
                    estado_dataset.set(str(estado.get('metricas',{}).get('imagenes',0))+' imágenes utilizadas')
                    estado_cnn.set('CNN provisional lista' if estado.get('entrenada') else 'CNN por entrenar')
                    if mostrar_detalle:resultado_cnn.set(resumen())
                    boton_entrenar.configure(state='normal')
                    boton_camara.configure(state='normal' if estado.get('entrenada') else 'disabled')
                    return
                from ai.facial.diagnostico_cnn import resumen
                estado_modelo.set("modelo_rostros.keras")
                estado_cnn.set("CNN lista" if estado["modelo_valido"] else "CNN sin calibración segura" if estado.get('entrenada') else "CNN pendiente de entrenamiento")
                if mostrar_detalle:
                    resultado_cnn.set(resumen(estado['calibrada']))
                from ai.facial.diagnostico_cnn import leer
                dataset=leer('dataset.json')
                estado_dataset.set(str(sum(dataset.get('validas_por_subject',{}).values()))+' imágenes válidas')
                boton_entrenar.configure(state='normal' if dataset.get('resumen_sesiones',{}).get('listo') else 'disabled')
                boton_camara.configure(state="normal" if estado.get('entrenada') else "disabled")
        except Exception as exc:
            estado_cnn.set(f"Error: {exc}")
            boton_camara.configure(state="disabled")

    def regenerar_base_facial_interfaz():
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        entrenamiento_en_curso["valor"] = True
        boton_regenerar.configure(state="disabled")
        progreso_cnn.start(12)
        estado_cnn.set("Regenerando embeddings desde imágenes existentes...")
        def tarea_regenerar():
            try:
                from ai.facial.diagnostico_facial_basico import regenerar, diagnosticar
                informe = regenerar()
                pruebas = diagnosticar()
                publicar_facial(resultado_cnn.set, f"Base: {len(informe['migrados'])} empleados, {informe['embeddings_totales']} embeddings. Diagnóstico guardado; calibración pendiente.")
            except Exception as exc:
                publicar_facial(resultado_cnn.set, f"Regeneración: {exc}")
            finally:
                entrenamiento_en_curso["valor"] = False
                publicar_facial(progreso_cnn.stop)
                publicar_facial(boton_regenerar.configure, {"state": "normal"})
                publicar_facial(actualizar_estado_cnn)
                publicar_facial(cargar_empleados)
        threading.Thread(target=tarea_regenerar, daemon=True).start()

    boton_regenerar = crear_boton_accion(acciones_motor, "Regenerar base", regenerar_base_facial_interfaz)
    boton_regenerar.pack(side="left", padx=SPACING_XS)

    def diagnostico_calibracion_facial(calibrar=False):
        if camara_en_uso['valor'] or entrenamiento_en_curso['valor']:return
        entrenamiento_en_curso['valor']=True
        motor_diagnostico=selector_motor.get()
        modo_diagnostico=selector_modo_cnn.get()
        estado_cnn.set('Midiendo muestras registradas...' if calibrar else 'Revisando motores y vínculos SQL...')
        def ejecutar():
            try:
                if motor_diagnostico=='cnn' and modo_diagnostico=='Dataset actual':
                    from ai.facial.cnn_dataset_actual import cargar_actual,resumen
                    d=cargar_actual()
                    publicar_facial(resultado_cnn.set,resumen()+'\nDataset revisado: '+str(len(d['X']))+' imágenes válidas.')
                    return
                from ai.facial.diagnostico_facial_basico import calibrar_registrados,calibrar_cnn
                from ai.facial.pipeline_facial import GaleriaEmbeddings,cargar_politica,cargar_configuracion
                from core.formato_numerico import format_numero
                if calibrar:
                    resultados=[]
                    motores=(('CNN',calibrar_cnn),) if motor_diagnostico=='cnn' else (('SFace',calibrar_registrados),)
                    for nombre,funcion in motores:
                        try:
                            p=funcion();resultados.append(nombre+': umbral '+format_numero(p['threshold'])+' · margen '+format_numero(p.get('margin',p.get('margen'))))
                        except Exception as error:resultados.append(nombre+': '+str(error))
                    texto='\n'.join(resultados)+'\nPendiente validar desconocidos y sesiones nuevas.'
                else:
                    if motor_diagnostico=='cnn':
                        from ai.facial.dataset_rostros import cargar_dataset
                        d=cargar_dataset()['reporte_dataset']
                        from ai.facial.diagnostico_cnn import resumen
                        publicar_facial(resultado_cnn.set,resumen())
                        publicar_facial(cargar_empleados)
                        return
                    from ai.facial.base_facial import diagnostico
                    d=diagnostico(imagenes=True);g=GaleriaEmbeddings();p=cargar_politica(g,cargar_configuracion())
                    texto=f"YuNet / SFace · Empleados: {d['empleados']} · Embeddings válidos: {d['embeddings_validos_base']} · Galería: {d['embeddings']} · Dimensión: {d['dimension']}\n"
                    texto+='Misma persona: '+str(d['intra']['cantidad'])+' comparaciones / media '+format_numero(d['intra']['promedio'])+'\n'
                    texto+='Distintas personas: '+str(d['inter']['cantidad'])+' / media '+format_numero(d['inter']['promedio'])+'\n'
                    texto+=('CALIBRADO · Umbral: '+format_numero(p['threshold']) if p else 'BASE NO CALIBRADA: '+('galería modificada' if d['galeria_modificada'] else 'revise configuración o evaluación'))
                    texto+='\nMuestras por empleado: '+', '.join(s+': '+str(v['imagenes']) for s,v in d['por_empleado'].items())
                    if d['etiquetas_sin_vinculo_activo']:texto+='\nSin vínculo activo: '+', '.join(d['etiquetas_sin_vinculo_activo'])
                    texto+='\nDetalle: evaluacion_facial/diagnostico_completo.json'
                if motor_diagnostico=='cnn':
                    from ai.facial.diagnostico_cnn import resumen
                    texto=resumen()
                publicar_facial(resultado_cnn.set,texto)
            except Exception as error:publicar_facial(resultado_cnn.set,str(error))
            finally:
                entrenamiento_en_curso['valor']=False
                publicar_facial(actualizar_estado_cnn,None,False)
        threading.Thread(target=ejecutar,daemon=True).start()
    boton_validar_facial=crear_boton_accion(acciones_motor,'Validar dataset',diagnostico_calibracion_facial)
    boton_validar_facial.pack(side='left',padx=SPACING_XS)
    def ver_diagnostico_cnn():
        from ai.facial.diagnostico_cnn import detalle
        actual=selector_modo_cnn.get()=='Dataset actual'
        if actual:
            from ai.facial.cnn_dataset_actual import diagnostico
            contenido=diagnostico()
        else:contenido=detalle()
        dialogo=tk.Toplevel(ventana);dialogo.title('Diagnóstico CNN');dialogo.geometry('1050x650')
        texto=ScrolledText(dialogo,wrap='word',padx=16,pady=16)
        texto.pack(fill='both',expand=True);texto.insert('1.0',contenido);texto.configure(state='disabled')
        if actual:
            try:
                from ai.facial.cnn_dataset_actual import archivos_vigentes
                from PIL import Image,ImageTk
                with Image.open(archivos_vigentes()/'matriz_confusion.png') as imagen:
                    imagen.thumbnail((850,400));foto=ImageTk.PhotoImage(imagen)
                etiqueta=ttk.Label(dialogo,image=foto);etiqueta.image=foto;etiqueta.pack()
            except (OSError,ValueError,KeyError):pass
    boton_diagnostico_cnn=crear_boton_accion(acciones_motor,'Ver diagnóstico',ver_diagnostico_cnn)
    boton_diagnostico_cnn.pack(side='left',padx=SPACING_XS)
    boton_calibrar_facial=crear_boton_accion(acciones_motor,'Calibrar motores',lambda:diagnostico_calibracion_facial(True))
    boton_calibrar_facial.pack(side='left',padx=SPACING_XS)

    selector_motor.bind("<<ComboboxSelected>>", lambda evento: (actualizar_estado_cnn(), cargar_empleados()))
    selector_modo_cnn.bind('<<ComboboxSelected>>',lambda evento:(actualizar_estado_cnn(),cargar_empleados()))
    ventana.after(50, consumir_eventos_faciales)

    def entrenar_desde_interfaz():
        if entrenamiento_en_curso["valor"] or camara_en_uso["valor"]:
            return
        modo_entrenamiento=selector_modo_cnn.get()
        entrenamiento_en_curso["valor"] = True
        boton_entrenar.configure(state="disabled")
        boton_camara.configure(state="disabled")
        progreso_cnn.start(12)

        def informar(mensaje):
            publicar_facial(estado_cnn.set, f"CNN: {mensaje}")

        def tarea():
            try:
                if modo_entrenamiento=='Dataset actual':
                    from ai.facial.cnn_dataset_actual import entrenar,resumen
                    resultado=entrenar(informar)
                    publicar_facial(resultado_cnn.set,resumen())
                    texto='CNN entrenada · Dataset actual · Validación provisional'
                else:resultado = entrenar_modelo_cnn(informar)
                if modo_entrenamiento=='Dataset actual':pass
                elif resultado["modelo_valido"]:
                    texto = (f"CNN entrenada; falta calibración segura - evaluación "
                             f"{resultado['accuracy_prueba']:.1%}")
                else:
                    texto = "CNN: El modelo no aprendió correctamente; no se guardó."
                publicar_facial(estado_cnn.set, texto)
            except Exception as exc:
                publicar_facial(estado_cnn.set, f"Reconocimiento: Error - {exc}")
            finally:
                entrenamiento_en_curso["valor"] = False
                publicar_facial(progreso_cnn.stop)
                publicar_facial(boton_entrenar.configure, {"state": "normal"})
                publicar_facial(actualizar_estado_cnn)
        threading.Thread(target=tarea, daemon=True).start()

    def reconocer_rostro_interfaz():
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        motor_seleccionado = selector_motor.get()
        modo_reconocimiento=selector_modo_cnn.get()
        provisional=motor_seleccionado=='cnn' and modo_reconocimiento=='Dataset actual'
        estado = obtener_estado_cnn(motor_seleccionado,modo_cnn=modo_reconocimiento)
        if not estado["modelo_existe"] or (motor_seleccionado == "cnn" and not estado.get('entrenada')):
            estado_cnn.set("Faltan modelos o la CNN necesita entrenamiento.")
            return
        camara_en_uso["valor"] = True
        boton_camara.configure(state="disabled")
        boton_entrenar.configure(state="disabled")
        estado_cnn.set(f"{motor_seleccionado}: Cámara activa.")
        modo_cierre = {"valor": None}

        def solicitar_cierre(modo):
            modo_cierre["valor"] = modo
            detener_reconocimiento()

        dialogo = VentanaCamara(ventana, "cnn_actual" if provisional else "escaner", "-", solicitar_cierre,
                               al_info=None if provisional else lambda info: dashboard.registrar_info_facial(info))

        def tarea():
            try:
                resultado = reconocer_con_camara(
                    callback_alerta=None if provisional else lambda _alerta: (
                        publicar_facial(cargar_alertas)
                        if not aplicacion_cerrando["valor"] else None),
                    presentador=dialogo, motor=motor_seleccionado,modo_cnn=modo_reconocimiento)
                if modo_cierre["valor"] != "cancelar":
                    if provisional and resultado['estado']=='RECONOCIDO':
                        texto=f"{resultado['nombre']} · Confianza: {resultado['confianza']:.2f} · RECONOCIDO"
                    elif resultado["estado"] == "RECONOCIDO":
                        texto = (f"{resultado['nombre']} | {resultado['codigo_empleado']} | "
                                 f"{resultado['cargo'] or 'Sin cargo'} | Puntuación: {format_numero(resultado['confianza'])}")
                    elif resultado["estado"] == "EMPLEADO_INACTIVO":
                        texto = (f"{resultado['nombre']} | Empleado inactivo | "
                                 f"Confianza: {resultado['confianza']:.1%}")
                    elif resultado["estado"] == "SIN_ROSTRO":
                        texto = "SIN ROSTRO: no se detectó ninguna persona."
                    else:
                        texto = resultado["estado"]
                    if not aplicacion_cerrando["valor"]:
                        publicar_facial(resultado_cnn.set, texto)
                        if resultado.get("estado")=="RECONOCIDO" and not provisional:
                            from jarvis.jarvis_personality import saludar_empleado
                            publicar_facial(escribir_chat,"Jarvis",saludar_empleado(resultado['nombre']))
            except Exception as exc:
                if not aplicacion_cerrando["valor"]:
                    publicar_facial(estado_cnn.set, f"CNN: Error - {exc}")
            finally:
                camara_en_uso["valor"] = False
                if not aplicacion_cerrando["valor"]:
                    publicar_facial(dialogo.cerrar)
                    publicar_facial(boton_entrenar.configure, {"state": "normal"})
                    publicar_facial(actualizar_estado_cnn)
        threading.Thread(target=tarea, daemon=True).start()

    boton_entrenar = crear_boton_accion(acciones_motor, "Entrenar CNN", entrenar_desde_interfaz, "Primary")
    boton_entrenar.pack(side="left", padx=SPACING_XS)
    boton_camara = crear_boton_accion(acciones_motor, "Reconocer con cámara",
                                      reconocer_rostro_interfaz, "Primary", state="disabled")
    boton_camara.pack(side="left", padx=SPACING_XS)

    panel_relacion = ttk.LabelFrame(herramientas_faciales, text="Asignación biométrica", padding=SPACING_CARD)
    panel_relacion.pack(fill="x", pady=(0, SPACING_MD))
    ttk.Label(panel_relacion, text="Relaciona empleados registrados con sus etiquetas faciales.",
              foreground=COLORES["secundario"]).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, SPACING_MD))
    ttk.Label(panel_relacion, text="Empleado").grid(row=1, column=0, sticky="w",pady=(0,SPACING_SM))
    selector_empleado = ttk.Combobox(panel_relacion, state="readonly", width=38)
    selector_empleado.grid(row=2, column=0, padx=(0,SPACING_LG),sticky='ew')
    ttk.Label(panel_relacion, text="Etiqueta facial").grid(row=1, column=1, sticky="w",pady=(0,SPACING_SM))
    selector_etiqueta = ttk.Combobox(panel_relacion, state="readonly", width=16)
    selector_etiqueta.grid(row=2, column=1, padx=(0,SPACING_LG),sticky='ew')
    panel_relacion.columnconfigure(0,weight=3);panel_relacion.columnconfigure(1,weight=1)

    cols_e = ("codigo_empleado", "nombre", "cargo", "subject", "estado_facial", "estado_empleado")
    cuerpo_personal=ttk.Frame(lista_empleados,style='App.TFrame');cuerpo_personal.pack(fill='both',expand=True)
    panel_personal=DetailPanel(cuerpo_personal,'Empleado seleccionado');panel_personal.pack(side='right',fill='y',padx=(12,0))
    tabla_e = _tabla(cuerpo_personal, cols_e,
                     ("Código", "Empleado", "Cargo", "Subject", "Estado facial", "Estado empleado"),
                     (105, 190, 190, 90, 150, 110))
    tabla_e.configure(displaycolumns=('codigo_empleado','nombre','cargo','estado_empleado'))
    def detalle_personal(_=None):
        if not tabla_e.selection():return
        valores=tabla_e.item(tabla_e.selection()[0],'values')
        panel_personal.set('\n\n'.join(f'{titulo}: {valor}' for titulo,valor in zip(('Código','Nombre','Cargo','Identidad facial','Estado facial','Estado'),valores)))
    tabla_e.bind('<<TreeviewSelect>>',detalle_personal)
    tabla_e.tag_configure("reconocible", background=COLORES["success_bg"], foreground=COLORES["success_text"])
    tabla_e.tag_configure("pendiente", background=COLORES["warning_bg"], foreground=COLORES["warning_text"])
    tabla_e.tag_configure("inactivo", background=COLORES["azul_claro"], foreground=COLORES["secundario"])
    empleados_tabla = {}
    mapa_selector_empleados = {}
    relaciones_por_empleado = {}
    def cargar_empleados():
        if selector_motor.get()=='cnn' and selector_modo_cnn.get()=='Dataset actual':return
        try:
            datos = listar_empleados()
            relaciones = listar_relaciones()
        except Exception as exc: _error(exc, ventana); return
        empleados_tabla.clear(); mapa_selector_empleados.clear(); relaciones_por_empleado.clear()
        empleados_activos_ui.set(str(sum(bool(e.get("estado")) for e in datos)))
        rostros_registrados_ui.set(str(sum(bool(r.get("etiqueta_modelo")) for r in relaciones)))
        rostros_pendientes_ui.set(str(sum(not r.get("etiqueta_modelo") for r in relaciones)))
        tabla_e.delete(*tabla_e.get_children())
        nombres = [f'{e["codigo_empleado"]} - {e["nombres"]} {e["apellidos"]}' for e in datos]
        mapa_selector_empleados.update({nombre: e["id_empleado"] for nombre, e in zip(nombres, datos)})
        selector_empleado["values"] = nombres
        estado_facial_motor = obtener_estado_cnn(selector_motor.get())
        etiquetas_modelo = (set(estado_facial_motor.get("subjects", [])) if selector_motor.get() in ("embeddings","comparacion")
                           else set(listar_etiquetas_disponibles(incluir_asignadas=True)))
        selector_etiqueta["values"] = sorted(etiquetas_modelo)
        for e in datos:
            empleados_tabla[e["id_empleado"]] = e
        for relacion in relaciones:
            relaciones_por_empleado[relacion["id_empleado"]] = relacion
            subject = relacion["etiqueta_modelo"]
            if not subject:
                estado_facial = "Sin rostro registrado"
            elif selector_motor.get()=='cnn':
                from ai.facial.diagnostico_cnn import estado_subject
                estado_facial=estado_subject(subject,estado_facial_motor['modelo_valido'])
            elif subject in etiquetas_modelo and estado_facial_motor["modelo_valido"]:
                estado_facial = "Reconocible"
            else:
                estado_facial = "Pendiente de calibración" if selector_motor.get() in ("embeddings","comparacion") or estado_facial_motor.get('entrenada') else "Pendiente de reentrenamiento"
            estado_empleado = "Activo" if relacion["empleado_activo"] else "Inactivo"
            tag = "inactivo" if not relacion["empleado_activo"] else "reconocible" if estado_facial == "Reconocible" else "pendiente"
            insertar_fila(tabla_e, "", "end", iid=str(relacion["id_empleado"]), tags=(tag,),
                           values=(relacion["codigo_empleado"], relacion["nombre"],
                                   relacion["cargo"] or "—", subject or "—",
                                   estado_facial, estado_empleado))

    def asignar_relacion():
        if selector_empleado.get() not in mapa_selector_empleados or not selector_etiqueta.get():
            messagebox.showwarning("Relación facial", "Seleccione empleado y etiqueta.", parent=ventana)
            return
        try:
            asignar_etiqueta_empleado(mapa_selector_empleados[selector_empleado.get()],
                                      selector_etiqueta.get())
            cargar_empleados()
            messagebox.showinfo("Relación facial", "Relación guardada correctamente.", parent=ventana)
        except Exception as exc:
            _error(exc, ventana)

    crear_boton_accion(panel_relacion, "Asignar", asignar_relacion, "Success").grid(row=3, column=0,sticky='w',pady=(SPACING_LG,0))
    def actualizar_relacion_ui():
        seleccion=tabla_e.selection()
        if not seleccion or selector_empleado.get() not in mapa_selector_empleados or not selector_etiqueta.get():
            messagebox.showwarning("Relación facial","Seleccione una fila, empleado y etiqueta.",parent=ventana); return
        relacion=relaciones_por_empleado.get(int(seleccion[0]))
        if not relacion or not relacion["id_rostro"]:
            messagebox.showwarning("Relación facial","La fila seleccionada no tiene relación activa.",parent=ventana); return
        try:
            actualizar_relacion(relacion["id_rostro"],mapa_selector_empleados[selector_empleado.get()],selector_etiqueta.get())
            cargar_empleados()
        except Exception as exc: _error(exc,ventana)
    crear_boton_accion(panel_relacion,"Actualizar relación",actualizar_relacion_ui,"Primary").grid(row=3,column=1,sticky='w',pady=(SPACING_LG,0))

    def planificar_captura_cnn(empleado):
        from ai.facial.diagnostico_cnn import leer,conflictos_historicos
        from ai.facial.sesiones_cnn import plan_subject,abrir_plan
        relacion=relaciones_por_empleado.get(empleado['id_empleado'],{})
        subject=relacion.get('etiqueta_modelo')
        try:plan=plan_subject(subject,leer('dataset.json'))
        except ValueError as error:
            messagebox.showwarning('Capturar sesión CNN',str(error),parent=ventana);return
        return abrir_plan(ventana,empleado,plan,lambda p:iniciar_captura_empleado(empleado,p),
            prioridad=any(subject in par for par in conflictos_historicos()))

    def iniciar_captura_empleado(empleado,plan_cnn=None):
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        if selector_motor.get()=='cnn' and plan_cnn is None:
            return planificar_captura_cnn(empleado)
        camara_en_uso["valor"] = True
        boton_camara.configure(state="disabled"); boton_entrenar.configure(state="disabled")
        motor_seleccionado = 'cnn' if plan_cnn else selector_motor.get()
        nombre_empleado = f'{empleado["nombres"]} {empleado["apellidos"]}'
        resultado_cnn.set(f"Registrando rostro de {nombre_empleado}...")
        cancelado = {"valor": False}

        def solicitar_cierre(_modo):
            cancelado["valor"] = True
            detener_reconocimiento()

        if plan_cnn:
            from ai.facial.sesiones_cnn import VentanaSesionCNN
            dialogo=VentanaSesionCNN(ventana,nombre_empleado,solicitar_cierre,plan_cnn)
        else:dialogo = VentanaCamara(ventana, "registro", nombre_empleado, solicitar_cierre)

        def finalizar(resultado=None, error=None):
            camara_en_uso["valor"] = False
            dialogo.cerrar()
            boton_entrenar.configure(state="normal")
            actualizar_estado_cnn(); cargar_empleados()
            if error:
                _error(error, ventana); return
            if cancelado["valor"] and not resultado.get('completado'):
                resultado_cnn.set("Registro facial cancelado.")
                return
            if not resultado["completado"]:
                messagebox.showwarning("Registro facial",
                    f'Empleado registrado, pero el rostro no fue completado. Imágenes válidas: {resultado["imagenes_guardadas"]}.',
                    parent=ventana)
                return
            resultado_cnn.set(f'Rostro {resultado["subject"]} registrado con {resultado["imagenes_guardadas"]} imágenes.')
            if resultado.get("motor") == "embeddings":
                messagebox.showinfo("Registro facial", "Muestras y embeddings guardados. Evalúa y calibra conocidos y desconocidos antes de aceptar identidades; consulta RECONOCIMIENTO_FACIAL.md.", parent=ventana)
            else:
                resultado_cnn.set(f"Sesión {resultado['numero_sesion']} completada correctamente.\n"
                    f"{resultado['subject']} · Sesiones CNN: {resultado.get('sesiones_completas',0)} / 4")
                if resultado.get('error_validacion'):
                    boton_entrenar.configure(state='disabled')
                    messagebox.showwarning('Validar dataset','La sesión se guardó. No pudo actualizarse la validación; pulsa Validar dataset antes de continuar.',parent=ventana)
        def tarea():
            try:
                resultado = capturar_rostros_nuevo_empleado(empleado["id_empleado"], presentador=dialogo, motor=motor_seleccionado)
                if motor_seleccionado=='cnn':
                    try:
                        from ai.facial.cnn_dataset import cargar
                        d=cargar()['reporte_dataset']
                        resultado['sesiones_completas']=d['sesiones_por_subject'].get(resultado['subject'],0)
                    except Exception as error:resultado['error_validacion']=str(error)
                if not aplicacion_cerrando["valor"]:
                    publicar_facial(finalizar, resultado, None)
                else:
                    camara_en_uso["valor"] = False
            except Exception as exc:
                if not aplicacion_cerrando["valor"]:
                    publicar_facial(finalizar, None, exc)
                else:
                    camara_en_uso["valor"] = False
        threading.Thread(target=tarea, daemon=True).start()

    def nuevo_empleado(empleado_actual=None):
        form = tk.Toplevel(ventana); form.title("Editar empleado" if empleado_actual else "Nuevo empleado")
        form.transient(ventana); form.grab_set(); centrar_ventana(form, 580, 580, ventana)
        form.minsize(520,580)
        encabezado_modal(form, "EDITAR EMPLEADO" if empleado_actual else "NUEVO EMPLEADO", "Datos del personal")
        cuerpo = ttk.Frame(form, padding=SPACING_LG)
        cuerpo.pack(fill="both", expand=True); entradas = {}
        for fila, campo in enumerate(("Código empleado", "Nombres", "Apellidos", "Cargo")):
            grupo=ttk.Frame(cuerpo);grupo.grid(row=fila,column=0,columnspan=2,sticky='ew',pady=(0,SPACING_MD))
            ttk.Label(grupo,text=campo).pack(anchor='w',pady=(0,SPACING_XS))
            entradas[campo] = ttk.Entry(grupo, width=38); entradas[campo].pack(fill='x')
        cuerpo.columnconfigure(0,weight=1)
        if empleado_actual:
            for campo,valor in (("Código empleado",empleado_actual["codigo_empleado"]),
                                ("Nombres",empleado_actual["nombres"]),("Apellidos",empleado_actual["apellidos"]),
                                ("Cargo",empleado_actual["cargo"] or "")):
                entradas[campo].insert(0,valor)
        def guardar():
            try:
                if empleado_actual:
                    actualizar_empleado(empleado_actual["id_empleado"],entradas["Código empleado"].get(),
                                        entradas["Nombres"].get(),entradas["Apellidos"].get(),entradas["Cargo"].get())
                    empleado = empleado_actual
                else:
                    empleado = registrar_empleado(entradas["Código empleado"].get(), entradas["Nombres"].get(),
                                                   entradas["Apellidos"].get(), entradas["Cargo"].get())
            except Exception as exc:
                _error(exc, form); return
            form.destroy(); cargar_empleados()
            if not empleado_actual and messagebox.askyesno("Empleado", "Empleado guardado. ¿Registrar su rostro ahora?", parent=ventana):
                iniciar_captura_empleado(empleado)
        acciones = ttk.Frame(form,padding=SPACING_MD); acciones.pack(side='bottom',fill='x')
        crear_boton_accion(acciones, "Cancelar", form.destroy).pack(side="left", padx=SPACING_XS)
        crear_boton_accion(acciones, "Guardar", guardar, "Success").pack(side="left", padx=SPACING_XS)

    def empleado_seleccionado():
        seleccion=tabla_e.selection()
        if not seleccion: messagebox.showwarning("Empleado","Seleccione un empleado.",parent=ventana); return None
        return empleados_tabla.get(int(seleccion[0]))
    def editar_empleado_ui():
        empleado=empleado_seleccionado()
        if empleado: nuevo_empleado(empleado)
    def eliminar_empleado_ui():
        empleado=empleado_seleccionado()
        if empleado and messagebox.askyesno("Eliminar empleado",f'¿Desea eliminar a {empleado["nombres"]} {empleado["apellidos"]}?',parent=ventana):
            try: eliminar_empleado(empleado["id_empleado"]); cargar_empleados()
            except Exception as exc: _error(exc,ventana)
    def registrar_rostro_ui():
        empleado=empleado_seleccionado()
        if empleado: iniciar_captura_empleado(empleado)
    def capturar_sesion_cnn_ui():
        if camara_en_uso['valor'] or entrenamiento_en_curso['valor']:return
        empleado=empleado_seleccionado()
        if empleado:
            selector_motor.set('cnn');selector_modo_cnn.set('Validación estricta');actualizar_estado_cnn();cargar_empleados()
            return planificar_captura_cnn(empleado)
    def eliminar_rostro_ui():
        empleado=empleado_seleccionado()
        relacion=relaciones_por_empleado.get(empleado["id_empleado"]) if empleado else None
        if not relacion or not relacion["id_rostro"]:
            messagebox.showwarning("Relación facial","El empleado no tiene rostro activo.",parent=ventana); return
        if messagebox.askyesno("Eliminar relación","¿Desea desactivar la relación facial? Las imágenes se conservarán.",parent=ventana):
            try: eliminar_relacion(relacion["id_rostro"]); cargar_empleados()
            except Exception as exc: _error(exc,ventana)
    crear_boton_accion(acciones_empleado,"Nuevo empleado",nuevo_empleado,"Primary").pack(side="left",padx=SPACING_XS)
    crear_boton_accion(acciones_empleado,"Editar",editar_empleado_ui).pack(side="left",padx=SPACING_XS)
    crear_boton_accion(acciones_empleado,"Eliminar",eliminar_empleado_ui,"Danger").pack(side="left",padx=SPACING_XS)
    crear_boton_accion(acciones_empleado,"Registrar rostro",registrar_rostro_ui,"Success").pack(side="left",padx=SPACING_XS)
    boton_captura_sesion_cnn=crear_boton_accion(acciones_empleado,"Capturar sesión CNN",capturar_sesion_cnn_ui,"Primary")
    boton_captura_sesion_cnn.pack(side="left",padx=SPACING_XS)
    crear_boton_accion(acciones_empleado,"Eliminar relación facial",eliminar_rostro_ui,"Danger").pack(side="left",padx=SPACING_XS)
    agrupar_acciones(acciones_empleado,'Más acciones',[b for b in acciones_empleado.winfo_children()
        if isinstance(b,ttk.Button) and ('Danger' in str(b.cget('style')) or b==boton_captura_sesion_cnn)])
    crear_boton_accion(acciones_empleado,'Reconocer',reconocer_rostro_interfaz).pack(side='left',padx=4)
    organizar_acciones(acciones_empleado)

    # Resumen de inteligencia: herramientas en sus pantallas correspondientes.
    from ui.analisis_ui import AnalisisUI
    analisis_ui=AnalisisUI(pestana_ia,ventana,lambda:prediccion_ui,lambda:anomalias_ui,
        lambda:notebook.select(pestana_prediccion.pagina),
        lambda:notebook.select(nuevas['Anomalías'].pagina))

    # Pestaña Agente local de inventario
    encabezado_seccion(pestana_agente, "JARVIS",
                       "Asistente inteligente del inventario")
    barra_estado = crear_tarjeta(pestana_agente, SPACING_MD); barra_estado.pack(fill="x", pady=(0, SPACING_MD))
    estado_agente = tk.StringVar(value="● Disponible")
    etiqueta_estado = etiqueta_visual(barra_estado, textvariable=estado_agente, background=COLORES["success_bg"],
                                     font=FONTS["boton"], foreground=COLORES["success_text"], padx=SPACING_MD, pady=SPACING_SM)
    etiqueta_estado.pack(side="left")
    etiqueta_proveedor_voz = ttk.Label(barra_estado, text=obtener_estado_tts()["etiqueta"])
    etiqueta_proveedor_voz.pack(side="left", padx=SPACING_MD)
    ttk.Label(barra_estado,
              text="Productos · Ubicaciones · Existencias · Movimientos",
              background=COLORES["tarjeta"], foreground=COLORES["secundario"]).pack(side="right")
    def actualizar_proveedor_voz():
        etiqueta_proveedor_voz.configure(text=obtener_estado_tts()['etiqueta'])
        ventana.after(250, actualizar_proveedor_voz)
    ventana.after(250, actualizar_proveedor_voz)
    conversacion = ChatConversacion(pestana_agente)
    conversacion.pack(fill="both", expand=True)
    pie_agente = crear_tarjeta(pestana_agente, SPACING_MD)
    pie_agente.pack(fill="x", pady=(SPACING_MD, 0))
    texto_pregunta = tk.StringVar()
    pregunta_agente = ttk.Entry(pie_agente, textvariable=texto_pregunta)
    pregunta_agente.pack(side="left", fill="x", expand=True, padx=(0, SPACING_SM))
    texto_placeholder = "Escribe un mensaje para Jarvis..."
    pregunta_agente.insert(0, texto_placeholder)
    opciones_voz = ttk.Frame(pestana_agente)
    opciones_voz.pack(fill="x", pady=(SPACING_SM, 0))
    responder_con_voz = tk.BooleanVar(value=configuracion['jarvis']['respuesta_hablada'])
    modo_asistente = tk.BooleanVar(value=configuracion['jarvis']['activacion'])
    # Solo el hilo Tk consume eventos; los trabajadores nunca llaman widgets/after.
    eventos_jarvis = queue.Queue()
    cancelar_escucha = threading.Event()
    control_voz = {"escuchando": False, "procesando": False, "hablando": False,
                   "hilo_escucha": None, "hilo_trabajo": None}

    def procesar_con_metricas(pregunta):
        inicio = time.perf_counter()
        respuesta = procesar_consulta(pregunta, estructurada=True)
        registrar_tiempo_jarvis(time.perf_counter() - inicio)
        return respuesta

    def ejecutar_accion_jarvis(accion):
        try:
            if accion['tipo']=='abrir_modulo':
                for pagina in notebook.tabs():
                    if notebook.tab(pagina,'text').casefold()==accion['modulo'].casefold():
                        notebook.select(pagina);break
            if accion['tipo']=='led_producto':
                from integrations.arduino.led_service import servicio_led
                mapa_almacen.trabajo_led.ejecutar(lambda:servicio_led.encender_por_producto(accion['id']),
                    lambda r:(escribir_chat('Jarvis',r['mensaje']),mostrar_producto_en_mapa(accion['id'])))
            if accion['tipo']=='producto_mapa':mostrar_producto_en_mapa(accion['id'])
            elif accion['tipo']=='abrir_mapa':
                mapa_almacen.refrescar();notebook.select(pestana_mapa.pagina)
            elif accion['tipo']=='facial':reconocer_rostro_interfaz()
            elif accion['tipo']=='ubicacion':
                mapa_almacen.mostrar_ubicacion(accion['id']);notebook.select(pestana_mapa.pagina)
            elif accion['tipo']=='ubicaciones':
                mapa_almacen.almacen.set('Todos');mapa_almacen.zona.set('Todas')
                mapa_almacen.busqueda.delete(0,'end')
                mapa_almacen.resaltados=set(accion['ids']);mapa_almacen.seleccion=None
                mapa_almacen.refrescar();notebook.select(pestana_mapa.pagina)
        except Exception:
            traceback.print_exc()

    def escribir_chat(autor, texto,acciones=None):
        if acciones:
            botones=[(accion.get('etiqueta','Ver en mapa'),lambda a=dict(accion):ejecutar_accion_jarvis(a)) for accion in acciones]
            conversacion.agregar(autor,texto,botones)
        else:conversacion.agregar(autor, texto)

    colores_estado = {"Listo": COLORES["success_text"], "Escuchando...": COLORES["azul"],
                      "Procesando...": COLORES["warning_text"], "Hablando...": COLORES["azul"],
                      "Error": COLORES["peligro"], "Esperando activación...": COLORES["azul"]}

    def actualizar_estado(estado):
        from core.system_state import state_manager
        texto_estado={"Listo":"● En espera", "Escuchando...":"🎤 Escuchando...",
            "Procesando...":"● Procesando...", "Hablando...":"🔊 Hablando...", "Error":"⚠ Error"}.get(estado,estado)
        estado_agente.set(texto_estado)
        state_manager.set_activity('JARVIS',{'Escuchando...':'LISTENING','Procesando...':'PROCESSING','Hablando...':'SPEAKING'}.get(estado,'IDLE'))
        tono = "danger" if estado == "Error" else "warning" if estado == "Procesando..." else "success" if estado == "Listo" else "info"
        etiqueta_estado.configure(foreground=colores_estado.get(estado, COLORES["secundario"]),
                                  background=COLORES[tono + "_bg"])

    def ocupado():
        return any(control_voz[k] for k in ("escuchando", "procesando", "hablando"))

    def actualizar_controles():
        bloqueado = ocupado() or modo_asistente.get()
        boton_hablar.configure(state="disabled" if bloqueado else "normal",
                              text="🎤 Escuchando..." if control_voz["escuchando"] else "🎤 Hablar",
                              style="Action.TButton" if control_voz["escuchando"] else "Primary.TButton")
        valido = texto_pregunta.get().strip() and texto_pregunta.get() != texto_placeholder
        puede_enviar=not control_voz['escuchando'] and not control_voz['procesando'] and not modo_asistente.get()
        boton_enviar.configure(state="normal" if valido and puede_enviar else "disabled")
        boton_reiniciar.configure(state="disabled" if bloqueado else "normal")
        boton_detener.configure(state="normal" if control_voz["hablando"] else "disabled")

    def mostrar_error_voz(error):
        actualizar_estado("Error")
        escribir_chat("Jarvis", str(error).strip() or "Ocurrió un error de audio. Intenta nuevamente.")

    def enviar_consulta(pregunta, origen='desktop'):
        """Ruta compartida de texto y voz; preserva el agente y sus datos reales."""
        if control_voz['hablando'] and not control_voz['procesando'] and not control_voz['escuchando']:
            control_voz['consulta_pendiente']=pregunta
            control_voz['consulta_pendiente_origen']=origen
            detener_voz()
            actualizar_estado('Interrumpiendo voz...')
            return
        if ocupado() or aplicacion_cerrando["valor"]:
            return
        control_voz["procesando"] = True
        escribir_chat("Tú", pregunta)
        actualizar_estado("Procesando...")
        actualizar_controles()
        def tarea():
            try:
                from core.audit_service import use_context
                with use_context(origin=origen):
                    eventos_jarvis.put(("respuesta", procesar_con_metricas(pregunta)))
            except Exception as exc:
                eventos_jarvis.put(("error_consulta", "No pude consultar el almacén. Intenta nuevamente."))
        hilo = threading.Thread(target=tarea, daemon=True)
        control_voz["hilo_trabajo"] = hilo
        hilo.start()

    def reproducir_respuesta(texto):
        control_voz["hablando"] = True
        actualizar_estado("Hablando...")
        actualizar_controles()
        def tarea():
            error = None
            try:
                hablar(texto)
            except Exception as exc:
                error = str(exc)
            finally:
                eventos_jarvis.put(("fin_voz", error))
        hilo = threading.Thread(target=tarea, daemon=True)
        control_voz["hilo_trabajo"] = hilo
        hilo.start()

    def enviar_pregunta(evento=None):
        pregunta = pregunta_agente.get().strip()
        if pregunta and pregunta != texto_placeholder and not control_voz['escuchando'] and not control_voz['procesando'] and not modo_asistente.get():
            pregunta_agente.delete(0, tk.END)
            enviar_consulta(pregunta)
        return "break" if evento else None

    def iniciar_escucha(continua=False):
        if ocupado() or aplicacion_cerrando["valor"]:
            return
        cancelar_escucha.clear()
        control_voz["escuchando"] = True
        actualizar_estado("Esperando activación..." if continua else "Escuchando...")
        actualizar_controles()
        def tarea():
            tipo, resultado = "texto_voz", None
            try:
                resultado = escuchar_pregunta(cancelar=cancelar_escucha)
            except EscuchaSinTexto as exc:
                tipo, resultado = "silencio", str(exc)
            except Exception as exc:
                tipo, resultado = "error_escucha", str(exc)
            eventos_jarvis.put((tipo, (resultado, continua, cancelar_escucha.is_set())))
        hilo = threading.Thread(target=tarea, daemon=True)
        control_voz["hilo_escucha"] = hilo
        hilo.start()

    def hablar_una_vez():
        if not modo_asistente.get():
            iniciar_escucha()

    esperando_pregunta = {"valor": False}

    def cambiar_modo_asistente():
        if modo_asistente.get():
            if ocupado():
                modo_asistente.set(False)
                escribir_chat("Jarvis", "Espera a que termine la operación actual para activar el modo continuo.")
            else:
                iniciar_escucha(continua=True)
        else:
            cancelar_escucha.set()
            esperando_pregunta["valor"] = False
            if not ocupado():
                actualizar_estado("Listo")
        actualizar_controles()

    def consumir_eventos_jarvis():
        if aplicacion_cerrando["valor"]:
            return
        while True:
            try:
                tipo, dato = eventos_jarvis.get_nowait()
            except queue.Empty:
                break
            if tipo in {"texto_voz", "silencio", "error_escucha"}:
                control_voz["escuchando"] = False
                control_voz["hilo_escucha"] = None
                texto, continua, cancelada = dato
                if cancelada:
                    actualizar_estado("Listo")
                elif tipo == "error_escucha":
                    modo_asistente.set(False)
                    esperando_pregunta["valor"] = False
                    mostrar_error_voz(texto)
                elif tipo == "silencio":
                    if not continua:
                        mostrar_error_voz(texto)
                elif continua:
                    pregunta = texto if esperando_pregunta["valor"] else extraer_consulta_activada(texto)
                    esperando_pregunta["valor"] = False
                    if pregunta:
                        enviar_consulta(pregunta,origen='voice')
                    elif pregunta == "":
                        esperando_pregunta["valor"] = True
                        escribir_chat("Jarvis", "Te escucho. Di tu consulta.")
                elif texto:
                    enviar_consulta(texto,origen='voice')
            elif tipo == "respuesta":
                control_voz["procesando"] = False
                if isinstance(dato,dict):
                    for accion in dato.get("acciones_ui",[]):
                        ejecutar_accion_jarvis(accion)
                    texto=dato["respuesta"]; voz=dato.get("voz",texto)
                else: texto=voz=dato
                escribir_chat("Jarvis", texto,dato.get('acciones_opcionales') if isinstance(dato,dict) else None)
                if responder_con_voz.get():
                    reproducir_respuesta(voz)
                else:
                    actualizar_estado("Listo")
            elif tipo == "error_consulta":
                control_voz["procesando"] = False
                mostrar_error_voz(dato)
            elif tipo == "fin_voz":
                control_voz["hablando"] = False
                pendiente=control_voz.pop('consulta_pendiente',None)
                if dato:
                    mostrar_error_voz(dato)
                else:
                    actualizar_estado("Listo")
                if pendiente:enviar_consulta(pendiente,origen=control_voz.pop('consulta_pendiente_origen','desktop'))
            actualizar_controles()
        if modo_asistente.get() and not ocupado():
            iniciar_escucha(continua=True)
        ventana.after(50, consumir_eventos_jarvis)

    def limpiar_chat():
        if ocupado() or modo_asistente.get():
            return
        conversacion.limpiar()
        reiniciar_contexto()
        escribir_chat('Jarvis','Contexto reiniciado.')
        actualizar_estado("Listo")
        pregunta_agente.focus_set()

    boton_hablar = crear_boton_accion(pie_agente, "🎤 Hablar", hablar_una_vez, "Primary")
    boton_hablar.pack(side="left", padx=(0, SPACING_SM))
    boton_enviar = crear_boton_accion(pie_agente, "Enviar", enviar_pregunta, "Success", state="disabled")
    boton_enviar.pack(side="left")
    boton_reiniciar = crear_boton_accion(opciones_voz, "Reiniciar contexto", limpiar_chat)
    boton_reiniciar.pack( side="right", padx=(SPACING_SM, 0))
    boton_detener = crear_boton_accion(opciones_voz, "Detener voz", detener_voz, "Danger", state="disabled")
    boton_detener.pack(side="left", padx=SPACING_SM)
    ttk.Checkbutton(opciones_voz, text="Responder con voz",
                    variable=responder_con_voz).pack(side="left", padx=(SPACING_MD, SPACING_XS))
    ttk.Checkbutton(opciones_voz, text='Modo continuo ("Jarvis")',
                    variable=modo_asistente,
                    command=cambiar_modo_asistente).pack(side="left", padx=SPACING_XS)
    def gestionar_placeholder(evento=None):
        if pregunta_agente.focus_get() == pregunta_agente and pregunta_agente.get() == texto_placeholder:
            pregunta_agente.delete(0, tk.END)
        elif pregunta_agente.focus_get() != pregunta_agente and not pregunta_agente.get().strip():
            pregunta_agente.insert(0, texto_placeholder)

    pregunta_agente.bind("<FocusIn>", gestionar_placeholder)
    pregunta_agente.bind("<FocusOut>", gestionar_placeholder)
    pregunta_agente.bind("<Return>", enviar_pregunta)
    texto_pregunta.trace_add("write", lambda *_: actualizar_controles())
    ventana.after(50, consumir_eventos_jarvis)
    escribir_chat("Jarvis", "Hola. Soy Jarvis, tu asistente inteligente de inventario. ¿Qué necesitas revisar?")
    precalentar_voz()

    from ui.anomalias_ui import AnomaliasUI
    from integrations.reporting.reportes_ui import ReportesUI
    from ui.estado_ui import EstadoUI
    from ui.configuracion_ui import ConfiguracionUI
    from surveillance.vigilancia_ui import VigilanciaUI
    pestana_vigilancia=crear_pagina(notebook)
    navegacion.add(pestana_vigilancia.pagina,text='Vigilancia')
    vigilancia_ui=VigilanciaUI(pestana_vigilancia,ventana,_tabla)
    nuevas={}
    for titulo in ('Anomalías','Reportes','Estado','Configuración'):
        p=crear_pagina(notebook); navegacion.add(p.pagina,text=titulo); nuevas[titulo]=p
    anomalias_ui=AnomaliasUI(nuevas['Anomalías'],ventana,_tabla)
    reportes_ui=ReportesUI(nuevas['Reportes'],ventana,_tabla)
    def abrir_resumenes(_=None):
        actual=notebook.select()
        if actual==str(pestana_ia.pagina):analisis_ui.cargar()
        elif actual==str(nuevas['Reportes'].pagina):reportes_ui.al_entrar()
    notebook.bind('<<NotebookTabChanged>>',abrir_resumenes,add='+')
    def actualizar_badges(snapshot):
        if 'snapshot' in snapshot:snapshot=snapshot['snapshot']
        for label,name in (('Base de datos','SQL'),('JARVIS','JARVIS'),('Cámara','CAMARA')):
            view=format_service_state(snapshot[name]);short='BD' if name=='SQL' else label
            badges[label].estado_detalle=short+': '+view['text']+'\n'+snapshot[name]['message']
            badges[label].configure(text=short+' '+view['icon'],foreground=view['color'])
        online=sum(snapshot.get(key,{}).get('status')=='ONLINE' for key in ('CAMARA_1','CAMARA_2'))
        badges['Cámara'].configure(text=f'Cámaras {online}/2 ONLINE')
        badges['Cámara'].estado_detalle='\n'.join(snapshot[key].get('details',{}).get('name',key)+': '+snapshot[key]['status'] for key in ('CAMARA_1','CAMARA_2'))
        overall=health_summary(snapshot)
        view=format_service_state(snapshot['JARVIS'])
        estado_footer.configure(text='JARVIS: '+view['text'],foreground=view['color'])
        badges['Sistema'].configure(text='● '+{'HEALTHY':'Servicios en línea','DEGRADED':'Servicios por revisar','CRITICAL':'Revisar SQL'}[overall])
    from ui.service_state_ui import StateBinding
    state_binding=StateBinding(ventana,actualizar_badges,panel_badges)
    estado_ui=EstadoUI(nuevas['Estado'],ventana,actualizar_badges)
    def configuracion_guardada(c):
        nombre_sistema.set(c['general']['nombre']); ventana.title(c['general']['nombre'])
        from core.health_monitor import apply_configuration
        apply_configuration(c)
    configuracion_ui=ConfiguracionUI(nuevas['Configuración'],ventana,configuracion_guardada)
    crear_boton_accion(acciones_motor,'Configurar',lambda:notebook.select(nuevas['Configuración'].pagina)).pack(side='left',padx=SPACING_XS)
    secundarios=[b for b in acciones_motor.winfo_children() if isinstance(b,ttk.Button) and b not in (boton_entrenar,boton_camara)]
    agrupar_acciones(acciones_motor,'Herramientas',secundarios)
    organizar_acciones(acciones_motor)
    def abrir_pantalla_inicial():
        for p in notebook.tabs():
            if notebook.tab(p,'text')==configuracion['general']['inicio']: notebook.select(p); break
        if modo_asistente.get(): cambiar_modo_asistente()
    ventana.after(100,abrir_pantalla_inicial)

    dashboard = Dashboard(pestana_dashboard, ventana, _tabla,
        acciones=(("Nuevo producto", nuevo_producto, "Primary"),
                  ("Registrar entrada", lambda: abrir_movimiento("Entrada"), "Success"),
                  ("Registrar salida", lambda: abrir_movimiento("Salida"), "Danger"),
                  ("Reconocer empleado", reconocer_rostro_interfaz, "Primary"),
                  ("Abrir JARVIS", abrir_jarvis, "Secondary")),
        estado_facial=estado_cnn, estado_jarvis=estado_agente)
    def al_abrir_dashboard(_evento=None):
        if notebook.select() == str(pestana_dashboard.pagina) and not aplicacion_cerrando["valor"]:
            dashboard.actualizar()
    notebook.bind("<<NotebookTabChanged>>", al_abrir_dashboard, add="+")
    temporizador_dashboard = {"id": None}
    def refrescar_dashboard():
        if aplicacion_cerrando["valor"]:
            return
        al_abrir_dashboard()
        temporizador_dashboard["id"] = ventana.after(60000, refrescar_dashboard)
    temporizador_dashboard["id"] = ventana.after(60000, refrescar_dashboard)

    def actualizar_todo():
        cargar_productos()
        cargar_historial()
        cargar_alertas()
        cargar_empleados()
        dashboard.actualizar()
        mapa_almacen.refrescar()
        prediccion_ui.cargar()

    cargar_productos()
    cargar_historial()
    cargar_alertas()
    cargar_empleados()
    actualizar_estado_cnn()
    dashboard.actualizar()
    def cerrar_aplicacion():
        if aplicacion_cerrando["valor"]:
            return
        aplicacion_cerrando["valor"] = True
        state_manager.begin_shutdown()
        health_monitor.stop_event.set()
        state_binding.close()
        servicio_bot_telegram.cerrar()
        dashboard.cerrar()
        if temporizador_dashboard["id"] is not None:
            ventana.after_cancel(temporizador_dashboard["id"])
        cancelar_escucha.set()
        detener_reconocimiento()
        cerrar_audio()
        vigilancia_ui.servicio.parar()
        vigilancia_ui.presencia_ui.servicio.parar()
        from integrations.arduino.led_service import servicio_led
        threading.Thread(target=servicio_led.desconectar,daemon=True).start()
        eventos_cerrados=threading.Event()
        cierre_iniciado=[False]
        def finalizar_cierre(intentos=0):
            if ((camara_en_uso["valor"] and intentos < 40) or
                ((vigilancia_ui.servicio.obtener_estado()['activo'] or vigilancia_ui.servicio.pendiente_disco() or vigilancia_ui.presencia_ui.servicio.obtener_estado()['activo']) and intentos < 200)):
                ventana.after(50, finalizar_cierre, intentos + 1)
                return
            if not cierre_iniciado[0]:
                cierre_iniciado[0]=True
                def cerrar_integraciones():
                    try:
                        health_monitor.close()
                        cerrar_eventos()
                    finally:
                        servicio_telegram.cerrar()
                        eventos_cerrados.set()
                threading.Thread(target=cerrar_integraciones,name='cierre-eventos',daemon=True).start()
            if not eventos_cerrados.is_set():
                ventana.after(50,finalizar_cierre,intentos+1)
                return
            ventana.destroy()
        finalizar_cierre()
    ventana.protocol("WM_DELETE_WINDOW", cerrar_aplicacion)
    ventana.mainloop()
    return False
