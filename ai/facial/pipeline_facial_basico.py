from core.formato_numerico import format_numero
"""Depuración directa sin tracking, tiles ni votación. Respeta calibración."""
import time
import numpy as np
from ai.facial.pipeline_facial import PipelineFacial, evaluar_calidad

class PipelineFacialBasico(PipelineFacial):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ultimo_debug = 0

    def procesar(self, frame, empleados=None):
        inicio=time.perf_counter(); resultados=[]
        imprimir=self.cfg.get("debug") and time.monotonic()-self.ultimo_debug>=1
        # Una sola detección global; coordenadas y landmarks en el frame original.
        caras=self.motor._detectar_region(frame)
        for numero,cara in enumerate(caras,1):
            calidad=evaluar_calidad(frame,cara,self.cfg, self.politica["min_rostro"] if self.politica else None)
            vector,alineado=self.motor.extraer(frame,cara)
            subject,score,margen=self.galeria.comparar(vector,empleados)
            sims=self.galeria.vectores@vector
            ranking=sorted([(str(s),float(np.mean(np.sort(sims[self.galeria.subjects==s])[-3:]))) for s in np.unique(self.galeria.subjects)],key=lambda v:v[1],reverse=True)
            threshold=self.politica["threshold"] if self.politica else None
            ok=calidad["valida"] and subject is not None and threshold is not None and score>=threshold and margen>=self.politica["margen"]
            estado="RECONOCIDO" if ok else calidad["estado"] if not calidad["valida"] else "BASE_FACIAL_VACIA" if not len(sims) else "SIN_CALIBRAR" if threshold is None else "DESCONOCIDO"
            empleado=(empleados or {}).get(subject,{}) if ok else {}
            r={**calidad,**empleado,"estado":estado,"reconocido":ok,"etiqueta":subject if ok else None,"candidato":subject,
               "confianza":score,"similitud":score,"margen":margen,"threshold":threshold,
               "segundo_score":ranking[1][1] if len(ranking)>1 else None,"embedding_dimension":len(vector),"embedding_norma":float(np.linalg.norm(vector)),
               "track_id":numero,"caja":tuple(map(int,cara[:4])),"tiempo_inferencia_ms":(time.perf_counter()-inicio)*1000,"resolucion":f"{frame.shape[1]}x{frame.shape[0]}"}
            resultados.append(r)
            if imprimir:
                x,y,w,h=r["caja"]
                print("\n----------------------------------------\nFACE DEBUG\n----------------------------------------",flush=True)
                print(f"Rostro detectado: SI | Bounding box: {x},{y},{x+w},{y+h} | Tamaño: {w}x{h}\nDetector: YuNet | Landmarks: SI | Alineación: SI | Color: BGR\nEmbedding: SFace {len(vector)}D | Norma: {format_numero(np.linalg.norm(vector))}\nEmpleados SQL: {len(empleados or {})} | Embeddings: {len(sims)}",flush=True)
                for s,valor in ranking:
                    print(f"{(empleados or {}).get(s,{}).get('nombre',s)}: {format_numero(valor)}",flush=True)
                print(f"BEST MATCH: {subject} | BEST SCORE: {format_numero(score)} | SECOND BEST SCORE: {r['segundo_score']}\nMargen: {format_numero(margen)} | Threshold: {threshold} | Calidad: {calidad['estado']}\nResultado: {estado}",flush=True)
        if imprimir:
            self.ultimo_debug=time.monotonic()
        return resultados
