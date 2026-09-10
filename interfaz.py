import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None

from agente_inventario import procesar_pregunta, reiniciar_contexto
from asistente_voz import (FRASE_ACTIVACION, cerrar_audio, detener_voz,
                           escuchar_pregunta, hablar)
from alertas import eliminar_alerta, listar_alertas, marcar_alerta_atendida
from deteccion_anomalias import analizar_movimientos
from movimientos import (buscar_movimientos, listar_empleados_activos,
                         registrar_entrada, registrar_salida,
                         registrar_transferencia)
from productos import (buscar_productos, listar_categorias, listar_productos,
                       listar_ubicaciones, obtener_producto_por_id,
                       registrar_producto, ver_ubicaciones_producto,
                       actualizar_producto, eliminar_producto, crear_categoria,
                       actualizar_categoria, eliminar_categoria,
                       registrar_ubicacion, actualizar_ubicacion, eliminar_ubicacion)
from prediccion_stock import predecir_agotamiento
from empleados import (actualizar_empleado, eliminar_empleado, listar_empleados,
                       registrar_empleado)
from captura_rostros import capturar_rostros_nuevo_empleado
from reconocimiento_cnn import (detener_reconocimiento, obtener_estado_cnn,
                                reconocer_con_camara)
from dataset_rostros import cargar_dataset, resumir_dataset
from entrenar_cnn_rostros import entrenar_modelo_cnn
from rostros_empleados import (asignar_etiqueta_empleado,
                               actualizar_relacion, eliminar_relacion, listar_etiquetas_disponibles,
                               listar_relaciones)


UNIDADES = ("Unidad", "Caja", "Paquete", "Metro", "Kilogramo", "Litro")
TIPOS_MOVIMIENTO = ("Todos", "Entrada", "Salida", "Transferencia",
                    "Ajuste entrada", "Ajuste salida")

COLORES = {
    "primario": "#0F2A43", "azul": "#165D8C", "azul_claro": "#EAF4FB",
    "acento": "#18B7A0", "verde": "#22A06B", "aviso": "#F59E0B",
    "peligro": "#DC3545", "fondo": "#F5F8FC", "tarjeta": "#FFFFFF",
    "texto": "#102A43", "secundario": "#627D98", "borde": "#D9E2EC"
}


def configurar_estilos(ventana):
    """Configura una identidad visual consistente sin depender del tema instalado."""
    estilo = ttk.Style(ventana)
    estilo.configure("App.TFrame", background=COLORES["fondo"])
    estilo.configure("Card.TFrame", background=COLORES["tarjeta"], relief="solid", borderwidth=1)
    estilo.configure("Header.TFrame", background=COLORES["tarjeta"])
    estilo.configure("Titulo.TLabel", background=COLORES["fondo"], foreground=COLORES["texto"],
                      font=("Segoe UI", 20, "bold"))
    estilo.configure("Seccion.TLabel", background=COLORES["fondo"], foreground=COLORES["texto"],
                      font=("Segoe UI", 16, "bold"))
    estilo.configure("Subtitulo.TLabel", background=COLORES["fondo"], foreground=COLORES["secundario"],
                      font=("Segoe UI", 9))
    estilo.configure("CardTitle.TLabel", background=COLORES["tarjeta"], foreground=COLORES["secundario"],
                      font=("Segoe UI", 9))
    estilo.configure("CardValue.TLabel", background=COLORES["tarjeta"], foreground=COLORES["texto"],
                      font=("Segoe UI", 18, "bold"))
    estilo.configure("Primary.TButton", background=COLORES["azul"], foreground="white", padding=(14, 8))
    estilo.map("Primary.TButton", background=[("active", COLORES["primario"]), ("disabled", "#AAB7C4")])
    estilo.configure("Success.TButton", background=COLORES["acento"], foreground="white", padding=(14, 8))
    estilo.map("Success.TButton", background=[("active", COLORES["verde"])])
    estilo.configure("Danger.TButton", background=COLORES["peligro"], foreground="white", padding=(14, 8))
    estilo.map("Danger.TButton", background=[("active", "#B02A37")])
    estilo.configure("Secondary.TButton", background=COLORES["azul_claro"], foreground=COLORES["primario"], padding=(12, 8))
    estilo.map("Secondary.TButton", background=[("active", "#D8EBF7")])
    estilo.configure("Treeview", background="white", fieldbackground="white", foreground=COLORES["texto"],
                      rowheight=32, borderwidth=0, font=("Segoe UI", 9))
    estilo.configure("Treeview.Heading", background=COLORES["azul_claro"], foreground=COLORES["primario"],
                      relief="flat", padding=(8, 9), font=("Segoe UI", 9, "bold"))
    estilo.map("Treeview", background=[("selected", COLORES["azul"])], foreground=[("selected", "white")])
    estilo.configure("TNotebook", background=COLORES["fondo"], borderwidth=0)
    estilo.configure("TNotebook.Tab", background=COLORES["tarjeta"], foreground=COLORES["primario"],
                      padding=(18, 11), font=("Segoe UI", 9, "bold"))
    estilo.map("TNotebook.Tab", background=[("selected", COLORES["primario"])],
               foreground=[("selected", "white")], expand=[("selected", (0, 0, 0, 2))])
    estilo.configure("TLabelframe", background=COLORES["tarjeta"], relief="solid", borderwidth=1)
    estilo.configure("TLabelframe.Label", background=COLORES["tarjeta"], foreground=COLORES["primario"],
                      font=("Segoe UI", 10, "bold"))
    estilo.configure("TEntry", padding=7)
    estilo.configure("TCombobox", padding=6)
    return estilo


def crear_tarjeta(padre, padding=14):
    tarjeta = ttk.Frame(padre, style="Card.TFrame", padding=padding)
    return tarjeta


def crear_boton_accion(padre, texto, comando, variante="Secondary", **opciones):
    return ttk.Button(padre, text=texto, command=comando, style=f"{variante}.TButton", **opciones)


