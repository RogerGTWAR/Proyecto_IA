"""Capa NLP local de Jarvis: intención, análisis lingüístico y entidades."""
from core.paths import PROJECT_ROOT

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

try:
    from rapidfuzz.fuzz import ratio as _rapid_ratio
except ImportError:
    _rapid_ratio = None

try:
    import spacy
except ImportError:
    spacy = None


UMBRAL_INTENCION = 0.38
RUTA_INTENCIONES = (PROJECT_ROOT / 'intenciones_jarvis.json')

PALABRAS_FUNCIONALES = {
    "a", "al", "de", "del", "el", "en", "esta", "estan", "hay", "la", "las", "lo", "los",
    "me", "mi", "para", "por", "producto", "productos", "que", "se", "un", "una", "y", "jarvis",
    "hola", "hey", "oye", "buenas", "buenos", "dias", "tardes", "noches", "favor", "actualmente",
    "cuanto", "cuantos", "cantidad", "stock", "existencia", "existencias", "tenemos", "tiene", "quedan",
    "donde", "ubicacion", "localiza", "encontrar", "movimiento", "movimientos", "ultimo", "ultima",
    "historial", "empleado", "informacion", "datos", "buscar", "consulta", "consultar", "mostrar", "dime"
}

# Vocabulario compartido por el router y la extracción de entidades.
SINONIMOS = {
    'consultar_stock': ('stock', 'queda', 'quedan', 'disponible', 'disponibles', 'existencia', 'existencias', 'unidades', 'tenemos'),
    'consultar_ubicacion': ('donde', 'ubicacion', 'localiza', 'localizar', 'ubica', 'mapa', 'guardado', 'guardados', 'guardada', 'guardadas', 'muestramelo', 'muestramelos', 'muestrala', 'muestralos'),
    'prediccion_agotamiento': ('durara', 'duraran', 'duraria', 'durarian', 'durar', 'duracion', 'cuanto tiempo', 'cuantos dias', 'hasta cuando', 'prediccion', 'agotarse', 'agotara', 'agotaran', 'acabarse', 'se acaba', 'se acaban', 'se va a acabar', 'riesgo'),
    'consultar_anomalias': ('anomalia', 'anomalias', 'inusual', 'inusuales', 'raro', 'rara', 'raros', 'raras', 'extrano', 'extrana', 'extranos', 'extranas', 'anormal', 'sospechoso', 'sospechosos'),
}
PALABRAS_FUNCIONALES.update(p for frases in SINONIMOS.values() for f in frases for p in f.split())
PALABRAS_FUNCIONALES.update('abre abrir abreme llevame ensename ensena muestrame muestramelo muestramelos muestramela ver mapa su cual es estante nivel posicion'.split())


def solicita_mapa(texto,contexto_ubicacion=False):
    """La consulta de ubicación y la petición de navegar son decisiones distintas."""
    texto=normalizar_texto(texto)
    if re.search(r'\b(?:no|sin)\b.{0,45}\b(?:mapa|abrir|abras|muestres)\b',texto):return False
    if re.search(r'\bmapa\b',texto) and re.search(r'\b(?:abre|abrir|abreme|ver|muestra|muestrame|muestramelo|muestramelos|mostrar|llevame|lleva|ensena|ensename)\b',texto):return True
    if re.search(r'\b(?:ensename|ensena|muestrame|muestra)\b.*\bdonde\b',texto):return True
    return bool(contexto_ubicacion and re.fullmatch(r'(?:jarvis\s+)?(?:muestramelo|muestramela|muestramelos|muestramelas|muestrala|muestralos|muestralo)(?:\s+por favor)?',texto))


def contiene_intencion(texto, intencion):
    return bool(re.search(r'\b(?:'+'|'.join(re.escape(p) for p in SINONIMOS[intencion])+r')\b', texto))


def normalizar_texto(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower().strip())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\-/ ]", " ", texto)
    texto = " ".join(texto.split())
    return re.sub(r"\b(?:jarbis|yarvis)\b", "jarvis", texto)


