"""Inventario y retiro reversible exclusivamente de caches regenerables locales.

No importa la aplicacion, no conecta SQL, no lee .env y no cambia codigo existente.
"""
import argparse
import ast
from collections import Counter, defaultdict
import csv
from datetime import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {'.git', '.venv', 'venv', '.aws', '.agents', '.codex', 'backups',
    'backup', 'respaldos', 'node_modules', 'dataset',
    'respaldos_inventario', 'modelos', 'modelos_voz', 'rostros_temp', 'rostros',
    'clasificacion', 'datasets', 'embeddings', 'cnn_muestras', 'migrations',
    'sql', 'outputs', 'logs', 'reportes_exportados', 'cache_voz'}
CACHES = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
SKIP_ANALYSIS = PROTECTED-{'modelos', 'modelos_voz', 'migrations', 'sql'}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def scan():
    rows, errors = [], []
    def walk(folder):
        try:
            with os.scandir(folder) as entries:
                for entry in sorted(entries, key=lambda e:e.name.lower()):
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        link = entry.is_symlink() or getattr(info,'st_reparse_tag',0) in (0xA0000003,0xA000000C)
                        directory = entry.is_dir(follow_symlinks=False)
                        rows.append(dict(path=path.relative_to(ROOT).as_posix(),
                            kind='link' if link else 'directory' if directory else 'file',
                            bytes=0 if directory else info.st_size, mtime_ns=info.st_mtime_ns))
                        if directory and not link: walk(path)
                    except OSError as error: errors.append(dict(path=path.relative_to(ROOT).as_posix(),error=type(error).__name__))
        except OSError as error:errors.append(dict(path=folder.relative_to(ROOT).as_posix(),error=type(error).__name__))
    walk(ROOT)
    return rows, errors


def protected(path):
    parts = {p.lower() for p in path.parts}
    return bool(parts & PROTECTED) or path.name == '.env'


def removable(path):
    if protected(path): return False
    if any(p in CACHES-{'__pycache__'} for p in path.parts): return True
    if path.suffix.lower() in ('.pyc','.pyo'):
        if path.parent.name == '__pycache__':
            source = path.parent.parent/(path.name.split('.')[0]+'.py')
        else: source=path.with_suffix('.py')
        return source.is_file()
    return path.name in ('Thumbs.db','.DS_Store')


def classify(path, kind, reachable):
    top = path.parts[0].lower()
    if kind == 'link':return 'UNKNOWN'
    if top in ('backups','respaldos_inventario'):return 'BACKUP'
    if top in ('.venv','venv','node_modules'):return 'SUPPORT'
    if top in ('.git','.vscode','.agents','.codex','.aws'):return 'DEVELOPMENT'
    if any(p in CACHES for p in path.parts) or path.suffix in ('.pyc','.pyo'):return 'CACHE'
    if top=='cache_voz':return 'CACHE'
    if top=='pruebas' or top=='tests':return 'TEST'
    if top=='migrations':return 'MIGRATION'
    if top in ('outputs','logs','reportes_exportados'):return 'GENERATED'
    if top in ('docs',) or path.suffix.lower() in ('.md','.docx','.pdf'):return 'DOCUMENTATION'
    if top=='verificacion_ui':return 'DIAGNOSTIC' if path.suffix=='.py' else 'GENERATED'
    if top=='herramientas':return 'MIGRATION' if path.name.startswith(('migrar_','retirar_acceso','reorganizar_estantes','normalizar_historial')) else 'DIAGNOSTIC'
    if path.name.startswith(('diagnostico_','calibracion_')):return 'DIAGNOSTIC'
    if path.as_posix() in reachable:return 'PRODUCTION'
    if top in ('modelos','modelos_voz','rostros','rostros_temp','clasificacion','datasets','cnn_muestras','embeddings','sql','arduino'):return 'SUPPORT'
    if path.name=='__init__.py' or path.suffix.lower() in ('.json','.ini','.toml','.cfg','.txt','.editorconfig') or path.name in ('.env','.gitignore','.editorconfig'):return 'SUPPORT'
    return 'UNKNOWN'


