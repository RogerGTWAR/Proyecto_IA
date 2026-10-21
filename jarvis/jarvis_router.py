"""Orquestador compartido: interpretar → resolver → planificar → ejecutar → responder.

Los dominios y operadores se reconocen por separado. Una referencia a empleado
no convierte una consulta relacional de movimientos en una búsqueda de personas.
"""
from dataclasses import dataclass,field,asdict
from collections import defaultdict
from decimal import Decimal
from datetime import datetime,timedelta
from pathlib import Path
import logging
import re
import time
from jarvis.nlp_jarvis import normalizar_texto,extraer_filtros,IntentRouter,PALABRAS_FUNCIONALES,PALABRAS_CONSULTA
from core.formato_numerico import format_numero
from jarvis import herramientas_jarvis as servicios
from jarvis import jarvis_consultas as datos


@dataclass
class Plan:
    dominio:str
    operacion:str='listar'
    filtros:dict=field(default_factory=dict)
    limite:int=5
    orden:str='desc'
    entidades:dict=field(default_factory=dict)
    texto:str=''


# Prioridad explícita de dominios; no se extraen nombres desde estas señales.
DOMINIOS=(
    ('sistema',r'\b(?:todo esta funcionando|todo funciona|estan los servicios)\b'),
    ('sistema',r'\berrores relevantes\b'),
    ('reportes',r'\breporte|\binforme|\bexporta'),
    ('conteos',r'\bconteos?\b|\bconteo fisico\b'),
    ('vigilancia',r'\bintrusion|\bvigilancia|\bdeteccion(?:es)?\b|\bpersona detectada\b'),
    ('facial',r'\breconocid[oa]s?\b|\bresultado de reconocimiento|\bdesconocid[oa]s?\b'),
    ('prediccion',r'\bproductos?\b.*\b(?:mayor riesgo|en riesgo|riesgo de agotarse)\b'),
    ('anomalias',r'\banomalias?\b|\binusuales?\b|\braros?\b|\bextranos?\b|\banormal'),
    ('alertas',r'\balertas?\b|\bavisos?\b'),
    ('movimientos',r'\bmovimientos?\b|\bmovid[oa]s?\b|\bentradas?\b|\bsalidas?\b|\btransferencias?\b|\bajustes?\b|\bretiros?\b|\bmovio\b|\bmovieron\b|\bentro\b'),
    ('empleados',r'\bemplead[oa]s?\b'),
    ('ubicaciones',r'\bubicacion(?:es)?\b'),
    ('productos',r'\bproductos?\b|\bstock\b|\bcategorias?\b'),
)
OPERADORES=(
    ('comparar',r'\b(?:compara|comparar|comparacion)\b|\b(?:o|vs)\b.*\b(?:mas|menos)\b'),
    ('promedio',r'\bpromedio\b'),
    ('contar',r'\bcuant[oa]s\b|\bnumero de\b'),
    ('sumar',r'\b(?:cantidad total|total movid[oa]|stock total|total de unidades|unidades en total)\b'),
    ('primero',r'\b(?:primer[oa]?s?|mas antigu[oa])\b'),
    ('ultimo',r'\b(?:ultim[oa]s?|mas reciente|recientemente)\b'),
    ('maximo',r'\b(?:mas|mayor|maximo)\b'),
    ('minimo',r'\b(?:menos|menor|minimo)\b'),
    ('explicar',r'\b(?:por que|explica|explicame|motivo)\b'),
)
FECHA_ALTA=r'\b(?:agregad[oa]|registrad[oa]|cread[oa]|incorporad[oa]|en ser agregado)\b'
REFERENCIA=r'\b(?:ese|esa|este|mismo|misma|su|sus|el|ella|ahi|tiene|hizo|movio)\b'
SOCIAL=IntentRouter()
GRAMATICA_CONSULTA=set('quien quienes cual cuales fue fueron ser hacer hizo hicieron ha han hecho movio movieron movida movido movidas movidos agregado agregada agregados registrado registrada registrados reciente recientes primero primera primeros primeras ultimo ultima ultimos ultimas mas menos mayor menor antiguo antigua cuantos cuantas total promedio contando antiguas antiguos hubo hoy ayer esta este semana mes dias entre antes despues fecha fechas empleado empleados alerta alertas critica criticas critico criticos anomalia anomalias producto productos movimiento movimientos todos todas entrada entradas salida salidas transferencia transferencias ajustes ajuste pendientes activas activos hay'.split())


def tiene_mencion(texto):
    """Separar términos de consulta de posibles valores antes de leer catálogos."""
    ignoradas=PALABRAS_FUNCIONALES|PALABRAS_CONSULTA|GRAMATICA_CONSULTA
    return any(t not in ignoradas and not re.fullmatch(r'[\d-]+',t) for t in texto.split())


def respuesta(texto,intencion,filas=None,**extra):
    return dict(respuesta=texto,intencion=intencion,datos=filas if filas is not None else {},**extra)


