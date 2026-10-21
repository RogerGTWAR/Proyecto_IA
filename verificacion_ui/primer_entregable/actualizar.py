from pathlib import Path
from zipfile import ZipFile
from lxml import etree
import hashlib, json, copy

BASE=Path(__file__).resolve().parent
SOURCE=Path(r'C:\Users\rpere\Downloads\Primer Entregable IA 1.0.docx')
DEST=BASE.parents[1]/'Primer_Entregable_IA_Actualizado.docx'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
def tag(t): return '{'+NS['w']+'}'+t
sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
with ZipFile(SOURCE) as z:
    parts={i.filename:z.read(i.filename) for i in z.infolist()}
root=etree.fromstring(parts['word/document.xml'])
body=root.find('w:body',NS)
paragraphs=list(body)
updates={
38:'La gestión del inventario es necesaria para organizar los repuestos, herramientas, lubricantes y materiales utilizados en un taller de mecánica. Conocer las cantidades disponibles, su ubicación y los movimientos realizados permite al responsable del almacén revisar la información antes de atender las necesidades de mantenimiento y reparación. El proyecto conserva este enfoque y reúne el control operativo y el análisis de los registros en una misma aplicación.',
40:'El Sistema Inteligente para la Gestión y Análisis de Inventario en Almacenes mediante Inteligencia Artificial dispone actualmente de una aplicación de escritorio desarrollada en Python, con interfaz Tkinter y ttkbootstrap y almacenamiento en SQL Server. Permite administrar productos y empleados, registrar entradas, salidas, transferencias y ajustes, consultar historial y alertas, realizar conteos de inventario y generar reportes. Las existencias se almacenan por producto y ubicación; el stock total se obtiene sumando las cantidades correspondientes.',
42:'Sobre esta base se integran el mapa lógico del almacén, el reconocimiento facial y JARVIS como asistente central para consultas escritas y por voz. El asistente utiliza las mismas funciones de inventario, ubicaciones y análisis que las pantallas. La predicción estima la duración del stock a partir del consumo registrado, mientras que la detección de anomalías señala cantidades que se apartan de los movimientos históricos habituales. Estos resultados apoyan la revisión del personal responsable y no sustituyen sus decisiones.',
44:'CRISP-DM se mantiene como metodología para relacionar la comprensión del negocio, la comprensión y preparación de los datos, el modelado, la evaluación y el despliegue. Al 4 de octubre de 2026, el proyecto cuenta con funciones implementadas y datos de demostración identificados. La calibración facial y la evaluación de las estimaciones en condiciones reales continúan pendientes; por ello, no se atribuyen al sistema resultados experimentales de precisión, alcance físico o reducción de tiempos.',
50:'El primer entregable planteó la necesidad de centralizar la información del almacén de un taller de mecánica y aprovechar los registros operativos para su análisis. El segundo entregable desarrolló la comprensión del negocio y de los datos bajo CRISP-DM. Ambos documentos constituyen los antecedentes académicos del sistema actual y mantienen como problema principal el control de existencias, la localización de productos y la trazabilidad de los movimientos.',
52:'La implementación actual organiza productos, categorías, unidades, ubicaciones, empleados y movimientos en SQL Server. A diferencia de un registro aislado de cantidades, conserva existencias por ubicación y relaciona cada operación con sus datos de fecha, producto, cantidad y empleado responsable. Una transferencia redistribuye el stock entre ubicaciones sin representar consumo global. El mapa consulta estas relaciones para mostrar dónde se encuentran los productos, incluyendo los que están distribuidos en varias ubicaciones.',
54:'El análisis del inventario utiliza el historial disponible. La predicción principal calcula el consumo promedio diario a partir de salidas y estima cobertura, tendencia y riesgo cuando existen datos suficientes. La detección de anomalías compara cantidades con antecedentes del mismo producto y tipo de movimiento. Aunque los objetivos académicos contemplan evaluar Machine Learning, los motores operativos actuales emplean métodos estadísticos explicables; su disponibilidad no demuestra que ya se haya completado una evaluación experimental de modelos supervisados y no supervisados.',
56:'En visión artificial, el pipeline principal utiliza YuNet para detectar rostros y SFace para obtener embeddings, con alineación, evaluación de calidad y seguimiento temporal. La CNN anterior permanece como alternativa separada. JARVIS integra consultas en lenguaje natural y contexto de conversación; la voz utiliza Vosk y sounddevice para reconocimiento y captura, y Edge TTS con alternativa local pyttsx3 para síntesis. Las consultas habladas y escritas comparten el mismo procesamiento y no registran entradas ni salidas automáticamente.',
58:'El proyecto ha avanzado desde la propuesta inicial hacia un prototipo integrado con inventario, mapa, análisis y asistencia conversacional. Los datos de demostración permiten observar sus flujos, pero no representan consumo observado del taller. La validación del reconocimiento facial, del comportamiento predictivo y de los dispositivos en el almacén sigue siendo necesaria antes de atribuir beneficios operativos medidos o considerar concluido el despliegue.',
60:'El almacén de un taller de mecánica requiere mantener disponibles repuestos, herramientas y materiales distribuidos en distintas ubicaciones. Cuando la información se encuentra dispersa o se actualiza sin relacionar producto, cantidad y ubicación, resulta difícil conocer el stock total y localizar los artículos necesarios. También pueden producirse diferencias entre las cantidades registradas y el conteo físico, por lo que se requiere un procedimiento que permita identificarlas y corregirlas conservando el historial de ajustes.',
62:'La trazabilidad exige conocer qué producto ingresó, salió o fue transferido, en qué cantidad, cuándo ocurrió y qué empleado fue responsable. El sistema actual conserva estas relaciones en los movimientos y permite consultarlas en el historial. El reconocimiento facial aporta un mecanismo complementario de identificación de empleados inscritos, pero todavía requiere calibración y validación en condiciones reales. La existencia del módulo facial no significa que todos los movimientos estén vinculados automáticamente a un reconocimiento biométrico.',
64:'El historial también puede apoyar el seguimiento del consumo y la revisión de cantidades inusuales. Para ello deben diferenciarse las salidas de las entradas, transferencias y ajustes: una transferencia entre ubicaciones no reduce el inventario global. Un historial escaso o compuesto por datos simulados limita la evaluación de las estimaciones. Los avisos de anomalías señalan operaciones que necesitan revisión, sin demostrar fraude ni establecer por sí solos la causa de una diferencia.',
66:'La necesidad del proyecto consiste en integrar el control operativo del inventario con la consulta y el análisis de sus registros. La aplicación actual aborda esta necesidad mediante SQL Server, una interfaz común, el mapa y JARVIS. El problema conserva además una dimensión pendiente: comprobar con registros observados, muestras faciales independientes y equipos del almacén que la información y las estimaciones resulten útiles en la operación cotidiana, manteniendo la supervisión del responsable.',
103:'El proyecto se justifica por la necesidad de mantener información organizada sobre los productos, sus existencias y sus ubicaciones en el almacén de un taller de mecánica. La aplicación actual centraliza estos registros y permite gestionar entradas, salidas, transferencias, ajustes y conteos. El control por producto y ubicación proporciona una base para revisar la disponibilidad total y su distribución. El manejo de lotes y vencimientos, cuando corresponde, complementa la consulta de existencias sin reemplazar la verificación física.',
104:'La relación entre movimientos y empleados responsables facilita la revisión de las operaciones y de las diferencias detectadas durante el conteo. Los registros del historial, las alertas y los reportes permiten consultar la información desde distintas perspectivas. El reconocimiento facial puede complementar la identificación operativa de empleados inscritos; su uso debe depender de una calibración válida y de pruebas con la cámara del almacén. Esta función no sustituye la supervisión del responsable ni garantiza por sí sola la atribución correcta de cada movimiento.',
105:'JARVIS facilita el acceso a la información mediante consultas escritas y por voz. Puede responder sobre existencias, ubicaciones, movimientos, predicción y anomalías, conservar contexto para preguntas posteriores y solicitar aclaraciones cuando hay productos similares. Su integración con el mapa permite localizar las ubicaciones asociadas a una consulta. El asistente obtiene sus respuestas de las mismas funciones y datos utilizados por la interfaz, por lo que no debe producir cantidades o ubicaciones que no estén registradas.',
106:'El análisis histórico aporta estimaciones de consumo y cobertura que pueden orientar la revisión del abastecimiento. También permite señalar cantidades inusuales mediante comparaciones con antecedentes del mismo producto y tipo de movimiento. Son resultados aproximados que requieren datos suficientes e interpretación del personal encargado. La historia de demostración sirve para comprobar los flujos, pero no acredita precisión predictiva ni beneficios medidos en el taller. La evaluación con registros observados continúa formando parte del trabajo pendiente.',
107:'Desde el punto de vista académico, el proyecto articula programación, bases de datos, visión artificial, procesamiento del lenguaje natural y análisis del inventario bajo CRISP-DM. Mantener la relación entre objetivos, datos, implementación y evaluación permite distinguir avances funcionales de resultados todavía no comprobados. La contribución actual es un prototipo integrado que ofrece una base para realizar validaciones posteriores. La evaluación de técnicas de Machine Learning y de la operación en condiciones reales debe completarse antes de afirmar el cumplimiento experimental de todos los objetivos.'
}
def replace_text(p,text):
    nodes=p.xpath('.//w:t',namespaces=NS)
    assert nodes
    nodes[0].text=text
    for x in nodes[1:]:x.text=''