def analyze(rows):
    own = [r for r in rows if r['kind']=='file' and Path(r['path']).parts[0].lower() not in SKIP_ANALYSIS
           and not any(p in CACHES for p in Path(r['path']).parts)]
    sources = {r['path']:ROOT/r['path'] for r in own if Path(r['path']).suffix=='.py'}
    module_paths={p[:-3].replace('/','.'):p for p in sources}
    module_paths.update({p[:-12].replace('/','.'):p for p in sources if p.endswith('/__init__.py')})
    edges, external, dynamic, launchers, errors = defaultdict(set), defaultdict(set), [], [], []
    literals={}; references=defaultdict(set); texts={}
    for name,path in sources.items():
        try:tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        except (OSError,SyntaxError,UnicodeError) as error:errors.append({'path':name,'error':type(error).__name__});continue
        literals[name]=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        texts[name]='\n'.join(literals[name]).lower().replace('\\','/')
        for node in ast.walk(tree):
            modules=[]
            if isinstance(node,ast.Import):modules=[a.name for a in node.names]
            if isinstance(node,ast.ImportFrom):
                base=node.module or ''
                if node.level:
                    package=name.split('/')[:-1]
                    base='.'.join(package[:len(package)-node.level+1]+([base] if base else []))
                modules=[base]+[base+'.'+a.name for a in node.names]
            for module in modules:
                if module in module_paths:edges[name].add(module_paths[module])
                elif module:external[name].add(module)
            if isinstance(node,ast.Call):
                func=ast.unparse(node.func)
                if any(key in func for key in ('import_module','__import__','subprocess','open','Path','load','read_')):
                    dynamic.append({'path':name,'line':node.lineno,'call':func[:120]})
                    if ('import_module' in func or '__import__' in func) and node.args and isinstance(node.args[0],ast.Constant):
                        target=module_paths.get(node.args[0].value)
                        if target:edges[name].add(target)
            if isinstance(node,ast.Compare) and isinstance(node.left,ast.Name) and node.left.id=='__name__':
                if any(isinstance(v,ast.Constant) and v.value=='__main__' for v in node.comparators):launchers.append(name)
    for row in own:
        p=ROOT/row['path']
        if p.suffix.lower() in ('.json','.md','.txt','.sql','.ino') and row['bytes']<2_000_000:
            try:texts[row['path']]=p.read_text(encoding='utf-8-sig').lower().replace('\\','/')
            except (OSError,UnicodeError):pass
    names=defaultdict(list)
    for row in own:names[Path(row['path']).name.lower()].append(row['path'])
    for name,content in texts.items():
        for basename,paths in names.items():
            if len(basename)>3 and basename in content:
                for p in paths:
                    if p!=name:references[p].add(name)
    reachable=set();todo=['main.py']
    while todo:
        item=todo.pop()
        if item in reachable:continue
        reachable.add(item);todo.extend(edges[item]-reachable)
    hashes={name:digest(path) for name,path in sources.items()}
    # Small configuration/SQL documents are fingerprinted without exposing contents.
    for row in own:
        if Path(row['path']).suffix.lower() in ('.json','.sql','.ino'):
            hashes[row['path']]=digest(ROOT/row['path'])
    groups=defaultdict(list)
    for name,value in hashes.items():groups[value].append(name)
    duplicates=[{'sha256':value,'paths':paths,'decision':'CONSERVAR',
                 'reason':'Igualdad de contenido no demuestra equivalencia de uso/rutas.'}
                for value,paths in groups.items() if len(paths)>1]
    return reachable,references,hashes,dict(imports={k:sorted(v) for k,v in edges.items()},
        imports_externos={k:sorted(v) for k,v in external.items()},launchers=sorted(set(launchers)),
        entrypoint='main.py',reachable=sorted(reachable),dynamic_access=dynamic,
        references={k:sorted(v) for k,v in references.items()},duplicates=duplicates,errors=errors,
        limitation='Grafo estatico conservador; nombres calculados/callbacks y recursos externos no prueban ausencia de uso.')


