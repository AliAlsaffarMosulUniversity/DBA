import os
import pytest
os.environ.setdefault('JWT_SECRET','test-only-secret-with-more-than-32-characters')
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app.models import User, Recipient
from app.security import hash_password
from app.scheduler import Request, solve

@pytest.fixture(params=['sql','firestore-contract'])
def client(request,tmp_path,monkeypatch):
    if request.param=='firestore-contract':
        from app.firebase_api import create_app,base_user
        from app.firestore_store import MemoryStore
        store=MemoryStore()
        def populate(s):
            for role in ['admin','head','coordinator','teacher','teacher']:
                i=len(s['users'])+1
                s.insert('users',base_user(username=f'u{i}',name=f'User {i}',role=role,active=True,employment='مستمر',password=hash_password('test-password-123')))
        store.atomic(('users',),populate)
        monkeypatch.setenv('UPLOAD_DIR',str(tmp_path/'uploads'))
        with TestClient(create_app(store)) as c:yield c
        return
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine); factory=sessionmaker(engine)
    with factory() as db:
        for i,role in enumerate(['admin','head','coordinator','teacher','teacher'],1):
            db.add(User(id=i,username=f'u{i}',name=f'User {i}',role=role,password=hash_password('test-password-123')))
        db.commit()
    def dep():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=dep
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear(); engine.dispose()
def auth(c,i):
    r=c.post('/api/login',json={'username':f'u{i}','password':'test-password-123'})
    assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}
def test_permissions_and_receipts(client):
    c=client; head=auth(c,2); teacher=auth(c,4); other=auth(c,5)
    assert c.get('/api/teachers').status_code in (401,403)
    assert c.post('/api/login',json={'username':'u4','password':'wrong'}).status_code==401
    data={'title':'Official notice','body':'Read this','recipients':[4]}
    assert c.post('/api/notices',json=data,headers=teacher).status_code==403
    nid=c.post('/api/notices',json=data,headers=head).json()['id']
    assert c.get('/api/notices',headers=other).json()==[]
    assert c.post(f'/api/notices/{nid}/ack',headers=other).status_code==403
    a=c.post(f'/api/notices/{nid}/ack',headers=teacher).json()
    assert a==c.post(f'/api/notices/{nid}/ack',headers=teacher).json()
    rows=c.get(f'/api/notices/{nid}/receipts',headers=head).json()
    assert len(rows)==1 and rows[0]['acknowledged_at']
    assert c.get(f'/api/notices/{nid}/receipts',headers=teacher).status_code==403
    assert c.post('/api/notices',json={**data,'recipients':[999]},headers=head).status_code==422
def test_attachments(client, tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m,'UPLOAD',tmp_path)
    c=client; h=auth(c,2); t=auth(c,4); o=auth(c,5)
    nid=c.post('/api/notices',json={'title':'Files','body':'Body','recipients':[4]},headers=h).json()['id']
    assert c.post(f'/api/notices/{nid}/attachments',files={'file':('x.exe',b'x')},headers=h).status_code==415
    assert c.post(f'/api/notices/{nid}/attachments',files={'file':('x.txt',b'x')},headers=t).status_code==403
    r=c.post(f'/api/notices/{nid}/attachments',files={'file':('../../x.txt',b'hello')},headers=h)
    assert r.status_code==201
    aid=r.json()['id']
    assert c.get(f'/api/attachments/{aid}',headers=t).content==b'hello'
    assert c.get(f'/api/attachments/{aid}',headers=o).status_code==403
    assert c.post(f'/api/notices/{nid}/attachments',files={'file':('x.txt',b'x'*(5*1024*1024+1))},headers=h).status_code==413
def request(kind='weekly'):
    return Request(kind=kind,days=10 if kind=='exam' else 5,periods=8,rooms=[{'id':'R1','capacity':40},{'id':'R2','capacity':60}],lessons=[{'id':str(i),'title':'Course','teacher':i%3+2,'group':str(i%4),'shift':'morning' if i%2==0 else 'evening','size':35,'duration':2,'blocked':[0,1]} for i in range(16)])
def validate(req, result):
    assert result['status'] in ('OPTIMAL','FEASIBLE')
    entries=result['entries']; assert len(entries)==len(req.lessons)
    for a in entries:
        assert a['period']+a['duration']<=req.periods
        assert next(r.capacity for r in req.rooms if r.id==a['room'])>=a['size']
        assert not set(range(a['day']*req.periods+a['period'],a['day']*req.periods+a['period']+a['duration'])) & set(a['blocked'])
        if req.kind=='weekly':
            assert a['period']+a['duration']<=req.periods//2 if a['shift']=='morning' else a['period']>=req.periods//2
        for b in entries:
            if a['id']==b['id']:continue
            if req.kind=='exam' and a['group']==b['group']: assert abs(a['day']-b['day'])>=req.exam_gap_days+1
            overlap=a['day']==b['day'] and a['period']<b['period']+b['duration'] and b['period']<a['period']+a['duration']
            if overlap: assert all(a[k]!=b[k] for k in ('teacher','group','room'))
@pytest.mark.parametrize('kind',['weekly','exam'])
def test_solver_conflicts(kind):
    req=request(kind);validate(req,solve(req))
def test_impossible_and_duplicate():
    req=request(); req.rooms[0].capacity=1;req.rooms[1].capacity=1
    assert solve(req)['status']=='INFEASIBLE'
    data=request().model_dump();data['lessons'][1]['id']=data['lessons'][0]['id']
    with pytest.raises(ValueError):Request(**data)
def test_profiles_and_password(client):
    c=client; h=auth(c,2);t=auth(c,4)
    data={'name':'New Name','rank':'','specialty':'Management','bio':'Test'}
    assert c.patch('/api/teachers/5',json=data,headers=t).status_code==403
    assert c.patch('/api/teachers/4',json=data,headers=t).status_code==200
    assert c.patch('/api/teachers/5',json=data,headers=h).status_code==200
    assert c.post('/api/me/password',json={'old':'wrong','new':'new-password-123'},headers=t).status_code==400
    assert c.post('/api/me/password',json={'old':'test-password-123','new':'new-password-123'},headers=t).status_code==200
    assert c.post('/api/login',json={'username':'u4','password':'new-password-123'}).status_code==200
def test_schedule_api(client):
    c=client;h=auth(c,2);t=auth(c,4)
    data=request().model_dump()
    assert c.post('/api/schedules',json=data,headers=t).status_code==403
    assert c.post('/api/schedules',json=data,headers=h).status_code==200
    assert c.get('/api/schedules',headers=t).json()==[]  # drafts are management-only
    assert len(c.get('/api/schedules',headers=h).json())==1
    data['lessons'][0]['teacher']=999
    assert c.post('/api/schedules',json=data,headers=h).status_code==422
def test_seed_45_idempotent(tmp_path,monkeypatch):
    import app.seed as seed
    engine=create_engine('sqlite:///'+str(tmp_path/'seed.db'))
    monkeypatch.setattr(seed,'engine',engine)
    monkeypatch.setattr(seed,'Session',sessionmaker(engine))
    monkeypatch.setenv('DEMO_PASSWORD','test-demo-password-123')
    seed.seed();seed.seed()
    with sessionmaker(engine)() as db:
        users=list(db.scalars(select(User)))
        assert len(users)==46
        assert sum(u.role!='admin' for u in users)==45
        assert len(list(db.scalars(select(Recipient))))==45
    engine.dispose()