updates[107]='Desde el punto de vista académico, el proyecto articula programación, bases de datos, visión artificial, lenguaje natural y análisis del inventario bajo CRISP-DM. Su contribución actual es un prototipo integrado. La evaluación experimental de Machine Learning y la validación operativa siguen pendientes para comprobar el cumplimiento de los objetivos.'
for i,text in updates.items():replace_text(paragraphs[i],text)
# Preserve the original cover shapes, all team names, styles and page furniture.
for x in root.xpath('//w:t',namespaces=NS):
    if x.text and 'septiembre de 2026' in x.text:
        x.text=x.text.replace('septiembre de 2026','octubre de 2026')
# Explain the distinction between the retained objectives and validated outcomes.
note=copy.deepcopy(paragraphs[78])
replace_text(note,'Los objetivos se conservan como compromisos del proyecto. La identificación facial no constituye un sistema de acceso: los empleados son registros operativos. La vinculación biométrica de todos los movimientos y la evaluación experimental de técnicas de Machine Learning siguen pendientes. Actualmente, la predicción y las anomalías utilizan principalmente métodos estadísticos sobre el historial disponible.')
body.insert(list(body).index(paragraphs[84])+1,note)
# Replace manual blank-line pagination with explicit chapter breaks.
for element in list(body):
    if element in paragraphs[:37] or element.tag!=tag('p'): continue
    if not element.xpath('.//w:t|.//w:sectPr|.//w:drawing|.//w:br',namespaces=NS):
        body.remove(element)
for i in (49,59,76,102):
    pp=paragraphs[i].find('w:pPr',NS)
    if pp is None:pp=etree.Element(tag('pPr'));paragraphs[i].insert(0,pp)
    br=etree.SubElement(pp,tag('pageBreakBefore'));br.set(tag('val'),'1')
for para in [paragraphs[i] for i in updates]+[note]:
    pp=para.find('w:pPr',NS)
    if pp is None:pp=etree.Element(tag('pPr'));para.insert(0,pp)
    sp=pp.find('w:spacing',NS)
    if sp is None:sp=etree.SubElement(pp,tag('spacing'))
    sp.set(tag('after'),'160')
parts['word/document.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
with ZipFile(DEST,'w') as z:
    for name,data in parts.items():z.writestr(name,data)
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==sha
audit={'reference':str(SOURCE),'sha256':sha,'paragraphs_updated':list(updates),'preserved':'Original cover layout, names, objectives, five chapters, sections, styles, headers, relationships and images; only body prose and cover date changed. One short scope clarification added after objectives.','qa':'Native Word page EMF rendering; packaged LibreOffice unavailable in Windows runtime.'}
(BASE/'artifact.md').write_text('# Primer entregable actualizado\n\n'+json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
print(DEST)
