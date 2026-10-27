"""Manual local backup/empty-destination restore; no paid backup service."""
import argparse,json
from pathlib import Path
from .firestore_store import FirestoreStore,State,COLLECTIONS
from .firestore_migrate import import_state

def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['export','restore']);parser.add_argument('path');args=parser.parse_args()
    store=FirestoreStore();path=Path(args.path)
    if args.operation=='export':
        if path.exists():raise RuntimeError('Backup target exists; choose a new filename')
        state=store.snapshot(COLLECTIONS);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'schema_version':3,'collections':state},ensure_ascii=False,indent=2),encoding='utf8')
        print('Backup saved locally. Protect this file: it contains personal records and password hashes. Attachment bytes are separate.')
    else:
        payload=json.loads(path.read_text(encoding='utf-8-sig'))
        if payload.get('schema_version')!=3 or set(payload['collections'])!=set(COLLECTIONS):raise RuntimeError('Unsupported backup schema')
        print('Restored documents:',import_state(store,State(payload['collections'])))
if __name__=='__main__':main()
