"""Firestore is the authoritative document store in Firebase mode.

Transactions load only the named collections and write changed documents. This
small-department implementation favors atomic cross-entity validation over read
efficiency; operators must monitor the Spark read quota.
"""
import copy,json,os,re,threading

COLLECTIONS=('users','notices','recipients','attachments','schedules','audit','semesters','groups','courses','assignments','rooms','periods','unavailable','conflicts','login_attempts')

class State(dict):
    def rows(self,col):return list(self.get(col,{}).values())
    def get_row(self,col,id):return self.get(col,{}).get(str(id))
    def insert(self,col,data):
        table=self.setdefault(col,{})
        id=max((int(k) for k in table),default=0)+1
        row={**copy.deepcopy(data),'id':id};table[str(id)]=row;return row

class MemoryStore:
    """Explicit offline contract-test double; never selected in deployment."""
    def __init__(self):self.data={k:{} for k in COLLECTIONS};self.lock=threading.RLock()
    def snapshot(self,names):
        with self.lock:return State({k:copy.deepcopy(self.data[k]) for k in names})
    def get(self,col,id):
        with self.lock:return copy.deepcopy(self.data[col].get(str(id)))
    def atomic(self,names,fn):
        with self.lock:
            state=self.snapshot(names);result=fn(state)
            for k in names:self.data[k]=state[k]
            return copy.deepcopy(result)

class FirestoreStore:
    def __init__(self):
        project=os.environ.get('FIREBASE_PROJECT_ID','')
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',project):raise RuntimeError('Set FIREBASE_PROJECT_ID to the actual Firebase project ID')
        emulator=os.environ.get('FIRESTORE_EMULATOR_HOST')
        if emulator and os.environ.get('ALLOW_FIRESTORE_EMULATOR')!='1':raise RuntimeError('Emulator requires explicit ALLOW_FIRESTORE_EMULATOR=1')
        try:
            import firebase_admin
            from firebase_admin import firestore
        except ImportError as e:raise RuntimeError('Install requirements-firebase.txt before starting Firebase mode') from e
        try:app=firebase_admin.get_app('ba-dms')
        except ValueError:app=firebase_admin.initialize_app(options={'projectId':project},name='ba-dms')
        self.client=firestore.client(app=app);self.firestore=firestore
        self.prefix=os.environ.get('FIREBASE_COLLECTION_PREFIX','ba_dms_')
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,40}',self.prefix):raise RuntimeError('Invalid collection prefix')
    def collection(self,name):
        if name not in COLLECTIONS:raise ValueError('Unknown collection')
        return self.client.collection(self.prefix+name)
    def snapshot(self,names):
        return State({k:{doc.id:doc.to_dict() for doc in self.collection(k).stream()} for k in names})
    def get(self,col,id):
        doc=self.collection(col).document(str(id)).get()
        return doc.to_dict() if doc.exists else None
    def atomic(self,names,fn):
        transaction=self.client.transaction(max_attempts=5)
        @self.firestore.transactional
        def execute(tx):
            before=State({k:{doc.id:doc.to_dict() for doc in tx.get(self.collection(k))} for k in names})
            state=State(copy.deepcopy(before));result=fn(state);writes=[]
            for col in names:
                for key,row in state[col].items():
                    if before[col].get(key)!=row:
                        if len(json.dumps(row,ensure_ascii=False).encode())>750000:raise ValueError('Document too large; reduce plan size')
                        writes.append(('set',self.collection(col).document(key),row))
                for key in before[col].keys()-state[col].keys():writes.append(('delete',self.collection(col).document(key),None))
            if len(writes)>450:raise ValueError('Transaction exceeds 450 changed documents; split the operation')
            for action,ref,row in writes:
                if action=='set':tx.set(ref,row)
                else:tx.delete(ref)
            return result
        return execute(transaction)
