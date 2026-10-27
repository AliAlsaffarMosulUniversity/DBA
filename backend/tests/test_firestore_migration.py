import pytest
from app.firestore_store import MemoryStore,State,COLLECTIONS
from app.firestore_migrate import import_state

def test_one_way_migration_preserves_documents_and_refuses_nonempty_destination():
    state=State({k:{} for k in COLLECTIONS})
    state['users']['1']={'id':1,'name':'Synthetic User','password':'hash','role':'teacher'}
    store=MemoryStore();assert import_state(store,state)==1
    assert store.get('users',1)==state['users']['1']
    with pytest.raises(RuntimeError,match='not empty'):import_state(store,state)
    assert store.get('users',1)==state['users']['1']

def test_document_transaction_rolls_back_validation_failure():
    store=MemoryStore()
    def change(s):
        s.insert('users',{'name':'Must not persist'})
        raise ValueError('Invalid related record')
    with pytest.raises(ValueError):store.atomic(('users',),change)
    assert store.snapshot(('users',)).rows('users')==[]
