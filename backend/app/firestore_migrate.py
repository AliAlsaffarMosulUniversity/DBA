"""Explicit one-way migration from the configured SQL installation to Firestore.

Default is a read-only local dry run. --apply refuses a nonempty destination.
No attachment bytes are sent to Google; retain the original UPLOAD_DIR.
"""
import argparse,json
from sqlalchemy import select
from .db import engine,Base
from . import models
from .firestore_store import COLLECTIONS,State,FirestoreStore

TABLES={'groups':'student_groups','rooms':'classrooms','conflicts':'group_conflicts'}
def export_sql():
    state=State({k:{} for k in COLLECTIONS})
    with engine.connect() as conn:
        for col in COLLECTIONS:
            table=Base.metadata.tables[TABLES.get(col,col)]
            for raw in conn.execute(select(table)).mappings():
                row=dict(raw)
                if col=='schedules':row.update(row.pop('data'))
                state[col][str(row['id'])]=row
    return state
def import_state(store,state):
    count=sum(len(rows) for rows in state.values())
    if count>450:raise RuntimeError('Migration exceeds one atomic batch (450 documents). Split with a separately reviewed migration tool; no partial import attempted.')
    for rows in state.values():
        for row in rows.values():
            if len(json.dumps(row,ensure_ascii=False).encode())>750000:raise RuntimeError('A document exceeds the safe size; no partial import attempted')
    def change(destination):
        if any(destination.rows(k) for k in COLLECTIONS):raise RuntimeError('Destination is not empty; refusing to overwrite or merge')
        destination.update(state);return count
    return store.atomic(COLLECTIONS,change)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    state=export_sql();print('Document counts:',json.dumps({k:len(v) for k,v in state.items()}))
    if not args.apply:print('Dry run only. Nothing uploaded.');return
    print('Migrated documents:',import_state(FirestoreStore(),state))
if __name__=='__main__':main()