def _similitud(a, b):
    if _rapid_ratio:
        return _rapid_ratio(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class ResultadoNLP:
    texto_original: str
    texto_normalizado: str
    lemas: list[str]
    intencion: Optional[str]
    confianza: float
    entidades: dict = field(default_factory=dict)
    saludo: bool = False
    usa_contexto: bool = False


class ProcesadorNLPJarvis:
    """Se crea una sola vez; el clasificador y spaCy permanecen en memoria."""

    def __init__(self, ruta_intenciones=RUTA_INTENCIONES, umbral=UMBRAL_INTENCION):
        self.umbral = umbral
        with open(ruta_intenciones, encoding="utf-8") as archivo:
            self.ejemplos = json.load(archivo)
        textos, etiquetas = [], []
        for etiqueta, frases in self.ejemplos.items():
            textos.extend(frases)
            etiquetas.extend([etiqueta] * len(frases))
        caracteristicas = FeatureUnion([
            ("palabras", TfidfVectorizer(preprocessor=normalizar_texto, ngram_range=(1, 2), sublinear_tf=True)),
            ("caracteres", TfidfVectorizer(preprocessor=normalizar_texto, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
        ])
        self.clasificador = Pipeline([
            ("tfidf", caracteristicas),
            ("modelo", LogisticRegression(max_iter=1500, C=8.0, class_weight="balanced", random_state=42)),
        ])
        self.clasificador.fit(textos, etiquetas)
        self.nlp_es = None
        if spacy is not None:
            try:
                self.nlp_es = spacy.load("es_core_news_sm", disable=["parser"])
            except OSError:
                pass

    @property
    def usa_spacy(self):
        return self.nlp_es is not None

    def lematizar(self, texto):
        if not self.nlp_es:
            return normalizar_texto(texto).split()
        documento = self.nlp_es(texto)
        return [normalizar_texto(token.lemma_) for token in documento if not token.is_space and not token.is_punct]

    def clasificar(self, texto):
        probabilidades = self.clasificador.predict_proba([texto])[0]
        indice = int(probabilidades.argmax())
        return str(self.clasificador.classes_[indice]), float(probabilidades[indice])

    def interpretar(self, texto):
        normalizado = normalizar_texto(texto)
        if not normalizado:
            return ResultadoNLP(str(texto), "", [], None, 0.0)
        intencion, confianza = self.clasificar(normalizado)
        saludo = bool(re.search(r"\b(hola|hey|buenas|buenos dias|que onda|que tal)\b", normalizado))
        # Un saludo dentro de una consulta no debe reemplazar la intención operativa.
        texto_sin_saludo = re.sub(r"\b(hola|hey|buenas|buenos dias|buenas tardes|buenas noches|que onda)\b", " ", normalizado)
        texto_sin_saludo = re.sub(r"\bjarvis\b", " ", texto_sin_saludo).strip()
        if saludo and len(texto_sin_saludo.split()) >= 2:
            secundaria, confianza_secundaria = self.clasificar(texto_sin_saludo)
            if secundaria != "saludo" and confianza_secundaria >= confianza * 0.80:
                intencion, confianza = secundaria, confianza_secundaria
        if confianza < self.umbral:
            intencion = None
        resultado = ResultadoNLP(str(texto), normalizado, self.lematizar(texto), intencion,
                                 confianza, saludo=saludo)
        resultado.entidades.update(self.extraer_entidades_basicas(resultado))
        return resultado

    def extraer_entidades_basicas(self, resultado):
        """Extrae valores estructurados; producto y empleado se validan luego en SQL."""
        texto = resultado.texto_normalizado
        entidades = {}
        codigo_producto = re.search(r"\b(?:prod(?:ucto)?[- ]?)\d{1,8}\b", texto)
        codigo_empleado = re.search(r"\b(?:emp(?:leado)?[- ]?)\d{1,8}\b", texto)
        ubicacion = re.search(r"\b[a-z]{1,3}-\d{1,3}(?:-\d{1,3}){0,3}\b", texto)
        if codigo_producto:
            entidades["CODIGO_PRODUCTO"] = codigo_producto.group(0).upper().replace(" ", "-")
        if codigo_empleado:
            entidades["CODIGO_EMPLEADO"] = codigo_empleado.group(0).upper().replace(" ", "-")
        if ubicacion:
            entidades["UBICACION"] = ubicacion.group(0).upper()
        if re.search(r"\b(alta|alto|urgente|critica|critico)\b", texto):
            entidades["NIVEL_ALERTA"] = "Alta"
        elif re.search(r"\b(media|medio)\b", texto):
            entidades["NIVEL_ALERTA"] = "Media"
        elif re.search(r"\b(baja|bajo)\b", texto):
            entidades["NIVEL_ALERTA"] = "Baja"
        subject = re.search(r"\b(?:subject|sujeto|persona)\s*0*(\d{1,6})\b", texto)
        if subject:
            entidades["SUBJECT_NUMERO"] = int(subject.group(1))
        if re.search(r"\b(salida|retiro|retirar|sacar)\b", texto):
            entidades["TIPO_MOVIMIENTO"] = "Salida"
        elif re.search(r"\b(entrada|ingreso|ingresar|recibir)\b", texto):
            entidades["TIPO_MOVIMIENTO"] = "Entrada"
        elif re.search(r"\b(traslado|transferencia|mover)\b", texto):
            entidades["TIPO_MOVIMIENTO"] = "Traslado"
        return entidades

    def resolver_catalogo(self, resultado, catalogo, id_campo, nombre_campos, tipo_entidad):
        """Resuelve solo contra filas reales; nunca fabrica nombres ni identificadores."""
        texto = resultado.texto_normalizado
        ignoradas = PALABRAS_FUNCIONALES | PALABRAS_CONSULTA
        tokens = [singular(t) for t in texto.split() if len(t) >= 3 and t not in ignoradas]
        if not tokens:
            return []
        completas, puntuadas = [], []
        for fila in catalogo:
            valores = [normalizar_texto(fila.get(campo, "")) for campo in nombre_campos]
            if any(v and re.search(r'(?<!\w)'+re.escape(v)+r'(?!\w)',texto) for v in valores):
                completas.append((max(len(v) for v in valores if v and re.search(r'(?<!\w)'+re.escape(v)+r'(?!\w)',texto)),fila))
                continue
            partes = {singular(p) for valor in valores for p in valor.split() if len(p)>=3 and p not in ignoradas}
            coincidencias = [max((_similitud(t,p) if t!=p else 1.0 for p in partes),default=0) for t in tokens]
            foneticas = [max((_similitud(fonetica(t),fonetica(p)) for p in partes),default=0) for t in tokens]
            coincidencias=[max(a,b*.95) for a,b in zip(coincidencias,foneticas)]
            puntaje=sum(coincidencias)/len(coincidencias)
            if puntaje>=.76 and min(coincidencias)>=.65:
                puntuadas.append((puntaje,fila))
        halladas = [f for n,f in completas if n==max((n for n,_ in completas),default=0)]
        if not halladas and puntuadas:
            mejor=max(p for p,_ in puntuadas)
            halladas=[f for p,f in puntuadas if p>=mejor-.04]
        if len(halladas) == 1:
            resultado.entidades[tipo_entidad] = halladas[0]
        return halladas

    def resolver_producto(self, resultado, productos):
        return self.resolver_catalogo(resultado, productos, "id_producto", ("codigo", "nombre"), "PRODUCTO")

    def resolver_empleado(self, resultado, empleados):
        return self.resolver_catalogo(resultado, empleados, "id_empleado", ("codigo_empleado", "nombre"), "EMPLEADO")


PALABRAS_CONSULTA=set('queda quedan hay estan esta estamos durara duraran durar duracion agotarse agotar agotaran podria puede tiempo riesgo alto altos bajo bajos critico critica criticos tambien donde cuanto cuantos cuanto cuando nuevo nueva ultimo ultima ultimos recientes anterior anteriores previa previo actividad operacion operaciones mas menos responsabilidad responsable sacar retiro retirado retiraron quien dime dame saber revisar consultar quiero quieres necesito necesitamos sobre acerca ese esa esos esas eso ellos ellas ahi alli mismo mismos primero segundo tercero cuarto quinto elige selecciona seleccion de del en y el la los las un una con como por porque fue marcada marcado explicame explica detalles detalle muestrame muestramelo muestramelos muestrala muestralos muestra mostrar ver mapa localiza localizar rostro registrado registrada registrados registradas pertenece cargo hizo realizaron realizo hubo cuantos hoy ayer semana mes este esta ultimos dias'.split())

def singular(token):
    if token.endswith('s') and len(token)>4:
        return token[:-2] if token.endswith(('res','nes','les')) else token[:-1]
    return token


PALABRAS_CONSULTA.update({'falta','faltan'})

def fonetica(token):
    return re.sub(r'c(?=[ei])','s',token.replace('ll','y').replace('iy','y'))

def extraer_filtros(texto,hoy=None):
    """Entidades de lectura y fechas inclusivas, sin interpretar números de códigos como cantidades."""
    from datetime import datetime,timezone,timedelta,date
    hoy=hoy or datetime.now(timezone(timedelta(hours=-6))).date()
    filtros={}
    if re.search(r'\bhoy\b',texto):desde=hasta=hoy
    elif re.search(r'\bayer\b',texto):desde=hasta=hoy-timedelta(days=1)
    elif 'esta semana' in texto:desde,hasta=hoy-timedelta(days=hoy.weekday()),hoy
    elif 'este mes' in texto:desde,hasta=hoy.replace(day=1),hoy
    else:
        m=re.search(r'ultimos?\s+(\d+)\s+dias?',texto)
        fecha=re.search(r'\b(\d{4}-\d{2}-\d{2})\b',texto)
        if m:
            n=int(m.group(1))
            if not 1<=n<=365:raise ValueError('Indica un período de entre 1 y 365 días.')
            desde,hasta=hoy-timedelta(days=n-1),hoy
        elif fecha:desde=hasta=date.fromisoformat(fecha.group(1))
        else:desde=hasta=None
    if desde:filtros.update(fecha_desde=desde.isoformat(),fecha_hasta=hasta.isoformat())
    espacial=re.search(r'\b(zona|estante|pasillo|ubicacion)\s+([a-z0-9][a-z0-9-]*)',texto)
    if espacial:filtros.update(campo_ubicacion=espacial.group(1),valor_ubicacion=espacial.group(2))
    for t in ('entrada','salida','transferencia'):
        if re.search(r'\b'+t+r's?\b',texto):filtros['tipo_movimiento']=t.title();break
    if re.search(r'\b(?:salio|salieron)\b',texto):filtros['tipo_movimiento']='Salida'
    nivel=re.search(r'\b(?:riesgo|nivel)\s+(alto|alta|medio|media|bajo|baja|critico|critica)\b',texto)
    if nivel:filtros['nivel']=nivel.group(1).upper().replace('CRITICO','CRÍTICO').replace('CRITICA','CRÍTICA')
    cantidad=re.search(r'\bcantidad\s+(\d+(?:[.]\d+)?)\b',texto)
    if cantidad:filtros['cantidad']=cantidad.group(1)
    return filtros

def plan_conversacional(texto):
    """Prioridades por dominio: contar movimientos nunca implica consultar stock."""
    if contiene_intencion(texto,'consultar_anomalias'):return ['consultar_anomalias']
    if re.search(r'\b(?:consumiendo mas|consumen mas|mayor consumo|mas salidas)\b',texto):return ['resumen_consumo']
    if re.search(r'\b(?:movimientos?|operacion|actividad)\b',texto) and not re.search(r'\b(?:rostro|subject|sujeto)\b',texto):return ['consultar_movimientos']
    if re.search(r'\b(emplead[oa]s?|cargo|subject|sujeto|persona|quien)\b',texto) and not re.search(r'\b(retiro|retir|saco|salida|responsable)\b',texto):return []
    if re.search(r'\b(movimientos?|historial|salidas?|salio|salieron|entradas?|transferencias?|retiros?|responsable|actividad|operacion)\b',texto):return ['consultar_movimientos']
    if re.search(r'\b(alertas?|avisos?|notificaciones?)\b',texto):return []
    if re.search(r'\b(categoria|categorias)\b',texto) and re.search(r'\b(productos|que hay|lista|muestra)\b',texto):return ['contenido_categoria']
    if re.search(r'\b(zona|estante|pasillo|ubicacion)\b',texto) and re.search(r'\b(productos|que hay|contenido|muestra)\b',texto):return ['contenido_ubicacion']
    if 'stock minimo' in texto:return ['stock_minimo']
    grupos=[]
    if re.search(r'\b(?:productos?\s+(?:estan\s+|con\s+)?(?:stock\s+)?bajos?|stock bajo|poco stock)\b',texto):grupos.append('stock_bajo')
    if re.search(r'\b(?:productos?\s+agotados?|agotados)\b',texto):grupos.append('productos_agotados')
    if re.search(r'\b(?:agotarse primero|agotaria primero|agotara primero|primero en agotarse)\b',texto):grupos.append('prediccion_agotamiento')
    if re.search(r'\briesgo\s+(?:alto|critico|medio|bajo)\b',texto):grupos.append('consultar_riesgo')
    if grupos:return grupos
    plan=[]
    stock=contiene_intencion(texto,'consultar_stock') or bool(re.search(r'\bcuant[oa]s?\s+(?:hay|tenemos|tiene)\b',texto))
    if 'donde' in texto and not re.search(r'\b(?:stock|cuant[oa]s?|tenemos|existencias?|unidades)\b',texto):stock=False
    if stock and not re.search(r'cuanto tiempo|cuantos dias',texto):plan.append('consultar_stock')
    if contiene_intencion(texto,'consultar_ubicacion') or re.search(r'\ben que (?:estante|nivel|posicion|pasillo)\b',texto):plan.append('consultar_ubicacion')
    if contiene_intencion(texto,'prediccion_agotamiento'):plan.append('prediccion_agotamiento')
    if re.search(r'\b(?:tambien|esta|estan)\b.*\b(?:bajos?|critic[oa]s?)\b',texto):plan.append('estado_producto')
    return list(dict.fromkeys(plan))

procesador_nlp = ProcesadorNLPJarvis()


class IntentRouter:
    """Rutas compartidas; reutiliza el plan y el clasificador existentes."""
    acciones_producto = {'consultar_stock', 'consultar_ubicacion', 'prediccion_agotamiento',
                         'estado_producto', 'stock_minimo', 'historial_producto',
                         'ultimo_retiro', 'ultimo_movimiento'}

    def resolver(self, texto):
        return plan_conversacional(texto)

    def social(self, texto):
        # Una frase social completa no absorbe «hola, stock de filtros».
        texto = re.sub(r'^(?:jarvis|oye|hey)[, ]+', '', texto)
        vocativo = r'(?:\s+(?:jarvis|amigo|amiga|bro|dogh|dog|compa|colega))*'
        for patron, tipo in (
            (r'(?:que nota|que onda|que tal|como estas|como andas)', 'como_estas'),
            (r'(?:hola|hey|buenas|buenos dias|buenas tardes|buenas noches)', 'saludo'),
            (r'(?:gracias|muchas gracias|te agradezco)', 'agradecimiento'),
            (r'(?:perfecto|dale|ok|okay|listo|todo bien|de acuerdo)', 'confirmacion_social'),
            (r'(?:que haces|que estas haciendo)', 'actividad_social'),
            (r'(?:adios|hasta luego|nos vemos|hasta pronto)', 'despedida')):
            if re.fullmatch(patron + vocativo, texto):
                return tipo
        return 'saludo' if texto == 'jarvis' else None


class EntityResolver:
    """Un solo catálogo real; las medidas explícitas restringen coincidencias."""
    def __init__(self, nlp):
        self.nlp = nlp

    def productos(self, analisis, catalogo):
        analisis.texto_normalizado = re.sub(r'\bel de media(?: pulgada)?\b', 'el de 1/2', analisis.texto_normalizado)
        filas = self.nlp.resolver_producto(analisis, catalogo)
        if not filas and not re.search(r'\b[a-z]{2,8}-\d+\b', analisis.texto_normalizado):
            tokens=[singular(t) for t in analisis.texto_normalizado.split()
                    if len(t)>=3 and t not in PALABRAS_FUNCIONALES|PALABRAS_CONSULTA]
            puntuadas=[]
            for fila in catalogo:
                partes=[singular(t) for t in normalizar_texto(fila.get('nombre','')).split()
                        if len(t)>=3 and t not in PALABRAS_FUNCIONALES]
                scores=[max((_similitud(t,p) for p in partes),default=0) for t in tokens]
                if scores and min(scores)>=.55 and sum(scores)/len(scores)>=.65:
                    puntuadas.append((sum(scores)/len(scores),fila))
            if puntuadas:
                mejor=max(s for s,_ in puntuadas)
                filas=[f for s,f in puntuadas if s>=mejor-.06]
                analisis.entidades['PRODUCTO_SUGERIDO']=True
        medidas = re.findall(r'(?<!\d)\d+/\d+(?!\d)', analisis.texto_normalizado)
        if medidas:
            def coincide(f):
                return all(re.search(r'(?<!\d)'+re.escape(m)+r'(?!\d)',normalizar_texto(f.get('nombre',''))) for m in medidas)
            filas = [f for f in filas if coincide(f)]
            tokens = [t for t in analisis.texto_normalizado.split()
                      if t not in PALABRAS_FUNCIONALES | PALABRAS_CONSULTA and t not in medidas]
            if not filas and not tokens:
                filas = [f for f in catalogo if coincide(f)]
        return filas