def interpretar(texto,ctx):
    t=normalizar_texto(texto)
    t=re.sub(r'^(?:hola\s+)?jarvis\s*','',t)
    if re.search(r'\b(?:led|luz)\b',t) and not re.search(r'\b(?:encend|enciend|prend|apag)\w*',t):
        return Plan('productos','led',texto=t)
    # Estado es una consulta, no una intención de encender/detener un servicio.
    if re.search(r'\b(?:funciona|funcionando|estado|disponible|activa|activo|servicios)\b',t) and re.search(r'\b(?:telegram|camara|sql|sistema|jarvis|sface|arduino|vigilancia|servicios|reconocimiento facial|tts|vosk|yolo|prediccion|anomalias)\b',t):
        if not re.search(r'\b(?:inicia|iniciar|deten|detener|enciende|apaga)\b',t):return Plan('sistema','estado',texto=t)
    dominio=next((d for d,p in DOMINIOS if re.search(p,t)),None)
    if dominio not in ('reportes','conteos','vigilancia','facial','sistema','prediccion') and re.search(r'\b(?:agotarse|agotaria|agotara|riesgo|prediccion|durara|rostro|subject|sujeto|reconocidas)\b',t):return None
    if re.search(FECHA_ALTA,t) and not dominio:return Plan('aclaracion','dominio',texto=t)
    if not dominio and ctx.get('dominio_pendiente') and t in ('producto','productos','empleado','empleados'):
        dominio=t if t.endswith('s') else t+'s'
    if not dominio and re.search(r'\b(?:lo hizo|que movio|ese movimiento)\b',t):dominio='movimientos'
    if not dominio and ctx.get('ultimo_dominio')=='producto' and re.search(r'\b(?:mas|menos|mayor|menor)\b',t):dominio='productos'
    if not dominio and re.search(r'\b(?:por que|explica|explicame)\b',t) and ctx.get('ultimo_dominio')=='anomalia':
        # La implementación existente conserva su selección y explicación.
        if not ctx.get('ultima_anomalia'):return None
        return Plan('anomalias','explicar',texto=t)
    if not dominio:return None
    op=next((o for o,p in OPERADORES if re.search(p,t)),'listar')
    if re.search(r'\b(?:o|vs|entre)\b',t) and re.search(r'\b(?:mas|menos|mayor|menor)\b',t):op='comparar'
    if dominio=='ubicaciones' and re.search(r'\bstock por ubicacion',t):op='stock'
    if dominio=='ubicaciones' and op not in ('maximo','minimo','contar','stock'):return None
    if dominio=='productos' and re.search(r'\b(?:por categoria|categoria tiene mas|categoria tiene mayor)\b',t):op='agrupar'
    if dominio=='productos' and op=='listar' and 'categoria' in t and re.search(r'\b(?:productos|que hay)\b',t):return None
    if dominio=='productos' and re.search(r'\b(?:precio|categoria|detalle|informacion)\b',t) and op=='listar' and not re.search(r'\b(?:categorias|por categoria|productos de)\b',t):op='detalle'
    if dominio=='empleados' and op=='listar' and re.search(r'\b(?:rostro|subject|cargo)\b',t):return None
    if dominio=='movimientos' and re.search(r'\bquien\b',t) and op=='listar':op='ultimo'
    if dominio=='productos' and op=='listar' and not re.search(r'\blista|\bcatalogo|\bbusca|\bdetalle|\bprecio|\bcategoria',t):return None
    # Estas capacidades ya resuelven planes compuestos y contexto espacial.
    if dominio=='productos' and op=='listar' and re.search(r'\bdonde|\bubicacion|\bquedan|\bcuanto|\briesgo|\bagotad|\bdurara|\bminimo',t):return None
    if dominio=='movimientos' and re.search(r'\b(?:consumiendo mas|consumen mas|mayor consumo|mas salidas|retiro|retiro el)\b',t):return None
    if dominio=='facial' and re.search(r'\b(?:inicia|iniciar|abre|abrir)\b',t):return None
    if dominio=='anomalias' and op=='listar' and not re.search(r'\b(?:ultim|primer|de |del |critic)',t):return None
    if dominio=='productos' and op in ('maximo','minimo') and not re.search(r'\bstock|\bunidades|\bcategoria',t) and ctx.get('ultimo_dominio')!='producto':return None
    f=extraer_filtros(t)
    if dominio=='facial' and re.search(r'\b(?:desconocid|no reconocid)',t):f['identidad']='desconocida'
    if re.search(r'\b(?:entro|entraron)\b',t):f['tipo_movimiento']='Entrada'
    # Las fechas de intervalo tienen prioridad sobre una fecha aislada.
    fechas=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',t)
    if len(fechas)==2 and 'entre' in t:
        desde,hasta=(datetime.fromisoformat(x).date() for x in fechas)
        if desde>hasta:raise ValueError('La fecha inicial debe ser anterior a la final.')
        f.update(fecha_desde=str(desde),fecha_hasta=str(hasta))
    elif fechas and re.search(r'\b(?:antes de|despues de)\b',t):
        fecha=datetime.fromisoformat(fechas[0]).date();f.pop('fecha_desde',None);f.pop('fecha_hasta',None)
        f['fecha_hasta' if 'antes de' in t else 'fecha_desde']=str(fecha+timedelta(days=-1 if 'antes de' in t else 1))
    if re.search(r'\bajustes?\b',t):f['tipo_movimiento']='Ajuste'
    if re.search(r'\b(?:criticas?|criticos?)\b',t):f['nivel']='CRÍTICA'
    n=re.search(r'\b(?:ultim[oa]s?|primer[oa]s?)\s+(\d+)\b',t)
    if n and 'dias' in t and op=='ultimo':op='listar'
    limite=int(n.group(1)) if n and 'dias' not in t else 1 if op in ('ultimo','primero') else 5
    if not 1<=limite<=50:raise ValueError('Solicita entre 1 y 50 resultados.')
    return Plan(dominio,op,f,limite,'asc' if op=='primero' else 'desc',texto=t)


def coincidencias(texto,catalogo,tipo):
    """Solo menciones léxicas del catálogo; las palabras de la pregunta no son nombres."""
    codigo='codigo_empleado' if tipo=='empleado' else 'codigo'
    completos=[];parciales=[]
    for fila in catalogo:
        cod=normalizar_texto(fila.get(codigo,''));nombre=normalizar_texto(fila.get('nombre',''))
        if (cod and re.search(r'(?<!\w)'+re.escape(cod)+r'(?!\w)',texto)) or (nombre and re.search(r'(?<!\w)'+re.escape(nombre)+r'(?!\w)',texto)):
            completos.append(fila);continue
        tokens=[p for p in nombre.split() if len(p)>2 and p not in ('del','los','las','para','con','sin')]
        if any(re.search(r'\b'+re.escape(p)+r'\b',texto) for p in tokens):parciales.append(fila)
    return completos or parciales


def _aclarar(plan,ctx,tipo,candidatos):
    ctx['plan_orquestador']=asdict(plan)
    ctx.esperar([plan.dominio+'.'+plan.operacion],tipo,candidatos)
    nombres=[f.get('nombre') or f.get('codigo_ubicacion') for f in candidatos]
    return respuesta('No estoy seguro de cuál quieres. Encontré:\n'+'\n'.join(f'{i+1}. {n}' for i,n in enumerate(nombres)),
        'aclaracion',clarification=True)


