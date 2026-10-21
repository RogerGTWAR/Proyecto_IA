from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import json
BASE=Path(__file__).resolve().parent
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
for n,nombre in enumerate(('Primer Entregable IA 1.0.docx','Borrador del segundo entregable (1) (1).docx'),1):
    ruta=Path('C:/Users/rpere/Downloads')/nombre
    with ZipFile(ruta) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        texto=[]
        for i,p in enumerate(root.findall('.//w:body//w:p',NS),1):
            s=p.find('./w:pPr/w:pStyle',NS); estilo=s.attrib.get('{'+NS['w']+'}val','') if s is not None else ''
            t=''.join(e.text or '' for e in p.findall('.//w:t',NS))
            if t: texto.append(f'{i:04} [{estilo}] {t}')
        (BASE/f'referencia_{n}.txt').write_text('\n'.join(texto),encoding='utf-8')
        print(nombre,len(texto),'párrafos',sum(len(t) for t in texto),'caracteres')
        imagenes=[info for info in z.infolist() if info.filename.startswith('word/media/')]
        for j,info in enumerate(imagenes):
            (BASE/f'ref{n}_{j}{Path(info.filename).suffix}').write_bytes(z.read(info.filename))
        print('Imágenes:',[(info.filename,info.file_size) for info in imagenes])
