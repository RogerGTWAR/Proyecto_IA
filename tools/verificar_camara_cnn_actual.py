"""Verifica cámara CNN provisional sin guardar imágenes ni consultar identidades SQL."""
from pathlib import Path
import sys
import time
import json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai.facial import reconocimiento_cnn as cnn


class Presentador:
    cierre_solicitado=False
    def __init__(self):self.inicio=None;self.frames=0;self.estados=set();self.info={}
    def publicar_frame(self,frame):
        ahora=time.monotonic()
        if self.inicio is None:self.inicio=ahora
        self.frames+=1
        if ahora-self.inicio>=8:cnn.detener_reconocimiento()
    def publicar_info(self,**info):
        self.info=info;self.estados.add(info.get('estado'))


if __name__=='__main__':
    p=Presentador()
    with patch.object(cnn,'obtener_cache_empleados_por_subject',side_effect=AssertionError('SQL no permitido')) as sql,\
         patch.object(cnn,'resolver_etiqueta',side_effect=AssertionError('Sin resolución SQL')) as resolver,\
         patch.object(cnn.ControlAlertaDesconocido,'procesar',side_effect=AssertionError('Sin alertas SQL')) as alertas:
        ultimo=cnn.reconocer_con_camara(motor='cnn',modo_cnn='Dataset actual',presentador=p)
        resultado={'frames_mostrados':p.frames,'duracion_s':time.monotonic()-p.inicio if p.inicio else 0,
            'fps_video':ultimo.get('fps_video'),'fps_cnn':ultimo.get('fps_cnn'),
            'inferencias_ms_promedio':ultimo.get('latencia_cnn_ms_promedio'),
            'estados_observados':sorted(s for s in p.estados if s),'estado_final':ultimo.get('estado'),
            'subject_final':ultimo.get('etiqueta'),'consultas_sql':sql.call_count,
            'resoluciones_empleado':resolver.call_count,'alertas_sql':alertas.call_count,
            'imagenes_guardadas':0,'nota':'Comprobación de cámara disponible; no mide accuracy con personas ni distancia de reconocimiento.'}
        Path('evaluacion_facial/cnn/camara_dataset_actual.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(resultado,ensure_ascii=False,indent=2))