def resolver(plan,ctx):
    t=plan.texto
    if plan.operacion=='explicar':return None
    if ctx.get('plan_orquestador') and ctx.get('candidatos_ambiguos'):
        candidatos=ctx['candidatos_ambiguos'];m=re.fullmatch(r'(?:el |la |opcion )?(\d+)',t)
        elegidos=[candidatos[int(m.group(1))-1]] if m and 0<int(m.group(1))<=len(candidatos) else coincidencias(t,candidatos,ctx['tipo_candidatos'])
        if len(elegidos)==1:
            tipo=ctx['tipo_candidatos'];plan.entidades[tipo]=elegidos[0]
            ctx.completar();ctx['plan_orquestador']=None
    for tipo,fn in (('producto',lambda:servicios.datos_inventario()),('empleado',lambda:datos.empleados({}))):
        # Una consulta global de empleados no requiere consultar el catálogo de productos.
        if tipo in plan.entidades:continue
        necesita=(tipo=='producto' and plan.dominio in ('productos','movimientos','anomalias','alertas')) or (tipo=='empleado' and plan.dominio in ('empleados','movimientos','anomalias'))
        if not necesita:continue
        if not tiene_mencion(t):continue
        # Consultas temporales de altas y conteos globales no buscan una entidad.
        if plan.dominio==tipo+'s' and (plan.operacion in ('contar','ultimo','primero') and (re.search(FECHA_ALTA,t) or tipo=='empleado')):continue
        filas=coincidencias(t,fn(),tipo)
        if len(filas)>1 and plan.operacion not in ('comparar',):return _aclarar(plan,ctx,tipo,filas)
        if len(filas)==1:plan.entidades[tipo]=filas[0]
        elif len(filas)>1:plan.entidades[tipo+'s']=filas
    if plan.dominio in ('movimientos','anomalias','alertas') and not plan.entidades:
        codigos=re.findall(r'\b[a-z]{2,8}-\d+\b',t)
        explicita=re.search(r'\b(?:de|del)\s+(?:el\s+)?(?:producto|empleado)\b',t)
        if codigos or explicita or (tiene_mencion(t) and re.search(r'\b(?:de|del|por)\b',t)):
            tipo='empleado' if any(c.startswith('emp-') for c in codigos) or 'empleado' in (explicita.group(0) if explicita else '') else 'producto'
            ctx['plan_orquestador']=asdict(plan);ctx.esperar([plan.dominio+'.'+plan.operacion],tipo)
            return respuesta('No encontré ese '+tipo+'. Indica su nombre o código registrado.','aclaracion',clarification=True)
    if re.search(REFERENCIA,t):
        if 'producto' not in plan.entidades and ctx.get('ultimo_producto_id') and not re.search(r'\b(?:hoy|ayer|esta semana|este mes|todos|todas)\b',t):
            if re.search(r'\b(?:su|ese producto|el mismo)\b',t):plan.entidades['producto']={'id_producto':ctx['ultimo_producto_id']}
        if re.search(r'\b(?:ese empleado|el|ella)\b',t) and ctx.get('ultimo_empleado_id') and not plan.entidades.get('empleado'):
            if re.search(r'\b(?:ese empleado|de el|de ella)\b',t):plan.entidades['empleado']={'id_empleado':ctx['ultimo_empleado_id']}
    for tipo,campo in (('producto','id_producto'),('empleado','id_empleado')):
        if plan.entidades.get(tipo):plan.filtros[tipo]=plan.entidades[tipo][campo]
    if plan.dominio in ('productos','empleados') and re.search(r'\b(?:busca|buscar|consulta|consultar)\b',t) and 'listar' not in t:
        tipo='producto' if plan.dominio=='productos' else 'empleado'
        if not plan.entidades.get(tipo):
            ctx['plan_orquestador']=asdict(plan);ctx.esperar([plan.dominio+'.'+plan.operacion],tipo)
            return respuesta('¿Qué '+tipo+' quieres consultar? Indica su nombre o código registrado.','aclaracion',clarification=True)
    return None


def _fecha_fila(f,dominio):return datos.fecha(f.get(datos.FECHAS[dominio]))


def _filtrar(filas,plan):
    f=plan.filtros
    for tipo,campo in (('producto','id_producto'),('empleado','id_empleado')):
        if f.get(tipo):filas=[r for r in filas if r.get(campo)==f[tipo]]
    if f.get('nivel'):
        equivalentes={'critico':'critica','alto':'alta','medio':'media','bajo':'baja'}
        canon=lambda v:equivalentes.get(normalizar_texto(v),normalizar_texto(v))
        filas=[r for r in filas if canon(r.get('nivel'))==canon(f['nivel'])]
    for clave,comparar in (('fecha_desde',lambda a,b:a>=b),('fecha_hasta',lambda a,b:a<=b)):
        if f.get(clave):filas=[r for r in filas if _fecha_fila(r,plan.dominio) and comparar(str(_fecha_fila(r,plan.dominio).date()),f[clave])]
    return filas


def _recordar(ctx,plan,filas):
    ctx['ultimo_plan_orquestador']=asdict(plan)
    ctx['ultimo_dominio']={'movimientos':'movimiento','anomalias':'anomalia','empleados':'empleado','productos':'producto'}.get(plan.dominio,plan.dominio)
    ctx['ultimos_resultados']=filas[:50];ctx['ultimo_resultado']={'dominio':ctx['ultimo_dominio'],'datos':filas}
    if len(filas)==1:
        fila=filas[0]
        if fila.get('id_producto'):
            nombre=fila.get('producto') or (fila.get('nombre') if plan.dominio=='productos' else None)
            ctx.recordar_producto({'id_producto':fila['id_producto'],'nombre':nombre or ctx.get('ultimo_producto_nombre')})
        if fila.get('id_empleado'):
            ctx.update(ultimo_empleado_id=fila['id_empleado'],ultimo_empleado_nombre=fila.get('empleado') or fila.get('nombre'))
        clave={'movimientos':'ultimo_movimiento','anomalias':'ultima_anomalia','alertas':'ultima_alerta','empleados':'ultimo_empleado'}.get(plan.dominio)
        if clave:ctx[clave]=dict(fila)
    ctx['referencias'][plan.dominio]=filas[:50]