def inventory():
    rows, errors=scan()
    reachable, references, hashes, graph=analyze(rows)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output=ROOT/'outputs/limpieza_conservadora'/stamp
    output.mkdir(parents=True,exist_ok=False)
    candidates=[];manual=[];counts=Counter()
    fields=['path','kind','bytes','category','decision','reason','references']
    with gzip.open(output/'inventario_completo.csv.gz','wt',encoding='utf-8-sig',newline='') as complete, \
         (output/'inventario_proyecto.csv').open('w',encoding='utf-8-sig',newline='') as project:
        writers=[csv.DictWriter(f,fields) for f in (complete,project)]
        for writer in writers:writer.writeheader()
        for row in rows:
            path=Path(row['path']);category=classify(path,row['kind'],reachable)
            decision='CONSERVAR';reason='Sin evidencia suficiente para modificar; se conserva ubicacion y contenido.'
            if row['kind']=='file' and removable(path) and not (ROOT/path).is_symlink():
                decision='ELIMINAR_SEGURO';reason='Cache regenerable, fuera de las areas protegidas; se respalda antes.'
                candidates.append(dict(row,sha256=digest(ROOT/path)))
            elif category=='UNKNOWN':
                decision='REVISAR_MANUALMENTE';manual.append(row['path'])
            if path.parts[0].lower()=='cache_voz':reason='Audio reutilizado sin red; conservar para mantener disponibilidad y latencia.'
            if protected(path):reason='Area protegida por alcance; no mover ni eliminar.'
            refs=len(references.get(row['path'],()))
            result={k:row[k] for k in ('path','kind','bytes')}
            result.update(category=category,decision=decision,reason=reason,references=refs)
            writers[0].writerow(result)
            if path.parts[0].lower() not in ('.venv','venv','.git'):writers[1].writerow(result)
            counts[category]+=1
    sizes=Counter()
    for r in rows:
        if r['kind']=='file':sizes[Path(r['path']).parts[0]]+=r['bytes']
    plan=dict(created_at=datetime.now().astimezone().isoformat(),workspace=str(ROOT),
        total_bytes=sum(r['bytes'] for r in rows if r['kind']=='file'),files=sum(r['kind']=='file' for r in rows),
        directories=sum(r['kind']=='directory' for r in rows),classification=dict(counts),
        top_level_bytes=dict(sizes),candidates=candidates,candidate_bytes=sum(r['bytes'] for r in candidates),
        cache_directories=[r['path'] for r in rows if r['kind']=='directory' and Path(r['path']).name in CACHES and not protected(Path(r['path']))],
        fingerprints=hashes,manual_review=manual,errors=errors,
        decisions={'ELIMINAR_SEGURO':[r['path'] for r in candidates],'MOVER_SEGURO':[],
                   'CONSERVAR':'Todos los demas archivos clasificados, incluyendo datos, modelos, entornos, evidencias y respaldos.',
                   'REVISAR_MANUALMENTE':manual})
    dump(output/'plan.json',plan);dump(output/'dependencias.json',graph)
    print(json.dumps({'report':output.relative_to(ROOT).as_posix(),'files':plan['files'],
        'bytes':plan['total_bytes'],'candidates':len(candidates),'candidate_bytes':plan['candidate_bytes'],
        'scan_errors':len(errors),'reachable_modules':len(reachable)},ensure_ascii=False))


def checked_path(relative):
    path=ROOT/relative
    resolved=path.resolve(strict=True)
    if ROOT not in resolved.parents or protected(Path(relative)) or path.is_symlink():
        raise RuntimeError('Ruta fuera del alcance permitido: '+relative)
    # Every ancestor must also remain a real workspace directory.
    for parent in path.parents:
        if parent==ROOT:break
        if parent.is_symlink() or parent.resolve()!=parent:raise RuntimeError('Ruta indirecta: '+relative)
    return path


