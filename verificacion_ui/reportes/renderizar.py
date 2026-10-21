from pathlib import Path
import json,subprocess
from PIL import Image,ImageDraw
base=Path('verificacion_ui/reportes')
exe=r'C:\Users\rpere\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
reports=json.loads((base/'verificacion.json').read_text(encoding='utf-8'))
all_images=[]
for i,r in enumerate(reports):
 prefix=base/f'final_{i:02d}'
 subprocess.run([exe,'-scale-to','1150','-png',str(base/r['pdf']),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 all_images.extend(base/f'{prefix.name}-{p}.png' for p in range(1,r['paginas']+1))
for n in range(0,len(all_images),6):
 group=all_images[n:n+6]; canvas=Image.new('RGB',(1800,3*470),'#e1e5e9');draw=ImageDraw.Draw(canvas)
 for j,p in enumerate(group):
  im=Image.open(p);im.thumbnail((880,440));x=(j%2)*900;y=(j//2)*470
  canvas.paste(im,(x,y+22));draw.text((x+8,y+4),p.stem,fill='black')
 canvas.save(base/f'revision_{n//6:02d}.png')
print('Paginas renderizadas:',len(all_images),'paneles:',(len(all_images)+5)//6)
