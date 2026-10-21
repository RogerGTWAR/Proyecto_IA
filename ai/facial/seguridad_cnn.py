"""Decisión CNN, rechazo y evidencia temporal. No modifica el motor de embeddings."""
from collections import Counter, deque
import math
import numpy as np

VERSION_PROTOCOLO='cnn-sesiones-documentadas-validacion-calibracion-evaluacion-v2'


def ranking(probabilidades, etiquetas):
    p=np.asarray(probabilidades,dtype=float)
    if p.ndim!=1 or len(p)<2 or not np.isfinite(p).all() or np.any(p<0) or np.any(p>1) or not np.isclose(p.sum(),1,atol=1e-3):
        raise ValueError('La CNN devolvió probabilidades incompatibles.')
    if set(etiquetas)!=set(range(len(p))) or len(set(etiquetas.values()))!=len(p):
        raise ValueError('El mapeo de clases CNN no coincide con el modelo.')
    indices=np.argsort(p,kind='stable')[::-1];a,b=map(int,indices[:2])
    return {'best_class':etiquetas[a],'best_score':float(p[a]),
            'second_class':etiquetas[b],'second_score':float(p[b]),'margin':float(p[a]-p[b])}


def parametros_validos(p):
    if not isinstance(p,dict) or p.get('calibrada') is not True or p.get('protocolo')!=VERSION_PROTOCOLO:return False
    for campo in ('threshold','margin'):
        v=p.get(campo)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<1:return False
    evidencia=p.get('validacion_independiente',{})
    return (evidencia.get('protocolo_valido') is True and evidencia.get('muestras',0)>0
            and evidencia.get('incorrectas_aceptadas')==0 and evidencia.get('correctas_aceptadas',0)>0)


def acepta(fila,politica):
    return (politica is not None and fila['best_score']>=politica['threshold']
            and fila['margin']>=politica['margin'])


def metricas(filas,politica=None):
    resultado={'muestras':len(filas),'correctas_argmax':0,'correctas_aceptadas':0,
               'incorrectas_aceptadas':0,'rechazadas':0,'por_clase':{},'confusiones':[]}
    for f in filas:
        correcta=f['best_class']==f['real'];ok=acepta(f,politica)
        resultado['correctas_argmax']+=int(correcta)
        clave='correctas_aceptadas' if ok and correcta else 'incorrectas_aceptadas' if ok else 'rechazadas'
        resultado[clave]+=1
        c=resultado['por_clase'].setdefault(f['real'],{'muestras':0,'correctas_aceptadas':0,'incorrectas_aceptadas':0,'rechazadas':0})
        c['muestras']+=1;c[clave]+=1
        if not correcta:resultado['confusiones'].append({k:f.get(k) for k in ('archivo','real','best_class','best_score','second_class','second_score','margin')}|{'aceptada':bool(ok)})
    resultado['accuracy_argmax']=resultado['correctas_argmax']/len(filas) if filas else None
    return resultado


def buscar_politica(filas):
    """Solo consulta calibración; los datos de evaluación nunca eligen parámetros."""
    if not filas:raise ValueError('No hay imágenes de calibración utilizables.')
    thresholds=sorted({f['best_score'] for f in filas}|{float(np.nextafter(f['best_score'],1.0)) for f in filas})
    margenes=sorted({f['margin'] for f in filas}|{float(np.nextafter(f['margin'],1.0)) for f in filas})
    candidatas=[]
    for t in thresholds:
        for m in margenes:
            if not 0<t<1 or not 0<m<1:continue
            politica={'threshold':t,'margin':m};r=metricas(filas,politica)
            if r['incorrectas_aceptadas']==0 and r['correctas_aceptadas']>=math.ceil(len(filas)/2):
                candidatas.append((r['correctas_aceptadas'],m,t,politica))
    if not candidatas:raise ValueError('Los scores y márgenes de calibración no separan los errores con cobertura suficiente.')
    return max(candidatas,key=lambda p:p[:3])[3]


class EvidenciaCNN:
    def __init__(self,ventana=5,minimo=4,ttl=2.0,validador=None):
        self.historial=deque(maxlen=ventana);self.minimo=minimo;self.ttl=ttl
        self.validador=validador or parametros_validos
    def limpiar(self):self.historial.clear()
    def actualizar(self,fila,politica,ahora):
        if not self.validador(politica):
            self.limpiar();return 'CNN_NO_CALIBRADA',None
        while self.historial and ahora-self.historial[0][0]>self.ttl:self.historial.popleft()
        valida=acepta(fila,politica)
        self.historial.append((ahora,fila['best_class'] if valida else None))
        votos=Counter(s for _,s in self.historial if s is not None)
        candidata,n=votos.most_common(1)[0] if votos else (None,0)
        # Una predicción reciente ambigua o contraria revoca inmediatamente la identidad.
        if valida and candidata==fila['best_class'] and len(self.historial)==self.historial.maxlen and n>=self.minimo:
            return 'RECONOCIDO',candidata
        return ('DESCONOCIDO' if len(self.historial)==self.historial.maxlen and not valida else 'VERIFICANDO'),None
