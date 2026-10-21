"""Read-only, chronological consultation of technical JSONL traces."""
import argparse
import json
from pathlib import Path


def consultar(args):
    path = Path(args.archivo)
    paths = sorted(path.parent.glob(path.name+'.*'))+[path]
    rows = []
    for candidate in paths:
        if not candidate.is_file(): continue
        with candidate.open(encoding='utf-8') as stream:
            for line in stream:
                try: row = json.loads(line)
                except (ValueError, TypeError): continue
                filters = {'correlation_id':args.correlation, 'source':args.source,
                           'action':args.action, 'status':args.status,
                           'entity_code':args.entity_code, 'category':args.category}
                if any(value and row.get(key) != value for key, value in filters.items()): continue
                stamp = row.get('timestamp', '')
                if args.desde and stamp < args.desde: continue
                if args.hasta and stamp > args.hasta: continue
                rows.append(row)
    rows.sort(key=lambda row:row.get('timestamp', ''))
    for row in rows:
        if args.json: print(json.dumps(row, ensure_ascii=False))
        else:
            print('{timestamp} {source:12} {action:30} {status:22} correlation={correlation_id} operation={operation_id} parent={parent_operation_id}'.format(**row))
            if row.get('before') or row.get('after'): print('  {} -> {}'.format(row.get('before'), row.get('after')))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archivo', default=str(Path(__file__).resolve().parents[1]/'logs/audit.jsonl'))
    for name in ('correlation', 'source', 'action', 'status', 'entity-code', 'category', 'desde', 'hasta'):
        parser.add_argument('--'+name)
    parser.add_argument('--json', action='store_true')
    consultar(parser.parse_args())
