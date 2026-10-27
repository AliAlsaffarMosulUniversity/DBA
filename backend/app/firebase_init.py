import os
from .firestore_store import FirestoreStore
from .firebase_api import base_user,audit
from .security import hash_password

def initialize():
    password=os.environ.get('ADMIN_PASSWORD','')
    if len(password)<12:raise RuntimeError('Set ADMIN_PASSWORD (12+ characters)')
    store=FirestoreStore()
    def change(s):
        if s.rows('users'):raise RuntimeError('Destination already contains users; no account or password changed')
        u=s.insert('users',base_user(username=os.environ.get('ADMIN_USERNAME','admin'),name='مدير النظام',password=hash_password(password),active=True,role='admin'))
        audit(s,u,'firestore_initialize');return {'created':1}
    result=store.atomic(('users','audit'),change)
    print('Firestore administrator initialized. No fictional faculty created.')
if __name__=='__main__':initialize()