def centrar_ventana(ventana, ancho, alto, padre=None):
    ventana.update_idletasks()
    referencia = padre or ventana.master
    if referencia and referencia.winfo_exists():
        x = referencia.winfo_rootx() + max(0, (referencia.winfo_width() - ancho) // 2)
        y = referencia.winfo_rooty() + max(0, (referencia.winfo_height() - alto) // 2)
    else:
        x = (ventana.winfo_screenwidth() - ancho) // 2
        y = (ventana.winfo_screenheight() - alto) // 2
    ventana.geometry(f"{ancho}x{alto}+{x}+{y}")


def encabezado_seccion(padre, titulo, subtitulo):
    zona = ttk.Frame(padre, style="App.TFrame")
    zona.pack(fill="x", pady=(0, 12))
    ttk.Label(zona, text=titulo, style="Seccion.TLabel").pack(anchor="w")
    ttk.Label(zona, text=subtitulo, style="Subtitulo.TLabel").pack(anchor="w", pady=(2, 0))
    return zona


def aplicar_estilo_tabla(tabla):
    tabla.tag_configure("par", background="#F8FBFE")
    tabla.tag_configure("impar", background="#FFFFFF")


def _error(error, padre):
    """Muestra el error real y deja el traceback en consola para depuración."""
    print("\n========================================")
    print("ERROR REAL")
    print("========================================")
    print("Tipo:", type(error).__name__)
    print("Detalle:", repr(error))
    print("========================================")
    traceback.print_exc()

    mensaje = str(error).strip()
    if not mensaje:
        mensaje = "Ocurrió un error inesperado."

    messagebox.showerror(
        "Error",
        mensaje,
        parent=padre
    )


def _tabla(marco, columnas, titulos, anchos, horizontal=False):
    zona = ttk.Frame(marco, style="Card.TFrame", padding=1)
    zona.pack(fill="both", expand=True)
    tabla = ttk.Treeview(zona, columns=columnas, show="headings", selectmode="browse")
    for columna, titulo, ancho in zip(columnas, titulos, anchos):
        tabla.heading(columna, text=titulo)
        tabla.column(columna, width=ancho, minwidth=60)
    vertical = ttk.Scrollbar(zona, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=vertical.set)
    tabla.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    if horizontal:
        barra_h = ttk.Scrollbar(zona, orient="horizontal", command=tabla.xview)
        tabla.configure(xscrollcommand=barra_h.set)
        barra_h.grid(row=1, column=0, sticky="ew")
    zona.rowconfigure(0, weight=1)
    zona.columnconfigure(0, weight=1)
    aplicar_estilo_tabla(tabla)
    return tabla


def iniciar_aplicacion():
    ventana = tb.Window(themename="flatly") if tb is not None else tk.Tk()
    ventana.title("Sistema Inteligente de Inventario")
    ventana.geometry("1360x820")
    ventana.minsize(1120, 680)
    ventana.configure(background=COLORES["fondo"])
    configurar_estilos(ventana)

    principal = ttk.Frame(ventana, padding=(22, 18), style="App.TFrame")
    principal.pack(fill="both", expand=True)
    cabecera = crear_tarjeta(principal, padding=(20, 13))
    cabecera.pack(fill="x", pady=(0, 14))
    identidad = ttk.Frame(cabecera, style="Header.TFrame"); identidad.pack(side="left", fill="x", expand=True)
    ttk.Label(identidad, text="Sistema Inteligente de Inventario", background=COLORES["tarjeta"],
              foreground=COLORES["texto"], font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(identidad, text="Gestión, análisis y control inteligente del almacén",
              background=COLORES["tarjeta"], foreground=COLORES["secundario"],
              font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
    usuario = ttk.Frame(cabecera, style="Header.TFrame"); usuario.pack(side="right", padx=(25, 0))
    ttk.Label(usuario, text="Administrador", background=COLORES["tarjeta"], foreground=COLORES["primario"],
              font=("Segoe UI", 10, "bold")).pack(anchor="e")
    ttk.Label(usuario, text="Sistema de Inventario", background=COLORES["tarjeta"],
              foreground=COLORES["secundario"], font=("Segoe UI", 8)).pack(anchor="e")
    notebook = ttk.Notebook(principal)
    notebook.pack(fill="both", expand=True)
    pestana_productos = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_movimientos = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_historial = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_alertas = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_empleados = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_ia = ttk.Frame(notebook, padding=16, style="App.TFrame")
    pestana_agente = ttk.Frame(notebook, padding=16, style="App.TFrame")
    notebook.add(pestana_productos, text="Productos")
    notebook.add(pestana_movimientos, text="Movimientos")
    notebook.add(pestana_historial, text="Historial")
    notebook.add(pestana_alertas, text="Alertas")
    notebook.add(pestana_empleados, text="Empleados")
    notebook.add(pestana_ia, text="Análisis IA")
    notebook.add(pestana_agente, text="Agente")

    # Pestaña Productos
    encabezado_seccion(pestana_productos, "Productos", "Gestiona el inventario y las existencias del almacén")
    resumen_productos = ttk.Frame(pestana_productos, style="App.TFrame")
    resumen_productos.pack(fill="x", pady=(0, 12))
    valores_resumen = {nombre: tk.StringVar(value="0") for nombre in ("productos", "stock", "bajo", "categorias")}
    for columna, (titulo, clave) in enumerate((("Total de productos", "productos"), ("Stock total", "stock"),
                                               ("Stock bajo", "bajo"), ("Categorías", "categorias"))):
        tarjeta = crear_tarjeta(resumen_productos, 12); tarjeta.grid(row=0, column=columna, sticky="ew", padx=(0 if columna == 0 else 5, 0))
        ttk.Label(tarjeta, text=titulo, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(tarjeta, textvariable=valores_resumen[clave], style="CardValue.TLabel").pack(anchor="w", pady=(3, 0))
        resumen_productos.columnconfigure(columna, weight=1)
    barra_p = crear_tarjeta(pestana_productos, padding=10)
    barra_p.pack(fill="x", pady=(0, 12))
    ttk.Label(barra_p, text="Buscar", background=COLORES["tarjeta"], foreground=COLORES["secundario"]).pack(side="left")
    buscar_p = ttk.Entry(barra_p, width=30)
    buscar_p.pack(side="left", padx=(7, 6), fill="x", expand=True)
    busqueda_producto_after = {"id": None}
    columnas_p = ("codigo", "nombre", "categoria", "unidad", "precio", "actual", "minimo", "estado")
    tabla_p = _tabla(pestana_productos, columnas_p,
        ("Código", "Producto", "Categoría", "Unidad", "Precio", "Stock actual", "Stock mínimo", "Estado"),
        (100, 190, 150, 90, 100, 90, 90, 110))

    def cargar_productos(registros=None):
        try:
            datos = listar_productos() if registros is None else registros
            tabla_p.delete(*tabla_p.get_children())
            for indice, p in enumerate(datos):
                estado = str(p["estado_stock"])
                tag_estado = "agotado" if estado.lower() == "agotado" else "bajo" if "bajo" in estado.lower() else "normal"
                tabla_p.insert("", "end", iid=str(p["id_producto"]), tags=(tag_estado,), values=(p["codigo"], p["nombre"],
                    p["categoria"], p["unidad_medida"], f'C$ {float(p["precio"]):,.2f}',
                    p["stock_actual"], p["stock_minimo"], p["estado_stock"]))
            valores_resumen["productos"].set(str(len(datos)))
            valores_resumen["stock"].set(f'{sum(float(p["stock_actual"] or 0) for p in datos):,.0f}')
            valores_resumen["bajo"].set(str(sum("bajo" in str(p["estado_stock"]).lower() or "agotado" in str(p["estado_stock"]).lower() for p in datos)))
            valores_resumen["categorias"].set(str(len({p["categoria"] for p in datos if p["categoria"]})))
        except Exception as exc:
            _error(exc, ventana)

    def buscar_en_productos(evento=None):
        try:
            cargar_productos(buscar_productos(buscar_p.get()))
        except Exception as exc:
            _error(exc, ventana)

    def programar_busqueda_productos(evento=None):
        if busqueda_producto_after["id"]:
            ventana.after_cancel(busqueda_producto_after["id"])
        busqueda_producto_after["id"] = ventana.after(300, buscar_en_productos)

    def limpiar_productos():
        buscar_p.delete(0, tk.END)
        cargar_productos()

    def id_producto_tabla():
        seleccion = tabla_p.selection()
        if not seleccion:
            messagebox.showwarning("Producto", "Seleccione un producto.", parent=ventana)
            return None
        return int(seleccion[0])

    def detalles_producto(evento=None):
        identificador = id_producto_tabla()
        if identificador is None:
            return
        try:
            p = obtener_producto_por_id(identificador)
            ubicaciones = ver_ubicaciones_producto(identificador)
        except Exception as exc:
            _error(exc, ventana)
            return
        detalle = tk.Toplevel(ventana)
        detalle.title(f"Detalle - {p['codigo']}")
        detalle.transient(ventana); centrar_ventana(detalle, 900, 560, ventana)
        marco = ttk.LabelFrame(detalle, text="PRODUCTO", padding=12)
        marco.pack(fill="x", padx=15, pady=15)
        datos = (("Código", p["codigo"]), ("Nombre", p["nombre"]),
                 ("Descripción", p["descripcion"] or "Sin descripción"), ("Categoría", p["categoria"]),
                 ("Unidad", p["unidad_medida"]), ("Precio", f'C$ {float(p["precio"]):,.2f}'),
                 ("Stock actual", p["stock_actual"]), ("Stock mínimo", p["stock_minimo"]), ("Estado", p["estado"]))
        for i, (nombre, valor) in enumerate(datos):
            fila, grupo = divmod(i, 2)
            ttk.Label(marco, text=f"{nombre}:", font=("Segoe UI", 9, "bold")).grid(
                row=fila, column=grupo * 2, sticky="w", padx=(0, 5), pady=3)
            ttk.Label(marco, text=valor, wraplength=280).grid(
                row=fila, column=grupo * 2 + 1, sticky="w", padx=(0, 22), pady=3)
        zona = ttk.LabelFrame(detalle, text="UBICACIONES", padding=10)
        zona.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        cols = ("codigo_ubicacion", "seccion", "pasillo", "estante", "nivel", "cantidad")
        t = _tabla(zona, cols, ("Código", "Sección", "Pasillo", "Estante", "Nivel", "Cantidad"), (130, 110, 100, 100, 100, 90))
        for u in ubicaciones:
            t.insert("", "end", values=tuple("—" if u[c] is None else u[c] for c in cols))

    def nuevo_producto(producto=None):
        try:
            categorias = listar_categorias()
        except Exception as exc:
            _error(exc, ventana); return
        if not categorias:
            messagebox.showwarning("Categorías", "No hay categorías activas.", parent=ventana); return
        form = tk.Toplevel(ventana)
        form.title("Editar producto" if producto else "Nuevo producto"); form.transient(ventana); form.grab_set()
        centrar_ventana(form, 560, 500, ventana)
        cuerpo = ttk.Frame(form, padding=20); cuerpo.pack(fill="both", expand=True)
        entradas = {}
        etiquetas = ("Código", "Nombre", "Descripción", "Categoría", "Unidad", "Precio", "Stock mínimo")
        for fila, etiqueta in enumerate(etiquetas):
            ttk.Label(cuerpo, text=etiqueta + ":").grid(row=fila, column=0, sticky="w", pady=7)
        entradas["codigo"] = ttk.Entry(cuerpo, width=40); entradas["nombre"] = ttk.Entry(cuerpo, width=40)
        entradas["descripcion"] = ttk.Entry(cuerpo, width=40)
        entradas["categoria"] = ttk.Combobox(cuerpo, state="readonly", width=37, values=[c["nombre"] for c in categorias])
        entradas["unidad"] = ttk.Combobox(cuerpo, state="readonly", width=37, values=UNIDADES)
        entradas["precio"] = ttk.Entry(cuerpo, width=40); entradas["minimo"] = ttk.Entry(cuerpo, width=40)
        for fila, control in enumerate(entradas.values()): control.grid(row=fila, column=1, pady=7, padx=8)
        entradas["unidad"].set("Unidad"); entradas["precio"].insert(0, "0.00"); entradas["minimo"].insert(0, "0")
        ids = {c["nombre"]: c["id_categoria"] for c in categorias}
        if producto:
            for clave, valor in (("codigo", producto["codigo"]),("nombre", producto["nombre"]),
                                 ("descripcion", producto["descripcion"] or ""),
                                 ("unidad", producto["unidad_medida"]),("precio", producto["precio"]),
                                 ("minimo", producto["stock_minimo"])):
                entradas[clave].delete(0, tk.END); entradas[clave].insert(0, valor)
            entradas["categoria"].set(producto["categoria"])
        def guardar():
            if not entradas["categoria"].get():
                messagebox.showwarning("Validación", "Seleccione una categoría.", parent=form); return
            try:
                argumentos=(entradas["codigo"].get(), entradas["nombre"].get(), entradas["descripcion"].get(),
                    ids[entradas["categoria"].get()], entradas["unidad"].get(), entradas["precio"].get(), entradas["minimo"].get())
                if producto: actualizar_producto(producto["id_producto"], *argumentos)
                else: registrar_producto(*argumentos)
            except Exception as exc: _error(exc, form); return
            messagebox.showinfo("Producto", "Producto actualizado correctamente." if producto else "Producto registrado correctamente.", parent=form)
            form.destroy(); actualizar_todo()
        acciones_form = ttk.Frame(cuerpo); acciones_form.grid(row=8, column=0, columnspan=2, sticky="e", pady=15)
        crear_boton_accion(acciones_form, "Cancelar", form.destroy).pack(side="left", padx=4)
        crear_boton_accion(acciones_form, "Guardar", guardar, "Success").pack(side="left", padx=4)

    tabla_p.tag_configure("normal", foreground=COLORES["texto"], background="#FFFFFF")
    tabla_p.tag_configure("bajo", foreground=COLORES["texto"], background="#FFF4D6")
    tabla_p.tag_configure("agotado", foreground=COLORES["texto"], background="#FDE8E8")
    crear_boton_accion(barra_p, "Limpiar", limpiar_productos).pack(side="left", padx=3)
    crear_boton_accion(barra_p, "Nuevo producto", nuevo_producto, "Success").pack(side="right")
    def editar_producto_ui():
        identificador=id_producto_tabla()
        if identificador is not None: nuevo_producto(obtener_producto_por_id(identificador))
    def eliminar_producto_ui():
        identificador=id_producto_tabla()
        if identificador is None: return
        producto=obtener_producto_por_id(identificador)
        if messagebox.askyesno("Eliminar producto",f'¿Desea eliminar el producto {producto["nombre"]}?',parent=ventana):
            try: eliminar_producto(identificador); cargar_productos()
            except Exception as exc: _error(exc,ventana)

    def administrar_catalogo(tipo):
        es_categoria = tipo == "Categorías"
        form=tk.Toplevel(ventana); form.title(tipo); form.transient(ventana); centrar_ventana(form, 820, 500, ventana)
        cuerpo=ttk.Frame(form,padding=12); cuerpo.pack(fill="both",expand=True)
        columnas=("nombre","descripcion") if es_categoria else ("codigo_ubicacion","seccion","pasillo","estante","nivel","descripcion")
        titulos=("Nombre","Descripción") if es_categoria else ("Código","Sección","Pasillo","Estante","Nivel","Descripción")
        tabla=_tabla(cuerpo,columnas,titulos,(180,400) if es_categoria else (100,110,80,80,80,220))
        registros={}
        def cargar():
            datos=listar_categorias() if es_categoria else listar_ubicaciones()
            registros.clear(); tabla.delete(*tabla.get_children())
            llave="id_categoria" if es_categoria else "id_ubicacion"
            for dato in datos:
                registros[dato[llave]]=dato
                tabla.insert("","end",iid=str(dato[llave]),values=tuple(dato.get(c) or "—" for c in columnas))
        def editor(actual=None):
            ventana_ed=tk.Toplevel(form); ventana_ed.title("Editar" if actual else "Agregar"); ventana_ed.transient(form)
            caja=ttk.Frame(ventana_ed,padding=15); caja.pack(); entradas={}
            for fila,campo in enumerate(columnas):
                ttk.Label(caja,text=titulos[fila]+":").grid(row=fila,column=0,sticky="w",pady=5)
                entradas[campo]=ttk.Entry(caja,width=40); entradas[campo].grid(row=fila,column=1,padx=6,pady=5)
                if actual and actual.get(campo) is not None: entradas[campo].insert(0,actual[campo])
            def guardar():
                try:
                    valores=[entradas[c].get() for c in columnas]
                    if es_categoria:
                        (actualizar_categoria(actual["id_categoria"],*valores) if actual else crear_categoria(*valores))
                    else:
                        (actualizar_ubicacion(actual["id_ubicacion"],*valores) if actual else registrar_ubicacion(*valores))
                    ventana_ed.destroy(); cargar()
                except Exception as exc: _error(exc,ventana_ed)
            botones_editor = ttk.Frame(caja); botones_editor.grid(row=len(columnas), column=0, columnspan=2, sticky="e", pady=10)
            crear_boton_accion(botones_editor, "Cancelar", ventana_ed.destroy).pack(side="left", padx=4)
            crear_boton_accion(botones_editor, "Guardar", guardar, "Success").pack(side="left", padx=4)
            centrar_ventana(ventana_ed, 520, 190 if es_categoria else 390, form)
        def seleccionado():
            sel=tabla.selection()
            if not sel: messagebox.showwarning(tipo,"Seleccione un registro.",parent=form); return None
            return registros[int(sel[0])]
        def eliminar():
            actual=seleccionado()
            if actual and messagebox.askyesno(tipo,"¿Desea eliminar lógicamente el registro seleccionado?",parent=form):
                try:
                    (eliminar_categoria(actual["id_categoria"]) if es_categoria else eliminar_ubicacion(actual["id_ubicacion"]))
                    cargar()
                except Exception as exc: _error(exc,form)
        acciones=ttk.Frame(form,padding=8); acciones.pack(fill="x")
        crear_boton_accion(acciones,"Agregar",lambda:editor(),"Success").pack(side="left",padx=3)
        crear_boton_accion(acciones,"Editar",lambda:editor(seleccionado()) if tabla.selection() else seleccionado(),"Primary").pack(side="left",padx=3)
        crear_boton_accion(acciones,"Eliminar",eliminar,"Danger").pack(side="left",padx=3)
        cargar()
    crear_boton_accion(barra_p, "Editar", editar_producto_ui, "Primary").pack(side="right", padx=3)
    crear_boton_accion(barra_p, "Eliminar", eliminar_producto_ui, "Danger").pack(side="right", padx=3)
    crear_boton_accion(barra_p, "Categorías", lambda: administrar_catalogo("Categorías")).pack(side="right", padx=3)
    crear_boton_accion(barra_p, "Ubicaciones", lambda: administrar_catalogo("Ubicaciones")).pack(side="right", padx=3)
    crear_boton_accion(barra_p, "Ver ubicaciones", detalles_producto).pack(side="right", padx=3)
    crear_boton_accion(barra_p, "Actualizar", cargar_productos).pack(side="right", padx=3)
    buscar_p.bind("<KeyRelease>", programar_busqueda_productos)
    tabla_p.bind("<Double-1>", detalles_producto)

    # Pestaña Historial
    encabezado_seccion(pestana_historial, "Historial de movimientos", "Consulta y filtra todas las operaciones del inventario")
    filtros = crear_tarjeta(pestana_historial, 12); filtros.pack(fill="x", pady=(0, 12))
    ttk.Label(filtros, text="Buscar:").grid(row=0, column=0); filtro_texto = ttk.Entry(filtros, width=22)
    filtro_texto.grid(row=0, column=1, padx=5); ttk.Label(filtros, text="Tipo:").grid(row=0, column=2)
    filtro_tipo = ttk.Combobox(filtros, values=TIPOS_MOVIMIENTO, state="readonly", width=16); filtro_tipo.set("Todos")
    filtro_tipo.grid(row=0, column=3, padx=5); ttk.Label(filtros, text="Fecha desde:").grid(row=0, column=4)
    fecha_desde = ttk.Entry(filtros, width=12); fecha_desde.grid(row=0, column=5, padx=5)
    ttk.Label(filtros, text="Fecha hasta:").grid(row=0, column=6); fecha_hasta = ttk.Entry(filtros, width=12)
    fecha_hasta.grid(row=0, column=7, padx=5)
    busqueda_historial_after = {"id": None}
    cols_h = ("fecha_movimiento", "tipo_movimiento", "empleado", "codigo_producto", "producto", "cantidad",
              "ubicacion_origen", "ubicacion_destino", "stock_anterior", "stock_nuevo", "observacion")
    tabla_h = _tabla(pestana_historial, cols_h,
        ("Fecha", "Tipo", "Empleado", "Código", "Producto", "Cantidad", "Origen", "Destino", "Stock anterior", "Stock nuevo", "Observación"),
        (145, 100, 210, 90, 160, 70, 90, 90, 90, 90, 220), True)

    def cargar_historial():
        try: datos = buscar_movimientos(filtro_texto.get(), filtro_tipo.get(), fecha_desde.get().strip() or None, fecha_hasta.get().strip() or None)
        except Exception as exc: _error(exc, ventana); return
        tabla_h.delete(*tabla_h.get_children())
        for m in datos:
            tabla_h.insert("", "end", values=tuple("—" if m[c] is None else m[c] for c in cols_h))
    def programar_busqueda_historial(evento=None):
        if busqueda_historial_after["id"]:
            ventana.after_cancel(busqueda_historial_after["id"])
        fechas = (fecha_desde.get().strip(), fecha_hasta.get().strip())
        if any(fecha and len(fecha) < 10 for fecha in fechas):
            return
        busqueda_historial_after["id"] = ventana.after(300, cargar_historial)
    def limpiar_historial():
        for e in (filtro_texto, fecha_desde, fecha_hasta): e.delete(0, tk.END)
        filtro_tipo.set("Todos"); cargar_historial()
    crear_boton_accion(filtros, "Limpiar", limpiar_historial).grid(row=0, column=8, padx=3)
    crear_boton_accion(filtros, "Actualizar", cargar_historial, "Primary").grid(row=0, column=9, padx=3)
    filtro_texto.bind("<KeyRelease>", programar_busqueda_historial)
    filtro_tipo.bind("<<ComboboxSelected>>", programar_busqueda_historial)
    fecha_desde.bind("<KeyRelease>", programar_busqueda_historial)
    fecha_hasta.bind("<KeyRelease>", programar_busqueda_historial)
    fecha_desde.bind("<FocusOut>", programar_busqueda_historial)
    fecha_hasta.bind("<FocusOut>", programar_busqueda_historial)

    # Pestaña Alertas
    encabezado_seccion(pestana_alertas, "Alertas del sistema", "Supervisa eventos pendientes y situaciones que requieren atención")
    barra_a = crear_tarjeta(pestana_alertas, 12); barra_a.pack(fill="x", pady=(0, 12))
    solo_pendientes = tk.BooleanVar(value=True)
    contador_alertas = tk.StringVar(value="0 pendientes")
    ttk.Checkbutton(barra_a, text="Mostrar solamente pendientes", variable=solo_pendientes).pack(side="left")
    ttk.Label(barra_a, textvariable=contador_alertas, background=COLORES["tarjeta"], foreground=COLORES["peligro"],
              font=("Segoe UI", 10, "bold")).pack(side="left", padx=18)
    cols_a = ("fecha_generacion", "tipo", "nivel", "producto", "mensaje", "estado")
    tabla_a = _tabla(pestana_alertas, cols_a, ("Fecha", "Tipo", "Nivel", "Producto", "Mensaje", "Estado"),
                     (150, 140, 80, 170, 480, 90))
    tabla_a.tag_configure("Critica", background="#f8d7da"); tabla_a.tag_configure("Alta", background="#fff3cd")
    tabla_a.tag_configure("Media", background="#d9edf7"); tabla_a.tag_configure("Baja", background="#e8f5e9")
    def cargar_alertas():
        try: datos = listar_alertas(solo_pendientes.get())
        except Exception as exc: _error(exc, ventana); return
        tabla_a.delete(*tabla_a.get_children())
        for a in datos:
            tabla_a.insert("", "end", iid=str(a["id_alerta"]), tags=(a["nivel"],),
                           values=tuple(a[c] for c in cols_a))
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
    crear_boton_accion(barra_a, "Actualizar", cargar_alertas).pack(side="right")
    crear_boton_accion(barra_a, "Marcar como atendida", atender_alerta, "Success").pack(side="right", padx=5)
    crear_boton_accion(barra_a, "Eliminar", eliminar_alerta_ui, "Danger").pack(side="right", padx=5)
    solo_pendientes.trace_add("write", lambda *_: cargar_alertas())

    # Pestaña Movimientos y formulario común
    encabezado_seccion(pestana_movimientos, "Movimientos de inventario",
                       "Registra entradas, salidas y transferencias entre ubicaciones")
    botones_m = ttk.Frame(pestana_movimientos, style="App.TFrame"); botones_m.pack(fill="x", pady=(30, 0))

    def abrir_movimiento(tipo):
        try:
            empleados = listar_empleados_activos(); ubicaciones = listar_ubicaciones()
        except Exception as exc: _error(exc, ventana); return
        if not empleados or not ubicaciones:
            messagebox.showwarning("Datos requeridos", "Se requieren empleados y ubicaciones activas.", parent=ventana); return
        form = tk.Toplevel(ventana); form.title(f"Registrar {tipo.lower()}")
        form.transient(ventana); form.grab_set(); centrar_ventana(form, 760, 650, ventana)
        cuerpo = crear_tarjeta(form, 22); cuerpo.pack(fill="both", expand=True, padx=18, pady=18)
        nombres_e = [f'{e["codigo_empleado"]} - {e["nombres"]} {e["apellidos"]}' for e in empleados]
        ids_e = {nombre: e["id_empleado"] for nombre, e in zip(nombres_e, empleados)}
        nombres_u = [f'{u["codigo_ubicacion"]} - {u["seccion"]}' for u in ubicaciones]
        ids_u = {nombre: u["id_ubicacion"] for nombre, u in zip(nombres_u, ubicaciones)}
        ttk.Label(cuerpo, text="Empleado:").grid(row=0, column=0, sticky="w", pady=5)
        empleado = ttk.Combobox(cuerpo, values=nombres_e, state="readonly", width=42); empleado.grid(row=0, column=1, sticky="w")
        ttk.Label(cuerpo, text="Buscar producto:").grid(row=1, column=0, sticky="w", pady=5)
        busca = ttk.Entry(cuerpo, width=34); busca.grid(row=1, column=1, sticky="w")
        resultados = ttk.Treeview(cuerpo, columns=("codigo", "nombre", "stock"), show="headings", height=6)
        for c, t, a in zip(("codigo", "nombre", "stock"), ("Código", "Producto", "Stock total"), (100, 270, 90)):
            resultados.heading(c, text=t); resultados.column(c, width=a)
        resultados.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)
        producto_elegido = {"id": None}
        busqueda_movimiento_after = {"id": None}

        def buscar_producto_form(evento=None):
            try:
                datos = buscar_productos(busca.get())
            except Exception as exc:
                _error(exc, form)
                return

            resultados.delete(*resultados.get_children())
            producto_elegido["id"] = None
            seleccionado.config(text="Seleccione un producto de los resultados")

            for p in datos:
                resultados.insert(
                    "",
                    "end",
                    iid=str(p["id_producto"]),
                    values=(p["codigo"], p["nombre"], p["stock_actual"])
                )

        def programar_busqueda_movimiento(evento=None):
            if busqueda_movimiento_after["id"]:
                form.after_cancel(busqueda_movimiento_after["id"])

            busqueda_movimiento_after["id"] = form.after(
                300,
                buscar_producto_form
            )
        def elegir(evento=None):
            sel = resultados.selection()
            if not sel: return
            producto_elegido["id"] = int(sel[0]); codigo, nombre, stock = resultados.item(sel[0], "values")
            seleccionado.config(text=f"Seleccionado: {codigo} | {nombre} | Stock total: {stock}")
            if tipo != "Entrada":
                try: disponibles = [u for u in ver_ubicaciones_producto(producto_elegido["id"]) if u["cantidad"] > 0]
                except Exception as exc: _error(exc, form); return
                textos = [f'{u["codigo_ubicacion"]} | Disponible: {u["cantidad"]}' for u in disponibles]
                origen["values"] = textos; mapa_origen.clear(); mapa_origen.update({t: u for t, u in zip(textos, disponibles)})
        seleccionado = ttk.Label(cuerpo, text="Seleccione un producto de los resultados"); seleccionado.grid(row=3, column=0, columnspan=3, sticky="w", pady=5)
        mapa_origen = {}; fila = 4
        origen = ttk.Combobox(cuerpo, state="readonly", width=42)
        if tipo != "Entrada":
            ttk.Label(cuerpo, text="Ubicación origen:").grid(row=fila, column=0, sticky="w", pady=5); origen.grid(row=fila, column=1, sticky="w"); fila += 1
        destino = ttk.Combobox(cuerpo, values=nombres_u, state="readonly", width=42)
        if tipo != "Salida":
            ttk.Label(cuerpo, text="Ubicación destino:").grid(row=fila, column=0, sticky="w", pady=5); destino.grid(row=fila, column=1, sticky="w"); fila += 1
        stock_origen = ttk.Label(cuerpo, text="")
        if tipo != "Entrada": stock_origen.grid(row=fila, column=1, sticky="w"); fila += 1
        origen.bind("<<ComboboxSelected>>", lambda e: stock_origen.config(text=f'Stock disponible: {mapa_origen[origen.get()]["cantidad"]}'))
        ttk.Label(cuerpo, text="Cantidad:").grid(row=fila, column=0, sticky="w", pady=5); cantidad = ttk.Entry(cuerpo, width=18); cantidad.grid(row=fila, column=1, sticky="w"); fila += 1
        ttk.Label(cuerpo, text="Observación:").grid(row=fila, column=0, sticky="nw", pady=5); observacion = tk.Text(cuerpo, width=43, height=4); observacion.grid(row=fila, column=1, sticky="w"); fila += 1
        def guardar_movimiento():
            if not empleado.get() or producto_elegido["id"] is None:
                messagebox.showwarning("Validación", "Seleccione empleado y producto.", parent=form); return
            try:
                if tipo == "Entrada":
                    if not destino.get(): raise ValueError("Seleccione la ubicación destino.")
                    registrar_entrada(ids_e[empleado.get()], producto_elegido["id"], ids_u[destino.get()], cantidad.get(), observacion.get("1.0", "end").strip())
                elif tipo == "Salida":
                    if not origen.get(): raise ValueError("Seleccione la ubicación origen.")
                    registrar_salida(ids_e[empleado.get()], producto_elegido["id"], mapa_origen[origen.get()]["id_ubicacion"], cantidad.get(), observacion.get("1.0", "end").strip())
                else:
                    if not origen.get() or not destino.get(): raise ValueError("Seleccione las ubicaciones origen y destino.")
                    registrar_transferencia(ids_e[empleado.get()], producto_elegido["id"], mapa_origen[origen.get()]["id_ubicacion"], ids_u[destino.get()], cantidad.get(), observacion.get("1.0", "end").strip())
            except Exception as exc: _error(exc, form); return
            messagebox.showinfo("Movimiento", f"{tipo} registrada correctamente.", parent=form)
            form.destroy(); actualizar_todo()
        crear_boton_accion(cuerpo, f"Registrar {tipo.lower()}" if tipo != "Transferencia" else "Transferir",
                           guardar_movimiento, "Success").grid(row=fila, column=1, sticky="e", pady=15)
        busca.bind("<KeyRelease>", programar_busqueda_movimiento)
        resultados.bind("<<TreeviewSelect>>", elegir)
        buscar_producto_form()

    descripciones = {"Entrada": "Registrar productos que ingresan al almacén",
                     "Salida": "Registrar productos retirados del inventario",
                     "Transferencia": "Mover productos entre ubicaciones"}
    variantes = {"Entrada": "Success", "Salida": "Danger", "Transferencia": "Primary"}
    for indice, tipo in enumerate(("Entrada", "Salida", "Transferencia")):
        tarjeta = crear_tarjeta(botones_m, 22); tarjeta.grid(row=0, column=indice, sticky="nsew", padx=8)
        ttk.Label(tarjeta, text=tipo, background=COLORES["tarjeta"], foreground=COLORES["texto"],
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(tarjeta, text=descripciones[tipo], background=COLORES["tarjeta"], foreground=COLORES["secundario"],
                  wraplength=270).pack(anchor="w", pady=(7, 25))
        crear_boton_accion(tarjeta, f"Registrar {tipo.lower()}" if tipo != "Transferencia" else "Transferir producto",
                           lambda t=tipo: abrir_movimiento(t), variantes[tipo]).pack(anchor="w")
        botones_m.columnconfigure(indice, weight=1)

    # Pestaña Empleados: la persona frente a la cámara se reconoce directamente.
    encabezado_seccion(pestana_empleados, "Empleados", "Administra personal y reconocimiento facial CNN")
    panel_cnn = ttk.LabelFrame(pestana_empleados, text="RECONOCIMIENTO FACIAL CNN", padding=12)
    panel_cnn.pack(fill="x", pady=(0, 12))
    estado_cnn = tk.StringVar(value="CNN: Comprobando...")
    estado_detector = tk.StringVar(value="Detector facial: Comprobando...")
    estado_dataset = tk.StringVar(value="Dataset: Comprobando...")
    resultado_cnn = tk.StringVar(value="Persona: —    Confianza: —")
    ttk.Label(panel_cnn, textvariable=estado_cnn).grid(row=0, column=0, sticky="w", pady=2)
    ttk.Label(panel_cnn, textvariable=estado_detector).grid(row=1, column=0, sticky="w", pady=2)
    ttk.Label(panel_cnn, textvariable=estado_dataset).grid(row=2, column=0, sticky="w", pady=2)
    ttk.Label(panel_cnn, textvariable=resultado_cnn,
              font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=(8, 2))
    controles_cnn = ttk.Frame(panel_cnn)
    controles_cnn.grid(row=0, column=1, rowspan=4, padx=(30, 0), sticky="e")
    progreso_cnn = ttk.Progressbar(panel_cnn, mode="indeterminate")
    progreso_cnn.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    panel_cnn.columnconfigure(0, weight=1)

    camara_en_uso = {"valor": False}
    entrenamiento_en_curso = {"valor": False}

    def actualizar_estado_cnn():
        try:
            estado = obtener_estado_cnn()
            resumen = resumir_dataset(cargar_dataset())
            estado_detector.set("Detector facial: Listo" if estado["detector_listo"] else "Detector facial: Error")
            estado_dataset.set(f"Dataset: {resumen['imagenes']} imágenes - {resumen['subjects']} personas")
            if estado["modelo_valido"]:
                estado_cnn.set("CNN: Lista para reconocimiento")
                boton_entrenar.configure(text="Reentrenar CNN")
                boton_camara.configure(state="normal")
            elif estado["modelo_existe"]:
                estado_cnn.set("CNN: Modelo anterior no válido; requiere reentrenamiento")
                boton_entrenar.configure(text="Reentrenar CNN")
                boton_camara.configure(state="disabled")
            else:
                estado_cnn.set("CNN: Modelo no entrenado")
                boton_entrenar.configure(text="Entrenar CNN")
                boton_camara.configure(state="disabled")
        except Exception as exc:
            estado_cnn.set(f"CNN: Error - {exc}")
            boton_camara.configure(state="disabled")

    def entrenar_desde_interfaz():
        if entrenamiento_en_curso["valor"] or camara_en_uso["valor"]:
            return
        entrenamiento_en_curso["valor"] = True
        boton_entrenar.configure(state="disabled")
        boton_camara.configure(state="disabled")
        progreso_cnn.start(12)

        def informar(mensaje):
            ventana.after(0, estado_cnn.set, f"CNN: {mensaje}")

        def tarea():
            try:
                resultado = entrenar_modelo_cnn(informar)
                if resultado["modelo_valido"]:
                    texto = (f"CNN: Modelo entrenado correctamente - prueba "
                             f"{resultado['accuracy_prueba']:.1%}")
                else:
                    texto = "CNN: El modelo no aprendió correctamente; no se guardó."
                ventana.after(0, estado_cnn.set, texto)
            except Exception as exc:
                ventana.after(0, estado_cnn.set, f"CNN: Error - {exc}")
            finally:
                entrenamiento_en_curso["valor"] = False
                ventana.after(0, progreso_cnn.stop)
                ventana.after(0, boton_entrenar.configure, {"state": "normal"})
                ventana.after(0, actualizar_estado_cnn)
        threading.Thread(target=tarea, daemon=True).start()

    def reconocer_rostro_interfaz():
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        estado = obtener_estado_cnn()
        if not estado["modelo_valido"]:
            estado_cnn.set("CNN: La CNN todavía no ha sido entrenada. Entrene el modelo primero.")
            return
        camara_en_uso["valor"] = True
        boton_camara.configure(state="disabled")
        boton_entrenar.configure(state="disabled")
        estado_cnn.set("CNN: Cámara activa. Presione ESC o Q para finalizar.")

        def tarea():
            try:
                resultado = reconocer_con_camara(
                    callback_alerta=lambda _alerta: ventana.after(0, cargar_alertas))
                if resultado["estado"] == "RECONOCIDO":
                    texto = (f"{resultado['nombre']} | {resultado['codigo_empleado']} | "
                             f"{resultado['cargo'] or 'Sin cargo'} | Confianza: {resultado['confianza']:.1%}")
                elif resultado["estado"] == "EMPLEADO_INACTIVO":
                    texto = (f"{resultado['nombre']} | Empleado identificado, pero se encuentra inactivo. "
                             f"Confianza: {resultado['confianza']:.1%}")
                elif resultado["estado"] == "SIN_ROSTRO":
                    texto = "SIN ROSTRO: no se detectó ninguna persona."
                else:
                    texto = (f"{resultado['estado']} | Persona desconocida | "
                             f"Confianza: {resultado['confianza']:.1%}")
                ventana.after(0, resultado_cnn.set, texto)
            except Exception as exc:
                ventana.after(0, estado_cnn.set, f"CNN: Error - {exc}")
            finally:
                camara_en_uso["valor"] = False
                ventana.after(0, boton_entrenar.configure, {"state": "normal"})
                ventana.after(0, actualizar_estado_cnn)
        threading.Thread(target=tarea, daemon=True).start()

    boton_entrenar = crear_boton_accion(controles_cnn, "Entrenar CNN", entrenar_desde_interfaz, "Primary")
    boton_entrenar.pack(side="left", padx=4)
    boton_camara = crear_boton_accion(controles_cnn, "Reconocer con cámara",
                                      reconocer_rostro_interfaz, "Success", state="disabled")
    boton_camara.pack(side="left", padx=4)

    panel_relacion = ttk.LabelFrame(pestana_empleados, text="RELACIÓN FACIAL", padding=10)
    panel_relacion.pack(fill="x", pady=(0, 10))
    ttk.Label(panel_relacion, text="Empleado:").grid(row=0, column=0, sticky="w")
    selector_empleado = ttk.Combobox(panel_relacion, state="readonly", width=38)
    selector_empleado.grid(row=0, column=1, padx=6)
    ttk.Label(panel_relacion, text="Etiqueta:").grid(row=0, column=2, sticky="w")
    selector_etiqueta = ttk.Combobox(panel_relacion, state="readonly", width=16)
    selector_etiqueta.grid(row=0, column=3, padx=6)

    cols_e = ("codigo_empleado", "nombre", "cargo", "subject", "estado_facial", "estado_empleado")
    tabla_e = _tabla(pestana_empleados, cols_e,
                     ("Código", "Empleado", "Cargo", "Subject", "Estado facial", "Estado empleado"),
                     (105, 190, 190, 90, 150, 110))
    empleados_tabla = {}
    mapa_selector_empleados = {}
    relaciones_por_empleado = {}
    def cargar_empleados():
        try:
            datos = listar_empleados()
            relaciones = listar_relaciones()
        except Exception as exc: _error(exc, ventana); return
        empleados_tabla.clear(); mapa_selector_empleados.clear(); relaciones_por_empleado.clear()
        tabla_e.delete(*tabla_e.get_children())
        nombres = [f'{e["codigo_empleado"]} - {e["nombres"]} {e["apellidos"]}' for e in datos]
        mapa_selector_empleados.update({nombre: e["id_empleado"] for nombre, e in zip(nombres, datos)})
        selector_empleado["values"] = nombres
        etiquetas_modelo = set(listar_etiquetas_disponibles(incluir_asignadas=True))
        selector_etiqueta["values"] = sorted(etiquetas_modelo)
        for e in datos:
            empleados_tabla[e["id_empleado"]] = e
        for relacion in relaciones:
            relaciones_por_empleado[relacion["id_empleado"]] = relacion
            subject = relacion["etiqueta_modelo"]
            if not subject:
                estado_facial = "Sin rostro registrado"
            elif subject in etiquetas_modelo and obtener_estado_cnn()["modelo_valido"]:
                estado_facial = "Reconocible"
            else:
                estado_facial = "Pendiente de reentrenamiento"
            estado_empleado = "Activo" if relacion["empleado_activo"] else "Inactivo"
            tabla_e.insert("", "end", iid=str(relacion["id_empleado"]),
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

    crear_boton_accion(panel_relacion, "Asignar", asignar_relacion, "Success").grid(row=0, column=4, padx=6)
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
    crear_boton_accion(panel_relacion,"Actualizar relación",actualizar_relacion_ui,"Primary").grid(row=1,column=4,padx=6,pady=(6,0))

    def iniciar_captura_empleado(empleado):
        if camara_en_uso["valor"] or entrenamiento_en_curso["valor"]:
            return
        camara_en_uso["valor"] = True
        boton_camara.configure(state="disabled"); boton_entrenar.configure(state="disabled")
        resultado_cnn.set(f'Registrando rostro de {empleado["nombres"]} {empleado["apellidos"]}...')
        def finalizar(resultado=None, error=None):
            camara_en_uso["valor"] = False
            boton_entrenar.configure(state="normal")
            actualizar_estado_cnn(); cargar_empleados()
            if error:
                _error(error, ventana); return
            if not resultado["completado"]:
                messagebox.showwarning("Registro facial",
                    f'Empleado registrado, pero el rostro no fue completado. Imágenes válidas: {resultado["imagenes_guardadas"]}.',
                    parent=ventana)
                return
            resultado_cnn.set(f'Rostro {resultado["subject"]} registrado con {resultado["imagenes_guardadas"]} imágenes.')
            if messagebox.askyesno("Registro facial",
                    "El rostro fue registrado. Es necesario reentrenar la CNN. ¿Reentrenar ahora?", parent=ventana):
                entrenar_desde_interfaz()
        def tarea():
            try:
                resultado = capturar_rostros_nuevo_empleado(empleado["id_empleado"])
                ventana.after(0, finalizar, resultado, None)
            except Exception as exc:
                ventana.after(0, finalizar, None, exc)
        threading.Thread(target=tarea, daemon=True).start()

    def nuevo_empleado(empleado_actual=None):
        form = tk.Toplevel(ventana); form.title("Editar empleado" if empleado_actual else "Nuevo empleado")
        form.transient(ventana); form.grab_set(); centrar_ventana(form, 520, 380, ventana); cuerpo = ttk.Frame(form, padding=20)
        cuerpo.pack(fill="both", expand=True); entradas = {}
        for fila, campo in enumerate(("Código empleado", "Nombres", "Apellidos", "Cargo")):
            ttk.Label(cuerpo, text=campo + ":").grid(row=fila, column=0, sticky="w", pady=8)
            entradas[campo] = ttk.Entry(cuerpo, width=38); entradas[campo].grid(row=fila, column=1, padx=8, pady=8)
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
        acciones = ttk.Frame(cuerpo); acciones.grid(row=5, column=0, columnspan=2, sticky="e", pady=16)
        crear_boton_accion(acciones, "Cancelar", form.destroy).pack(side="left", padx=4)
        crear_boton_accion(acciones, "Guardar", guardar, "Success").pack(side="left", padx=4)

    crear_boton_accion(panel_relacion, "Nuevo empleado", nuevo_empleado, "Success").grid(row=0, column=5, padx=(18, 4))
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
    def eliminar_rostro_ui():
        empleado=empleado_seleccionado()
        relacion=relaciones_por_empleado.get(empleado["id_empleado"]) if empleado else None
        if not relacion or not relacion["id_rostro"]:
            messagebox.showwarning("Relación facial","El empleado no tiene rostro activo.",parent=ventana); return
        if messagebox.askyesno("Eliminar relación","¿Desea desactivar la relación facial? Las imágenes se conservarán.",parent=ventana):
            try: eliminar_relacion(relacion["id_rostro"]); cargar_empleados()
            except Exception as exc: _error(exc,ventana)
    acciones_empleado=ttk.Frame(pestana_empleados); acciones_empleado.pack(fill="x",pady=(8,0))
    crear_boton_accion(acciones_empleado,"Editar",editar_empleado_ui,"Primary").pack(side="left",padx=3)
    crear_boton_accion(acciones_empleado,"Eliminar",eliminar_empleado_ui,"Danger").pack(side="left",padx=3)
    crear_boton_accion(acciones_empleado,"Registrar rostro",registrar_rostro_ui,"Success").pack(side="left",padx=3)
    crear_boton_accion(acciones_empleado,"Eliminar relación facial",eliminar_rostro_ui,"Danger").pack(side="left",padx=3)

    # Pestaña Análisis IA
    encabezado_seccion(pestana_ia, "Análisis IA", "Predicción de inventario y detección inteligente de anomalías")
    marco_pred = ttk.LabelFrame(pestana_ia, text="Predicción de agotamiento", padding=10)
    marco_pred.pack(fill="x", pady=(0, 10))
    ttk.Label(marco_pred, text="Buscar producto:").grid(row=0, column=0, sticky="w")
    busca_ia = ttk.Entry(marco_pred, width=30); busca_ia.grid(row=0, column=1, padx=5)
    resultados_ia = ttk.Combobox(marco_pred, state="readonly", width=42); resultados_ia.grid(row=0, column=3, padx=5)
    mapa_ia = {}
    busqueda_ia_after = {"id": None}
    resultado_pred = ttk.Label(marco_pred, text="Seleccione un producto para analizar.", justify="left",
                               background=COLORES["azul_claro"], foreground=COLORES["texto"], padding=12)
    resultado_pred.grid(row=1, column=0, columnspan=6, sticky="ew", pady=12)
    ultimo_analisis = {"datos": None}
    def buscar_producto_ia(evento=None):
        try:
            datos = buscar_productos(busca_ia.get())
        except Exception as exc:
            _error(exc, ventana)
            return

        nombres = [
            f'{p["codigo"]} - {p["nombre"]}'
            for p in datos
        ]

        mapa_ia.clear()
        mapa_ia.update({
            nombre: p["id_producto"]
            for nombre, p in zip(nombres, datos)
        })

        resultados_ia["values"] = nombres

        if nombres:
            resultados_ia.set(nombres[0])
        else:
            resultados_ia.set("")

    def programar_busqueda_ia(evento=None):
        if busqueda_ia_after["id"]:
            ventana.after_cancel(busqueda_ia_after["id"])

        busqueda_ia_after["id"] = ventana.after(
            300,
            buscar_producto_ia
        )
    def predecir():
        if resultados_ia.get() not in mapa_ia:
            messagebox.showwarning("Predicción", "Seleccione un producto.", parent=ventana); return
        try: r = predecir_agotamiento(mapa_ia[resultados_ia.get()])
        except Exception as exc: _error(exc, ventana); return
        ultimo_analisis["datos"] = r
        if not r["datos_suficientes"]: texto = f'{r["producto"]} | Stock: {r["stock_actual"]}\n{r["mensaje"]}'
        else:
            promedio = "No calculable" if r["dias_restantes_promedio"] is None else f'{r["dias_restantes_promedio"]:.1f} días'
            regresion = "No calculable" if r["dias_restantes_regresion"] is None else f'{r["dias_restantes_regresion"]:.1f} días'
            texto = (f'{r["producto"]} | Stock actual: {r["stock_actual"]} | Días analizados: {r["dias_analizados"]}\n'
                     f'Consumo promedio: {r["consumo_promedio_diario"]:.2f} unidades/día | Estimación promedio: {promedio}\n'
                     f'Estimación por tendencia: {regresion} | Estado: {r["estado"]}')
        resultado_pred.config(text=texto); cargar_alertas()
    def grafica_consumo():
        if resultados_ia.get() not in mapa_ia:
            messagebox.showwarning("Gráfica", "Seleccione un producto.", parent=ventana); return
        try:
            r = predecir_agotamiento(mapa_ia[resultados_ia.get()])
            if not r["consumo_diario"]: raise ValueError("El producto no tiene consumos históricos.")
            import matplotlib.pyplot as plt
            plt.figure(figsize=(8, 4)); plt.plot([d["fecha"] for d in r["consumo_diario"]], [d["cantidad"] for d in r["consumo_diario"]], marker="o")
            plt.title(f'Consumo diario - {r["producto"]}'); plt.xlabel("Fecha"); plt.ylabel("Cantidad consumida")
            plt.xticks(rotation=35); plt.tight_layout(); plt.show()
        except Exception as exc: _error(exc, ventana)
    busca_ia.bind("<KeyRelease>", programar_busqueda_ia)
    buscar_producto_ia()
    crear_boton_accion(marco_pred, "Predecir", predecir, "Primary").grid(row=0, column=4, padx=3)
    crear_boton_accion(marco_pred, "Gráfica de consumo", grafica_consumo).grid(row=0, column=5, padx=3)
    marco_anom = ttk.LabelFrame(pestana_ia, text="Análisis de anomalías", padding=10); marco_anom.pack(fill="both", expand=True)
    resumen_anom = ttk.Label(marco_anom, text="Movimientos analizados: 0 | Anomalías: 0"); resumen_anom.pack(anchor="w", pady=(0, 6))
    tabla_anom = _tabla(marco_anom, ("fecha", "producto", "empleado", "cantidad", "tipo_anomalia"),
                        ("Fecha", "Producto", "Empleado", "Cantidad", "Tipo de anomalía"), (150, 210, 210, 80, 160))
    def ejecutar_anomalias():
        try: r = analizar_movimientos()
        except Exception as exc: _error(exc, ventana); return
        resumen_anom.config(text=f'Movimientos analizados: {r["movimientos_analizados"]} | Anomalías: {r["anomalias_detectadas"]}')
        tabla_anom.delete(*tabla_anom.get_children())
        for a in r["resultados"]: tabla_anom.insert("", "end", values=tuple(a[c] for c in ("fecha", "producto", "empleado", "cantidad", "tipo_anomalia")))
        if "mensaje" in r: messagebox.showinfo("Análisis", r["mensaje"], parent=ventana)
    crear_boton_accion(marco_anom, "Analizar movimientos", ejecutar_anomalias, "Success").pack(anchor="e", pady=6)

    # Pestaña Agente local de inventario
    encabezado_seccion(pestana_agente, "JARVIS - Asistente Inteligente",
                       "Consulta productos, existencias, ubicaciones y movimientos en lenguaje natural")
    barra_estado = crear_tarjeta(pestana_agente, 10); barra_estado.pack(fill="x", pady=(0, 10))
    estado_agente = tk.StringVar(value="Listo")
    etiqueta_estado = ttk.Label(barra_estado, textvariable=estado_agente, background=COLORES["tarjeta"],
                                font=("Segoe UI", 10, "bold"), foreground=COLORES["verde"])
    etiqueta_estado.pack(side="left")
    ttk.Label(barra_estado,
              text="Ejemplos: ¿Cuántos motores quedan?  ·  ¿Dónde están los tornillos?  ·  ¿Qué productos tienen stock bajo?",
              background=COLORES["tarjeta"], foreground=COLORES["secundario"]).pack(side="right")
    conversacion = ScrolledText(pestana_agente, wrap="word", height=22,
                                font=("Segoe UI", 10), state="disabled",
                                background="#F7FAFC", foreground=COLORES["texto"], relief="flat",
                                highlightthickness=1, highlightbackground=COLORES["borde"], padx=16, pady=14)
    conversacion.pack(fill="both", expand=True)
    conversacion.tag_configure("usuario_titulo", foreground="#245a9b", font=("Segoe UI", 9, "bold"), justify="right")
    conversacion.tag_configure("usuario", background="#dceaff", foreground="#172b4d",
                               justify="right", lmargin1=180, lmargin2=180, rmargin=12, spacing3=12)
    conversacion.tag_configure("agente_titulo", foreground="#28745a", font=("Segoe UI", 9, "bold"))
    conversacion.tag_configure("agente", background="#e6f3ed", foreground="#20352c",
                               lmargin1=12, lmargin2=12, rmargin=180, spacing3=12)
    pie_agente = crear_tarjeta(pestana_agente, 10)
    pie_agente.pack(fill="x", pady=(10, 0))
    texto_pregunta = tk.StringVar()
    pregunta_agente = ttk.Entry(pie_agente, textvariable=texto_pregunta)
    pregunta_agente.pack(side="left", fill="x", expand=True, padx=(0, 6))
    texto_placeholder = "Escribe un mensaje para Jarvis..."
    pregunta_agente.insert(0, texto_placeholder)
    opciones_voz = ttk.Frame(pestana_agente)
    opciones_voz.pack(fill="x", pady=(8, 0))
    responder_con_voz = tk.BooleanVar(value=True)
    modo_asistente = tk.BooleanVar(value=False)
    detener_asistente = threading.Event()
    control_voz = {"escuchando": False, "procesando": False,
                   "hablando": False, "hilo_escucha": None,
                   "hilo_asistente": None, "error": False}

    def escribir_chat(autor, texto):
        conversacion.configure(state="normal")
        prefijo = "usuario" if autor in {"Usuario", "Tú"} else "agente"
        conversacion.insert("end", f"{autor}\n", f"{prefijo}_titulo")
        conversacion.insert("end", f"{texto}\n\n", prefijo)
        conversacion.configure(state="disabled")
        conversacion.see("end")

    colores_estado = {"Listo": "#198754", "Escuchando...": "#0d6efd",
                      "Procesando...": "#d97706", "Hablando...": "#7c3aed",
                      "Error": "#dc3545", "Esperando activación...": "#0d6efd"}

    def actualizar_estado(estado):
        estado_agente.set(estado)
        etiqueta_estado.configure(foreground=colores_estado.get(estado, "#495057"))

    def finalizar_escucha():
        control_voz["escuchando"] = False
        control_voz["procesando"] = False
        control_voz["hilo_escucha"] = None
        if not modo_asistente.get():
            boton_hablar.configure(state="normal", text="Hablar")
        if control_voz["error"]:
            control_voz["error"] = False
            ventana.after(1800, actualizar_estado, "Listo")
        else:
            actualizar_estado("Listo")

    def mostrar_error_voz(error):
        mensaje = str(error)
        control_voz["error"] = True
        actualizar_estado("Error")
        if "modelo" in mensaje.lower() or "micrófono disponible" in mensaje.lower():
            messagebox.showerror("Configuración de voz", mensaje, parent=ventana)
        elif "entender" in mensaje.lower():
            escribir_chat("Jarvis", "No logré entenderte bien. Intenta nuevamente.")
        else:
            escribir_chat("Jarvis", "No escuché ninguna pregunta. Puedes intentarlo otra vez.")

    def reproducir_respuesta(texto):
        if control_voz["hablando"]:
            detener_voz()
        def tarea():
            try:
                hablar(texto)
            except Exception as exc:
                ventana.after(0, mostrar_error_voz, exc)
            finally:
                control_voz["hablando"] = False
                ventana.after(0, boton_detener.configure, {"state": "disabled"})
                ventana.after(0, actualizar_estado, "Listo")
        control_voz["hablando"] = True
        boton_detener.configure(state="normal")
        actualizar_estado("Hablando...")
        threading.Thread(target=tarea, daemon=True).start()

    def enviar_pregunta(evento=None):
        pregunta = pregunta_agente.get().strip()
        if not pregunta or pregunta == texto_placeholder:
            return "break" if evento else None
        pregunta_agente.delete(0, tk.END)
        escribir_chat("Tú", pregunta)
        respuesta = procesar_pregunta(pregunta)
        escribir_chat("Jarvis", respuesta)
        if responder_con_voz.get():
            reproducir_respuesta(respuesta)
        return "break" if evento else None

    def hablar_una_vez():
        hilo = control_voz["hilo_escucha"]
        if (control_voz["escuchando"] or control_voz["procesando"] or
                (hilo is not None and hilo.is_alive()) or modo_asistente.get()):
            return
        control_voz["escuchando"] = True
        boton_hablar.configure(state="disabled", text="Escuchando...")
        actualizar_estado("Escuchando...")
        usar_voz = responder_con_voz.get()
        def tarea():
            try:
                pregunta = escuchar_pregunta()
                ventana.after(0, escribir_chat, "Tú", pregunta)
                control_voz["escuchando"] = False
                control_voz["procesando"] = True
                ventana.after(0, actualizar_estado, "Procesando...")
                respuesta = procesar_pregunta(pregunta)
                ventana.after(0, escribir_chat, "Jarvis", respuesta)
                if usar_voz:
                    control_voz["hablando"] = True
                    ventana.after(0, boton_detener.configure, {"state": "normal"})
                    ventana.after(0, actualizar_estado, "Hablando...")
                    hablar(respuesta)
            except Exception as exc:
                ventana.after(0, mostrar_error_voz, exc)
            finally:
                control_voz["hablando"] = False
                ventana.after(0, boton_detener.configure, {"state": "disabled"})
                ventana.after(0, finalizar_escucha)
        hilo_nuevo = threading.Thread(target=tarea, daemon=True)
        control_voz["hilo_escucha"] = hilo_nuevo
        hilo_nuevo.start()

    def ciclo_asistente(usar_voz):
        try:
            while not detener_asistente.is_set():
                ventana.after(0, actualizar_estado, "Esperando activación...")
                try:
                    activacion = escuchar_pregunta()
                except RuntimeError as exc:
                    if detener_asistente.is_set():
                        break
                    ventana.after(0, mostrar_error_voz, exc)
                    break
                if detener_asistente.is_set():
                    break
                texto_activacion = activacion.lower()
                if not any(frase in texto_activacion for frase in
                           (FRASE_ACTIVACION, "jarvis", "jarbis", "yarvis", "oye jarvis", "hey jarvis",
                            "hola inventario", "oye inventario", "hey inventario")):
                    continue
                bienvenida = "Hola, amigo. ¿En qué puedo ayudarte?"
                ventana.after(0, escribir_chat, "Jarvis", bienvenida)
                if usar_voz:
                    hablar(bienvenida)
                ventana.after(0, actualizar_estado, "Escuchando...")
                pregunta = escuchar_pregunta()
                if pregunta.lower().strip() in {"cancelar", "nada"}:
                    ventana.after(0, escribir_chat, "Jarvis", "Consulta cancelada.")
                    continue
                ventana.after(0, escribir_chat, "Tú", pregunta)
                ventana.after(0, actualizar_estado, "Procesando...")
                respuesta = procesar_pregunta(pregunta)
                ventana.after(0, escribir_chat, "Jarvis", respuesta)
                if usar_voz:
                    hablar(respuesta)
        except Exception as exc:
            ventana.after(0, mostrar_error_voz, exc)
        finally:
            control_voz["hilo_asistente"] = None
            ventana.after(0, modo_asistente.set, False)
            ventana.after(0, boton_hablar.configure, {"state": "normal", "text": "Hablar"})
            ventana.after(0, actualizar_estado, "Listo")

    def cambiar_modo_asistente():
        if modo_asistente.get():
            hilo = control_voz["hilo_asistente"]
            if hilo is not None and hilo.is_alive():
                return
            detener_asistente.clear()
            boton_hablar.configure(state="disabled")
            usar_voz = responder_con_voz.get()
            hilo = threading.Thread(target=ciclo_asistente, args=(usar_voz,), daemon=True)
            control_voz["hilo_asistente"] = hilo
            hilo.start()
        else:
            detener_asistente.set()
            boton_hablar.configure(state="normal", text="Hablar")
            actualizar_estado("Listo")

    def limpiar_chat():
        conversacion.configure(state="normal")
        conversacion.delete("1.0", tk.END)
        conversacion.configure(state="disabled")
        reiniciar_contexto()
        detener_voz()
        actualizar_estado("Listo")
        pregunta_agente.focus_set()

    boton_enviar = crear_boton_accion(pie_agente, "Enviar", enviar_pregunta, "Success", state="disabled")
    boton_enviar.pack(side="left")
    crear_boton_accion(pie_agente, "Reiniciar contexto", limpiar_chat).pack(side="left", padx=(6, 0))
    boton_hablar = crear_boton_accion(opciones_voz, "Hablar", hablar_una_vez, "Primary")
    boton_hablar.pack(side="left")
    boton_detener = crear_boton_accion(opciones_voz, "Detener voz", detener_voz, "Danger", state="disabled")
    boton_detener.pack(side="left", padx=6)
    ttk.Checkbutton(opciones_voz, text="Responder con voz",
                    variable=responder_con_voz).pack(side="left", padx=(12, 4))
    ttk.Checkbutton(opciones_voz, text="Modo asistente",
                    variable=modo_asistente,
                    command=cambiar_modo_asistente).pack(side="left", padx=4)
    def gestionar_placeholder(evento=None):
        if pregunta_agente.focus_get() == pregunta_agente and pregunta_agente.get() == texto_placeholder:
            pregunta_agente.delete(0, tk.END)
        elif pregunta_agente.focus_get() != pregunta_agente and not pregunta_agente.get().strip():
            pregunta_agente.insert(0, texto_placeholder)

    pregunta_agente.bind("<FocusIn>", gestionar_placeholder)
    pregunta_agente.bind("<FocusOut>", gestionar_placeholder)
    pregunta_agente.bind("<Return>", enviar_pregunta)
    texto_pregunta.trace_add("write", lambda *_: boton_enviar.configure(
        state="normal" if texto_pregunta.get().strip() and texto_pregunta.get() != texto_placeholder else "disabled"))
    escribir_chat("Jarvis", "Hola. Soy Jarvis, tu asistente inteligente de inventario. ¿Qué necesitas revisar?")

    def actualizar_todo():
        cargar_productos(); cargar_historial(); cargar_alertas(); cargar_empleados()

    cargar_productos(); cargar_historial(); cargar_alertas(); cargar_empleados()
    actualizar_estado_cnn()
    def cerrar_aplicacion():
        detener_asistente.set()
        detener_reconocimiento()
        cerrar_audio()
        ventana.destroy()
    ventana.protocol("WM_DELETE_WINDOW", cerrar_aplicacion)
    ventana.mainloop()
