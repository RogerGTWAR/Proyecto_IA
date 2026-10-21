"""Plan, respaldo y ventanas de captura manual exclusivos de CNN."""
from core.paths import PROJECT_ROOT
from datetime import datetime
from pathlib import Path
import hashlib
import json
import threading
import zipfile
import tkinter as tk
from tkinter import ttk

BASE=PROJECT_ROOT
CONDICIONES=(
    ('frontal','Frontal',('Mira al frente.','Expresión neutra.','Pequeñas variaciones naturales.')),
    ('angulos','Variación lateral',('Mira ligeramente a la izquierda.','Mira ligeramente a la derecha.')),
    ('distancia','Distancia',('Aléjate ligeramente.','Acércate ligeramente.')),
    ('iluminacion','Variación independiente',('Realiza una captura distinta.','Varía suavemente pose e iluminación.','No reutilices imágenes anteriores.')),
)
MIN_IMAGENES=4
OBJETIVO_IMAGENES=5


def plan_subject(subject,informe):
    if subject not in informe.get('subjects_activos_sql',[]):
        raise ValueError('El empleado necesita una etiqueta facial activa y validada en SQL.')
    n=min(4,informe.get('sesiones_por_subject',{}).get(subject,0))
    if n>=4:return {'subject':subject,'completadas':n,'numero':None}
    condicion,titulo,instrucciones=CONDICIONES[n]
    return {'subject':subject,'completadas':n,'numero':n+1,'condicion':condicion,
            'titulo':titulo,'instrucciones':instrucciones}


def respaldar_imagenes(rutas=None,destino=None):
    """Respaldo verificable por contenido; nunca mueve ni modifica las fuentes."""
    if rutas is None:
        from ai.facial.dataset_rostros import RUTA_DATASET,EXTENSIONES
        from ai.facial.pipeline_facial import DIRECTORIO
        rutas=[]
        for carpeta in (RUTA_DATASET,DIRECTORIO/'muestras',BASE/'modelos/cnn_muestras'):
            rutas.extend(p for p in Path(carpeta).rglob('*') if p.is_file() and (p.suffix.lower() in EXTENSIONES or p.suffix.lower()=='.json'))
    rutas=sorted(set(Path(p).resolve() for p in rutas))
    entradas={str(i)+'/'+p.name:(p,hashlib.sha256(p.read_bytes()).hexdigest()) for i,p in enumerate(rutas)}
    manifest={k:{'origen':str(p),'sha256':h} for k,(p,h) in entradas.items()}
    firma=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:20]
    destino=Path(destino or BASE/'backups/cnn');destino.mkdir(parents=True,exist_ok=True)
    archivo=destino/f'imagenes_{firma}.zip'
    if not archivo.exists():
        parcial=archivo.with_suffix('.zip.part')
        try:
            with zipfile.ZipFile(parcial,'w',zipfile.ZIP_DEFLATED) as z:
                for k,(p,h) in entradas.items():z.write(p,k)
                z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            parcial.replace(archivo)
        finally:parcial.unlink(missing_ok=True)
    with zipfile.ZipFile(archivo) as z:
        if json.loads(z.read('manifest.json'))!=manifest or any(hashlib.sha256(z.read(k)).hexdigest()!=v['sha256'] for k,v in manifest.items()):
            raise ValueError('No se pudo verificar el respaldo de imágenes CNN.')
    return {'archivo':str(archivo),'archivos':len(manifest),'verificado':True}


def abrir_plan(padre,empleado,plan,iniciar,prioridad=False):
    ventana=tk.Toplevel(padre);ventana.title('Capturar sesión CNN');ventana.transient(padre)
    ventana.geometry('570x490');ventana.resizable(False,False)
    panel=ttk.Frame(ventana,padding=24);panel.pack(fill='both',expand=True)
    nombre=f"{empleado['nombres']} {empleado['apellidos']}"
    for texto in (f'Empleado: {nombre}',f"Subject: {plan['subject']}",
                  f"Sesiones completadas: {plan['completadas']} / 4"):
        ttk.Label(panel,text=texto,font=('Segoe UI',11)).pack(anchor='w',pady=4)
    if plan['numero'] is None:
        ttk.Label(panel,text='Cuatro sesiones completas. Consulte Validar dataset.',wraplength=510).pack(pady=20)
        ttk.Button(panel,text='Cerrar',command=ventana.destroy).pack();return ventana
    ttk.Label(panel,text=f"Próxima sesión: Sesión {plan['numero']} · {plan['titulo']}",font=('Segoe UI',12,'bold')).pack(anchor='w',pady=12)
    ttk.Label(panel,text='\n'.join(plan['instrucciones']),wraplength=510).pack(anchor='w')
    ttk.Label(panel,text='Captura cada foto con el botón. Objetivo: 5 imágenes; mínimo: 4.\nUna sesión nueva requiere una captura y condiciones realmente distintas.',wraplength=510).pack(anchor='w',pady=12)
    if prioridad:ttk.Label(panel,text='Prioridad: confusión histórica. Verifica cuidadosamente la persona y la etiqueta.',wraplength=510).pack(anchor='w',pady=4)
    confirmado=tk.BooleanVar(value=False)
    boton=ttk.Button(panel,text='Iniciar captura',state='disabled')
    ttk.Checkbutton(panel,text='Confirmo que se capturará al empleado indicado.',variable=confirmado,
        command=lambda:boton.configure(state='normal' if confirmado.get() else 'disabled')).pack(anchor='w',pady=12)
    def comenzar():ventana.destroy();iniciar(plan)
    boton.configure(command=comenzar);boton.pack(anchor='e');return ventana


from ui.ventanas_camara import VentanaCamara


class VentanaSesionCNN(VentanaCamara):
    """Los botones emiten eventos; el worker no toca widgets de Tkinter."""
    def __init__(self,padre,persona,al_cerrar,plan):
        super().__init__(padre,'registro',persona,al_cerrar)
        self.plan_cnn=plan;self.condicion_cnn=plan['condicion']
        self.solicitud_foto=threading.Event();self.fin_sesion=threading.Event()
        self.ventana.title(f"Sesión {plan['numero']} de 4 · {plan['subject']} · CNN")
        self.variables['persona'].set(persona+' · '+plan['subject'])
        self.variables['contador'].set(f"Sesión {plan['numero']} de 4 · 0 / 5")
        self.variables['instruccion'].set(plan['instrucciones'][0])
        self.variables['estado'].set('Pulsa Capturar imagen después de variar la pose.')
        self.variables['guardadas']=tk.StringVar(value='0')
        botones=ttk.Frame(self.ventana,padding=(16,4));botones.pack(fill='x',after=self.ventana.winfo_children()[0])
        ttk.Button(botones,text='Capturar imagen',command=self.solicitud_foto.set).pack(side='left',padx=6)
        self.boton_fin=ttk.Button(botones,text='Completar sesión (mínimo 4)',state='disabled',command=self.fin_sesion.set)
        self.boton_fin.pack(side='left',padx=6)
        self.al_info=lambda datos:self.boton_fin.configure(state='normal' if int(datos.get('guardadas',0))>=MIN_IMAGENES else 'disabled')