def _linea(f,dominio):
    if dominio=='movimientos':
        fecha=datos.fecha(f.get('fecha_movimiento'));cuando=fecha.strftime('%d/%m/%Y a las %H:%M') if fecha else 'fecha no informada'
        return f"{f.get('empleado','Responsable no informado')}: {f['tipo_movimiento']} de {format_numero(f['cantidad'])} {f.get('unidad_medida') or 'unidades'} de {f['producto']}, {cuando} (movimiento #{f['id_movimiento']})."
    if dominio=='empleados':return f"{f['nombre']} ({f['codigo_empleado']})"+(f", registrado el {datos.fecha(f['fecha_creacion']):%d/%m/%Y %H:%M}." if datos.fecha(f.get('fecha_creacion')) else '.')
    if dominio=='productos':return f"{f['nombre']} ({f['codigo']}): {format_numero(f['stock_actual'])} {f.get('unidad_medida','unidades')}."
    if dominio=='anomalias':return f"Anomalía #{f['id_anomalia']}: {f['producto']}, nivel {f['nivel']}. {f['motivo']}"
    if dominio=='alertas':return f"Alerta #{f['id_alerta']}: {f['tipo']}, nivel {f['nivel']}. {f['mensaje']}"
    if dominio=='conteos':return f"Conteo #{f['id_conteo']}: {f['estado']}, {f.get('codigo_ubicacion','ubicación no informada')}."
    if dominio=='facial':return f"{f.get('nombre') or 'Identidad no informada'}, {f.get('fecha')}; motor {f.get('motor_facial') or 'no informado'}."
    return f"{f.get('fecha')}: {f.get('identidad') or f.get('mensaje') or 'Detección registrada'}; cámara {f.get('camara','no informada')}, zona {f.get('zona','no informada')}."