def apply(output):
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    if (output/'aplicacion.json').exists():raise RuntimeError('Este lote ya se proceso.')
    baseline=output/'antes/outputs/eventos/regresion.json'
    if not baseline.is_file() or not json.loads(baseline.read_text(encoding='utf-8'))['exito']:
        raise RuntimeError('Se requiere una regresion previa satisfactoria en la carpeta antes.')
    paths=[]
    for item in plan['candidates']:
        path=checked_path(item['path'])
        if not removable(Path(item['path'])) or digest(path)!=item['sha256']:raise RuntimeError('El candidato cambio: '+item['path'])
        paths.append((path,item))
    backup=ROOT/'backups/limpieza_conservadora'/output.name
    backup.mkdir(parents=True,exist_ok=False)
    archive=backup/'archivos_retirados.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for path,item in paths:z.write(path,item['path'])
        z.writestr('MANIFIESTO_LIMPIEZA.json',json.dumps(plan,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('El respaldo no supera CRC.')
        for _,item in paths:
            if hashlib.sha256(z.read(item['path'])).hexdigest()!=item['sha256']:raise RuntimeError('Respaldo incompleto.')
    removed=[];folders=[]
    dump(output/'respaldo.json',{'archive':archive.relative_to(ROOT).as_posix(),'verified':True,'sha256':digest(archive)})
    # Journal each deletion; no wildcard/recursive removal or shell crossing.
    for path,item in paths:
        if digest(path)!=item['sha256']:raise RuntimeError('El archivo cambio despues del respaldo.')
        path.unlink();removed.append(item['path'])
        dump(output/'aplicacion.json',{'deleted':removed,'directories':folders,'backup':archive.relative_to(ROOT).as_posix()})
    for relative in sorted(plan['cache_directories'],key=lambda p:len(Path(p).parts),reverse=True):
        directory=checked_path(relative)
        if not any(directory.iterdir()):directory.rmdir();folders.append(relative)
    dump(output/'aplicacion.json',{'deleted':removed,'directories':folders,'backup':archive.relative_to(ROOT).as_posix(),
        'removed_bytes':sum(i['bytes'] for _,i in paths),'moved':[],'imports_removed':[],'debug_removed':[],
        'duplicates_removed':[],'functional_source_changes':False})
    print(json.dumps({'deleted_files':len(removed),'deleted_directories':len(folders),'removed_bytes':sum(i['bytes'] for _,i in paths),
                      'backup':archive.relative_to(ROOT).as_posix()},ensure_ascii=False))


def verify(output):
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    rows,errors=scan()
    changed=[p for p,h in plan['fingerprints'].items() if not (ROOT/p).is_file() or digest(ROOT/p)!=h]
    deleted=json.loads((output/'aplicacion.json').read_text(encoding='utf-8'))
    result=dict(total_bytes_before=plan['total_bytes'],total_bytes_after=sum(r['bytes'] for r in rows if r['kind']=='file'),
        removed_bytes=deleted['removed_bytes'],fingerprinted_files=len(plan['fingerprints']),changed_files=changed,
        selected_files_absent=all(not (ROOT/p).exists() for p in deleted['deleted']),scan_errors=errors,
        remaining_removable=[r['path'] for r in rows if r['kind']=='file' and removable(Path(r['path']))],
        protected_areas='Sin eliminaciones ni movimientos; modelos, datos, entornos, logs, cache de voz y respaldos conservados.')
    dump(output/'verificacion.json',result)
    print(json.dumps(result,ensure_ascii=False))
    if changed or errors:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventariar','limpiar','verificar'])
    parser.add_argument('--informe',type=Path)
    args=parser.parse_args()
    if args.action=='inventariar':inventory()
    else:
        if not args.informe:parser.error('--informe es obligatorio')
        destination=args.informe.resolve()
        if (ROOT/'outputs/limpieza_conservadora') not in destination.parents:parser.error('Carpeta de informe fuera del workspace')
        (apply if args.action=='limpiar' else verify)(destination)