def ejecutar_consulta(plan,ctx):
    dominio=plan.dominio;op=plan.operacion;t=plan.texto
    ctx['ultimo_plan_orquestador']=asdict(plan)
    ctx['ultimo_dominio']={'movimientos':'movimiento','anomalias':'anomalia','empleados':'empleado','productos':'producto'}.get(dominio,dominio)
    if dominio=='movimientos':
        ctx.update(filtros_movimientos=dict(plan.filtros),producto_movimientos=plan.filtros.get('producto'),
                   empleado_movimientos=plan.filtros.get('empleado'))
    if plan.entidades.get('producto',{}).get('nombre'):
        ctx.recordar_producto(plan.entidades['producto'])
    if dominio=='sistema':
        estados=servicios.ejecutar('sistema_estado')
        componentes={'telegram':'Telegram','camara':'Cámara','vigilancia':'YOLO','sql':'SQL','sface':'SFace','reconocimiento facial':'SFace','arduino':'Arduino','tts':'TTS','vosk':'Vosk','yolo':'YOLO','prediccion':'Predicción','anomalias':'Anomalías'}
        elegidos=[v for k,v in componentes.items() if re.search(r'\b'+k+r'\b',t)]
        return respuesta('. '.join(k+': '+str(estados[k]) for k in dict.fromkeys(elegidos or estados) if k in estados)+'.','estado_sistema',estados)
    if dominio=='reportes':
        tipos={'movimiento':'Movimientos','anomalia':'Anomalías','alerta':'Alertas','prediccion':'Predicción de stock','agotado':'Agotados'}
        tipo=next((v for k,v in tipos.items() if k in t),'Inventario actual')
        formato='Excel' if 'excel' in t else 'PDF' if 'pdf' in t or re.search(r'\b(?:genera|generar|exporta|exportar)\b',t) else None
        r,archivo=servicios.ejecutar('reporte_generar',{'tipo':tipo,'filtros':plan.filtros,'formato':formato})
        return respuesta((f'Reporte exportado: {archivo}.' if archivo else f'Vista previa de {tipo.lower()}: {len(r["filas"])} registros.'),
            'generar_reporte',r,archivo=archivo)
    if dominio=='ubicaciones':
        from inventory.mapa_almacen import productos_ubicacion
        us=datos.leer('ubicaciones',{})
        if plan.operacion=='contar':return respuesta(f'Hay {len(us)} ubicaciones activas.','ubicaciones_contar',us)
        if plan.operacion=='stock':
            lineas=[]
            for u in us:
                grupos=datos.agrupar_cantidades(productos_ubicacion(u['id_ubicacion']),'unidad_medida','cantidad')
                lineas.append(u['codigo_ubicacion']+': '+('; '.join(f'{format_numero(v)} {unidad}' for (unidad,_),v in grupos.items()) or 'sin existencias registradas'))
            return respuesta('\n'.join(lineas) or 'Sin ubicaciones registradas.','stock_por_ubicacion')
        cantidades=[(u,len({p['id_producto'] for p in productos_ubicacion(u['id_ubicacion']) if p['cantidad']>0})) for u in us]
        if not cantidades:return respuesta('No hay ubicaciones disponibles.','ubicaciones_maximo')
        valor=(min if plan.operacion=='minimo' else max)(n for _,n in cantidades)
        return respuesta('; '.join(f"{u['codigo_ubicacion']}: {n} productos" for u,n in cantidades if n==valor)+'.','ubicaciones_maximo',us)
    if dominio=='productos' and plan.operacion=='agrupar':
        grupos=datos.agrupar_cantidades(servicios.datos_inventario(),'categoria','stock_actual')
        if re.search(r'\b(?:mayor|mas)\b',t):
            mejores={u:max(v for (_,unidad),v in grupos.items() if unidad==u) for _,u in grupos}
            grupos={k:v for k,v in grupos.items() if v==mejores[k[1]]}
        return respuesta('\n'.join(f'{categoria}: {format_numero(v)} {unidad}.' for (categoria,unidad),v in sorted(grupos.items())),
            'stock_categoria',[{'categoria':c,'unidad':u,'cantidad':v} for (c,u),v in grupos.items()])
    if dominio=='prediccion':
        from jarvis.jarvis_personality import prediccion
        rs=[dict(servicios.datos_prediccion(p['id_producto']),id_producto=p['id_producto']) for p in servicios.datos_inventario()]
        validos=[r for r in rs if r.get('datos_suficientes') and r.get('riesgo') in ('ALTO','CRÍTICO')]
        if not validos:return respuesta('No hay riesgos altos calculados.' if any(r.get('datos_suficientes') for r in rs) else 'Sin datos suficientes para evaluar el riesgo.','riesgos_producto')
        if op=='maximo':
            valor=max({'ALTO':2,'CRÍTICO':3}[r['riesgo']] for r in validos)
            validos=[r for r in validos if {'ALTO':2,'CRÍTICO':3}[r['riesgo']]==valor]
        return respuesta('\n'.join(prediccion(r) for r in validos[:plan.limite]),'riesgos_producto',validos)
    if dominio=='productos' and op=='detalle':
        p=plan.entidades.get('producto')
        if not p:return respuesta('¿Qué producto quieres consultar? Indica su nombre o código.','aclaracion')
        p=servicios.datos_producto(p['id_producto']);campos=[]
        if 'precio' in t:campos.append('Precio: '+(format_numero(p['precio']) if p.get('precio') is not None else 'no registrado'))
        if 'categoria' in t:campos.append('Categoría: '+str(p.get('categoria') or 'no registrada'))
        return respuesta(p['nombre']+'. '+('. '.join(campos) if campos else _linea(p,'productos'))+'.','producto_detalle',p)
    if dominio=='productos' and op=='led':
        p=plan.entidades.get('producto')
        if not p:
            ctx['plan_orquestador']=asdict(plan);ctx.esperar(['inventory.productos.led'],'producto')
            return respuesta('¿De qué producto quieres consultar el LED?','aclaracion')
        from integrations.arduino.led_service import resolver_filas
        direcciones=resolver_filas(servicios.datos_ubicaciones(p['id_producto']))
        if not direcciones:return respuesta('No hay ubicaciones con LED registradas para ese producto.','consultar_led')
        return respuesta('LED correspondiente: '+', '.join(str(u['led']) for u in direcciones)+'.','consultar_led',direcciones)
    if dominio=='conteos' and re.search(r'\bdiferencias?\b',t):
        from inventory.conteo_inventario import cargar_conteo,resumir_conteo
        filas=datos.conteos({})
        if not filas:return respuesta('No hay conteos registrados.','conteos_diferencias')
        c,detalle=cargar_conteo(filas[0]['id_conteo']);r=resumir_conteo(detalle)
        return respuesta(f"Conteo #{c['id_conteo']}: {r['faltantes']} registros con faltantes y {r['sobrantes']} con sobrantes.",'conteos_diferencias',r)
    if op=='explicar':
        clave={'anomalias':'ultima_anomalia','alertas':'ultima_alerta','movimientos':'ultimo_movimiento'}.get(dominio)
        anterior=ctx.get(clave) if clave else None
        numero=re.search(r'\b(?:alerta|anomalia|movimiento)\s+(?:numero\s+)?(\d+)\b',t)
        if numero and dominio in datos.IDS:
            campo=datos.IDS[dominio]
            anterior=next((f for f in datos.leer(dominio,{}) if f[campo]==int(numero.group(1))),None)
        if anterior:
            actuales=datos.leer(dominio,{})
            campo=datos.IDS[dominio];fila=next((f for f in actuales if f[campo]==anterior[campo]),None)
            if fila:return respuesta(fila.get('motivo') or fila.get('mensaje') or fila.get('observacion') or 'No hay un detalle adicional registrado.',dominio+'_explicar',fila)
        return respuesta('¿Qué registro quieres que explique? Indica su número.', 'aclaracion')
    filas=_filtrar(datos.leer(dominio,plan.filtros),plan)
    if dominio=='conteos' and 'pendiente' in t:filas=[f for f in filas if f['estado']=='BORRADOR']
    id_mencion=re.search(r'\b(?:alerta|anomalia|movimiento|conteo)\s+(?:numero\s+)?(\d+)\b',t)
    if id_mencion and dominio in datos.IDS:filas=[f for f in filas if f[datos.IDS[dominio]]==int(id_mencion.group(1))]
    intencion='consultar_movimientos' if dominio=='movimientos' and op=='contar' else dominio+'_'+op
    if op=='contar':
        total=len({f['id_movimiento'] for f in filas}) if dominio=='movimientos' else len(filas)
        return respuesta(f'Hay {total} '+({'empleados':'empleados activos registrados','productos':'productos activos registrados'}.get(dominio,dominio+' para la consulta'))+'.',intencion,{'total':total})
    if not filas:return respuesta('No hay registros disponibles para esa consulta.',intencion,[])
    if dominio=='productos' and op in ('maximo','minimo','comparar'):
        comparados=plan.entidades.get('productos')
        if comparados:filas=[f for f in filas if f['id_producto'] in {p['id_producto'] for p in comparados}]
        # Comparar cantidades solo dentro de una misma unidad de medida.
        unidades={f.get('unidad_medida') for f in filas}
        if len(unidades)>1:
            if comparados:return respuesta('Hay unidades de medida diferentes. Indica productos de la misma unidad para comparar sus cantidades.','aclaracion')
            seleccionar=min if op=='minimo' else max
            valores={u:seleccionar(Decimal(str(f['stock_actual'])) for f in filas if f.get('unidad_medida')==u) for u in unidades}
            filas=[f for f in filas if Decimal(str(f['stock_actual']))==valores[f.get('unidad_medida')]]
            _recordar(ctx,plan,filas)
            return respuesta('Comparación dentro de cada unidad de medida:\n'+'\n'.join(_linea(f,'productos') for f in filas),intencion,filas)
        valor=(min if op=='minimo' or (op=='comparar' and re.search(r'\b(?:menos|menor)\b',t)) else max)(Decimal(str(f['stock_actual'])) for f in filas)
        filas=[f for f in filas if Decimal(str(f['stock_actual']))==valor]
    elif op in ('maximo','minimo','comparar') and dominio=='movimientos':
        por_empleado='empleado' in t or 'quien' in t or plan.entidades.get('empleados')
        campo='id_empleado' if por_empleado else 'id_producto';grupos=defaultdict(set);nombres={}
        permitidos={e['id_empleado'] for e in plan.entidades.get('empleados',[])}
        for f in filas:
            if permitidos and f.get('id_empleado') not in permitidos:continue
            if f.get(campo) is None:continue
            grupos[f[campo]].add(f['id_movimiento']);nombres[f[campo]]=f['empleado' if por_empleado else 'producto']
        if not grupos:return respuesta('No hay identificadores suficientes para comparar los movimientos.',intencion)
        valor=(min if op=='minimo' or (op=='comparar' and re.search(r'\b(?:menos|menor)\b',t)) else max)(len(v) for v in grupos.values())
        return respuesta('; '.join(f'{nombres[k]}: {valor} movimientos' for k,v in grupos.items() if len(v)==valor)+'.',intencion,{'total':valor})
    elif op in ('sumar','promedio'):
        campo='stock_actual' if dominio=='productos' else 'cantidad'
        grupos=datos.agrupar_cantidades(filas,'unidad_medida',campo)
        promedios={u:(len({f['id_movimiento'] for f in filas if str(f.get('unidad_medida') or 'Unidad no informada')==u}) if dominio=='movimientos' else sum(str(f.get('unidad_medida') or 'Unidad no informada')==u for f in filas)) for u,_ in grupos}
        return respuesta('; '.join(f'{format_numero(v/promedios[unidad] if op=="promedio" else v)} {unidad}' for (unidad,_),v in grupos.items())+
            (' por movimiento registrado.' if op=='promedio' and dominio=='movimientos' else '.'),intencion,
            {'grupos':[{'unidad':u,'cantidad':v} for (u,_),v in grupos.items()]})
    elif op in ('ultimo','primero'):
        fechadas=[f for f in filas if _fecha_fila(f,dominio) is not None]
        if len(fechadas)!=len(filas):return respuesta('Faltan fechas registradas para determinar el orden con certeza.',intencion)
        filas=sorted(fechadas,key=lambda f:(_fecha_fila(f,dominio),f.get(datos.IDS.get(dominio,''),0)),reverse=op=='ultimo')[:plan.limite]
    else:filas=filas[:plan.limite]
    _recordar(ctx,plan,filas)
    return respuesta('\n'.join(_linea(f,dominio) for f in filas),intencion,filas)


def _preparar_accion(t,ctx,original):
    if re.search(r'\b(?:inicia|iniciar|deten|detener|detenla)\b.*\bvigilancia\b',t):
        from surveillance.vigilancia_yolo import servicio_vigilancia
        from core.config_manager import cargar_configuracion
        iniciar=bool(re.search(r'\binicia',t));activo=servicio_vigilancia.obtener_estado()['activo']
        if activo==iniciar:return respuesta('La vigilancia ya está '+('activa.' if activo else 'detenida.'),'estado_vigilancia')
        nombre='iniciar_vigilancia' if iniciar else 'detener_vigilancia'
        payload={'activo':activo,'configuracion':cargar_configuracion()['vigilancia']}
        return _pedir_confirmacion(ctx,nombre,payload,'Se '+('iniciará' if iniciar else 'detendrá')+' la vigilancia con la configuración vigente.')
    m=re.search(r'\b(?:atiende|atender|marca|marcar)\b.*\balerta\s*(?:numero\s*)?(\d+)',t)
    if m:
        a=next((a for a in datos.alertas({}) if a['id_alerta']==int(m.group(1))),None)
        if not a:return respuesta('La alerta no existe o ya no está pendiente.','alerta_no_disponible')
        return _pedir_confirmacion(ctx,'atender_alerta',{'id_alerta':a['id_alerta']},f"Se marcará como atendida la alerta #{a['id_alerta']}: {a['mensaje']}")
    m=re.search(r'\baplica(?:r)?\b.*\bconteo\s*(?:numero\s*)?(\d+)',t)
    if m:
        from inventory.conteo_inventario import cargar_conteo,resumir_conteo
        c,filas=cargar_conteo(int(m.group(1)))
        if c['estado']!='BORRADOR' or not filas or any(not f['contado'] for f in filas):return respuesta('El conteo debe ser un borrador completo antes de aplicarlo.','conteo_no_aplicable')
        r=resumir_conteo(filas)
        return _pedir_confirmacion(ctx,'aplicar_conteo',{'id_conteo':c['id_conteo'],'id_empleado':c['id_empleado'],'filas':filas},
            f"Se aplicará el conteo #{c['id_conteo']} con su responsable registrado: {r['faltantes']} faltantes y {r['sobrantes']} sobrantes. Se generarán ajustes.")
    if re.search(r'\bajusta(?:r)?\b.*(?:\bstock\b|\ba\s+\d)',t) or ctx.get('borrador_ajuste'):
        b=ctx.setdefault('borrador_ajuste',{})
        m=re.search(r'\ba\s+(-?\d+(?:[.,]\d+)?)(?![\w.,])',str(original).lower())
        if m:
            from inventory.inventario_service import decimal_inventario
            b['cantidad']=decimal_inventario(m.group(1).replace(',','.'),'Cantidad física')
            if b['cantidad']<0:ctx.pop('borrador_ajuste',None);raise ValueError('La cantidad física no puede ser negativa.')
        if 'cantidad' not in b:return respuesta('¿Qué cantidad física quieres registrar? Usa «a 50».','aclaracion')
        ps=coincidencias(t,servicios.datos_inventario(),'producto')
        if len(ps)>1:return respuesta('Indica el código exacto del producto para el ajuste.','aclaracion')
        if ps:b['producto']=ps[0]
        if 'producto' not in b:return respuesta('¿Qué producto quieres ajustar? Indica su código.','aclaracion')
        p=servicios.datos_producto(b['producto']['id_producto'])
        if p.get('control_lotes'):
            ctx.pop('borrador_ajuste',None);return respuesta('Este producto requiere seleccionar un lote. Realiza el ajuste desde Movimientos. No modifiqué existencias.','accion_no_disponible')
        us=servicios.datos_ubicaciones(p['id_producto'])
        seleccion=[u for u in us if normalizar_texto(u['codigo_ubicacion']) in t]
        if seleccion:b['ubicacion']=seleccion[0]
        if len(us)==1:b['ubicacion']=us[0]
        if 'ubicacion' not in b:return respuesta('¿En qué ubicación? '+', '.join(u['codigo_ubicacion'] for u in us)+'.','aclaracion')
        es=coincidencias(t,datos.empleados({}),'empleado')
        if len(es)==1:b['empleado']=es[0]
        if 'empleado' not in b:return respuesta('¿Qué empleado será responsable? Indica su código.','aclaracion')
        actual=next((u for u in us if u['id_ubicacion']==b['ubicacion']['id_ubicacion']),None)
        if not actual:ctx.pop('borrador_ajuste',None);raise ValueError('La ubicación cambió. Solicita el ajuste de nuevo.')
        anterior=Decimal(str(actual['cantidad']));diferencia=b['cantidad']-anterior
        if not diferencia:ctx.pop('borrador_ajuste',None);return respuesta('El stock ya coincide. No se necesita un ajuste.','sin_cambios')
        payload={'id_producto':p['id_producto'],'id_ubicacion':actual['id_ubicacion'],'id_empleado':b['empleado']['id_empleado'],
            'cantidad':b['cantidad'],'stock_anterior':anterior}
        ctx.pop('borrador_ajuste',None)
        return _pedir_confirmacion(ctx,'ajustar_stock',payload,
            f"{p['nombre']}, {actual['codigo_ubicacion']}. Stock en esa ubicación: {format_numero(anterior)} → {format_numero(b['cantidad'])}. "
            f"Ajuste de {'entrada' if diferencia>0 else 'salida'} de {format_numero(abs(diferencia))}. Responsable: {b['empleado']['nombre']}.")
    return None


def _pedir_confirmacion(ctx,nombre,payload,resumen):
    from core.audit_service import audit, capture_context
    audit.record('JARVIS', 'JARVIS_CONFIRMATION', 'CONFIRMATION_REQUIRED', data={'tool':nombre})
    ctx.completar();ctx['plan_orquestador']=None
    ctx.update(estado_dialogo='WAITING_FOR_ACTION_CONFIRMATION',intencion_pendiente=nombre,
        plan_pendiente=[nombre],tipo_entidad_pendiente='confirmacion')
    ctx['confirmacion_pendiente']={'accion':nombre,'datos':payload,'vence':time.monotonic()+120,
                                 '_audit_context':capture_context()}
    return respuesta(resumen+' ¿Confirmas?','confirmacion_requerida',confirmation=True)


def cancelar_pendientes(ctx):
    for clave in ('borrador_movimiento','borrador_ajuste','capacidad_pendiente','led_pendiente'):
        ctx.pop(clave,None)
    ctx['confirmacion_pendiente']=None;ctx['plan_orquestador']=None;ctx.completar()


def procesar(texto,ctx=None,fallback=None,session_id='escritorio'):
    """Se invoca bajo el lock de ConversationState del punto público compartido."""
    if ctx is None or isinstance(ctx,str):
        from jarvis.agente_inventario import procesar_consulta
        return procesar_consulta(texto,True,sesion=ctx if isinstance(ctx,str) else session_id)
    t=normalizar_texto(texto);t=re.sub(r'^(?:hola\s+)?jarvis\s*','',t)
    if re.fullmatch(r'(?:inicia|iniciar|abre|abrir) (?:el )?reconocimiento(?: facial)?',t):
        cancelar_pendientes(ctx)
        return respuesta('El reconocimiento se inicia desde la cámara de la aplicación de escritorio.','facial',acciones_ui=[{'tipo':'facial'}])
    apertura=re.fullmatch(r'(?:abre|abrir|inicia|iniciar|continua|continuar)\s+(?:el |la |modulo de )?(conteo fisico|conteo|reportes|productos|movimientos|empleados|alertas|anomalias|prediccion|jarvis)',t)
    if apertura:
        cancelar_pendientes(ctx)
        modulo={'conteo fisico':'Conteo de inventario','conteo':'Conteo de inventario','anomalias':'Anomalías','prediccion':'Predicción'}.get(apertura.group(1),apertura.group(1).capitalize())
        return respuesta(f'Acceso a {modulo} listo en la aplicación de escritorio.','abrir_modulo',acciones_ui=[{'tipo':'abrir_modulo','modulo':modulo}])
    if ctx.get('borrador_ajuste') and re.match(r'^(?:que|quien|cuant[oa]s?|donde|hay|muestra|lista|estado|abre|genera)\b',t):
        ctx.pop('borrador_ajuste',None)
    if t in ('cancelar','cancela','olvidalo','deja eso','otra consulta','no','mejor no','reiniciar contexto','reinicia el contexto','olvida la conversacion'):
        if t in ('reiniciar contexto','reinicia el contexto','olvida la conversacion'):
            ctx.limpiar();return respuesta('Contexto reiniciado.','reiniciar_contexto')
        if ctx.get('confirmacion_pendiente') or ctx.get('borrador_ajuste') or ctx.get('borrador_movimiento') or ctx.get('capacidad_pendiente') or ctx.get('plan_orquestador'):
            cancelar_pendientes(ctx)
            return respuesta('Cancelado. No modifiqué datos.','cancelar_consulta')
    if ctx.get('confirmacion_pendiente'):
        pendiente=ctx['confirmacion_pendiente']
        if time.monotonic()>pendiente['vence']:
            from core.audit_service import audit
            audit.record('JARVIS', 'JARVIS_CONFIRMATION', 'REJECTED', data={'reason':'expired','tool':pendiente['accion']})
            ctx['confirmacion_pendiente']=None;ctx.completar()
            if t in ('si','confirmar','confirmo','hazlo'):return respuesta('La confirmación venció. Solicita la acción nuevamente.','confirmacion_vencida')
        elif t in ('si','confirmar','confirmo','hazlo'):
            from core.audit_service import audit
            audit.record('JARVIS', 'JARVIS_CONFIRMATION', 'CONFIRMED', data={'tool':pendiente['accion']})
            # Consumir antes de llamar al servicio evita dobles ejecuciones por reintento.
            ctx['confirmacion_pendiente']=None;ctx.completar()
            texto_resultado=datos.ejecutar_confirmado(pendiente['accion'],pendiente['datos'])
            ctx['ultima_accion']={'accion':pendiente['accion'],'resultado':texto_resultado}
            return respuesta(texto_resultado,'accion_confirmada',accion_ejecutada=ctx['ultima_accion'])
        elif SOCIAL.social(t):return fallback(texto)
        else:ctx['confirmacion_pendiente']=None;ctx.completar()
    if SOCIAL.social(t):return fallback(texto)
    from jarvis.tools.presencia import responder as responder_presencia
    presencia=responder_presencia(t,ctx)
    if presencia is not None:return presencia
    from jarvis.tools.eventos import responder_eventos
    eventos=responder_eventos(t)
    if eventos is not None:
        return respuesta(eventos[1],'eventos_recientes',{'eventos':eventos[0]})
    from jarvis.jarvis_capacidades import seguimiento, compuesta, capacidad
    if ctx.get('borrador_movimiento') and re.match(r'^(?:que|quien|cuanto|cuantos|donde|hay|muestra|lista|estado|abre|genera)\b',t):
        ctx.pop('borrador_movimiento',None);ctx.completar()
    # Negaciones no deben iniciar acciones por contener el verbo de la petición.
    if not re.search(r'^no\b',t):
        from jarvis.jarvis_acciones import preparar_movimiento
        movimiento=preparar_movimiento(texto,ctx)
        if movimiento is not None:return movimiento
        accion=_preparar_accion(t,ctx,texto)
        if accion is not None:return accion
    if re.search(r'\b(?:elimina|eliminar|borra|borrar|registra|registrar|crea|crear|configura|modifica)\b',t):
        return respuesta('Esa modificación requiere la pantalla correspondiente y sus validaciones. No ejecuté cambios.','accion_no_permitida')
    if t in ('apagalo','apagala','apaga su luz','enciende su luz','encender su luz') and ctx.get('ultimo_producto_id'):
        from integrations.arduino.led_service import servicio_led
        encender=t.startswith('enc')
        r=servicio_led.por_producto(ctx['ultimo_producto_id'],encender)
        return respuesta(r['mensaje'],'led',r)
    if SOCIAL.social(t):return fallback(texto)
    for ruta in (seguimiento,compuesta,capacidad):
        resultado=ruta(t,ctx)
        if resultado is not None:return resultado
    if re.search(r'\b(?:algo critico|algo urgente|que paso con)\b',t):
        a=Plan('alertas',filtros={'nivel':'CRÍTICA'},texto=t);n=Plan('anomalias',filtros={'nivel':'CRÍTICA'},texto=t)
        ps=coincidencias(t,servicios.datos_inventario(),'producto')
        if len(ps)>1:return _aclarar(a,ctx,'producto',ps)
        if ps:a.filtros['producto']=n.filtros['producto']=ps[0]['id_producto']
        if 'que paso con' in t:a.filtros.pop('nivel',None);n.filtros.pop('nivel',None)
        alertas=_filtrar(datos.alertas(a.filtros),a);anomalias=_filtrar(datos.anomalias(n.filtros),n)
        # No sumar la alerta derivada y su hallazgo como dos incidentes distintos.
        vinculados={f.get('id_movimiento') for f in anomalias if f.get('id_movimiento')}
        independientes=[f for f in alertas if not f.get('id_movimiento') or f['id_movimiento'] not in vinculados]
        agotados=servicios.datos_inventario('Agotados') if re.search(r'\balgo (?:critico|urgente)\b',t) else []
        ids_agotados={p['id_producto'] for p in agotados}
        independientes=[f for f in independientes if not (f.get('id_producto') in ids_agotados and 'agotad' in normalizar_texto(f.get('tipo','')))]
        return respuesta(f'Hay {len(independientes)+len(anomalias)+len(agotados)} eventos para la consulta.\n'+
            '\n'.join(_linea(f,'alertas') for f in independientes[:3])+'\n'+
            '\n'.join(_linea(f,'anomalias') for f in anomalias[:3])+'\n'+
            '\n'.join('Agotado: '+_linea(p,'productos') for p in agotados[:3]),'eventos_criticos',{'alertas':alertas,'anomalias':anomalias,'agotados':agotados})
    if re.search(r'\b(?:quien lo hizo|que (?:producto )?movio)\b',t) and not re.search(r'\bultim[oa]\b',t) and ctx.get('ultimo_movimiento'):
        m=ctx['ultimo_movimiento']
        # Refrescar el registro para no afirmar que un movimiento eliminado sigue vigente.
        filas=servicios.datos_movimientos({},m.get('id_producto'))
        m=next((f for f in filas if f['id_movimiento']==m['id_movimiento']),None)
        return respuesta(_linea(m,'movimientos') if m else 'Ese movimiento ya no está disponible.','movimiento_referencia',m)
    if re.fullmatch(r'(?:y )?(?:quien lo hizo|que movio)',t) and not ctx.get('ultimo_movimiento'):
        return respuesta('¿A qué movimiento te refieres? Indica su número o el producto.','aclaracion')
    plan=interpretar(t,ctx)
    if plan and plan.dominio=='aclaracion':
        ctx['dominio_pendiente']=t
        return respuesta('¿Te refieres al último producto agregado o al último empleado registrado?','aclaracion')
    if ctx.get('dominio_pendiente') and t in ('productos','producto','empleados','empleado'):
        plan=interpretar(ctx.pop('dominio_pendiente')+' '+t,ctx)
    pendiente=ctx.get('plan_orquestador')
    if pendiente and plan is not None and not t.isdigit():
        ctx['plan_orquestador']=None;ctx.completar();pendiente=None
    if pendiente and (plan is None or t.isdigit()):
        plan=Plan(**pendiente);plan.texto=t
    if plan:
        aclaracion=resolver(plan,ctx)
        if aclaracion:return aclaracion
        if pendiente:ctx['plan_orquestador']=None
        r=ejecutar_consulta(plan,ctx)
        if r['intencion']!='aclaracion':ctx.completar()
        from jarvis.agente_inventario import _guardar_traza
        _guardar_traza(plan=asdict(plan),herramienta='orquestador_'+plan.dominio,
            clarification=r.get('clarification',False),confirmation=r.get('confirmation',False))
        logging.getLogger('jarvis').debug('[JARVIS] intent=%s entities=%s tool=%s clarification=%s confirmation=%s',
            plan.operacion,list(plan.entidades),plan.dominio,r.get('clarification',False),r.get('confirmation',False))
        return r
    r=fallback(texto)
    # Las rutas heredadas válidas conservan herramientas y respuestas. La ruta
    # incierta no vuelve a intentar buscar toda la pregunta como un nombre.
    if r is not None:return r
    from jarvis.agente_inventario import _consulta_estructurada_compatibilidad
    if re.search(r'\b(?:subject|sujeto|rostro|reabastecimiento|comprar|precio|categoria|ayuda|empleado|alertas|inventario|reconocidas)\b',t):
        return _consulta_estructurada_compatibilidad(texto)
    return respuesta('No estoy seguro de qué quieres consultar. Puedes preguntarme por productos, movimientos, empleados, alertas, anomalías o estado del sistema.','desconocida')
