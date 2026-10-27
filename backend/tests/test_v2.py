from datetime import date
import pytest
from sqlalchemy import create_engine, text, inspect
from app.scheduler import Request, solve
from app.migrations import upgrade
from test_system import client, auth

def create(c,h,kind,data):
    r=c.post('/api/academic/'+kind,json=data,headers=h);assert r.status_code==201,r.text
    return r.json()['id']
def catalog(c,h):
    sem=create(c,h,'semesters',{'name':'Test semester','year':'2026-2027','start_date':'2026-10-01','end_date':'2027-02-28'})
    groups=[create(c,h,'groups',{'semester_id':sem,'name':name,'stage':1,'shift':shift,'size':30}) for name,shift in [('Morning','morning'),('Evening','evening')]]
    room=create(c,h,'rooms',{'name':'Lab','capacity':40,'room_type':'lab','equipment':'projector'})
    periods=[]
    for i,start in enumerate([8,9,16,17]):periods.append(create(c,h,'periods',{'semester_id':sem,'name':f'P{i}','start':f'{start:02}:00','end':f'{start+1:02}:00','shift':'morning' if i<2 else 'evening'}))
    for i,g in enumerate(groups):
        co=create(c,h,'courses',{'name':f'Course {i}','sessions':2,'duration':1,'exam_duration':1,'monitors':2,'room_type':'lab','equipment':'projector'})
        create(c,h,'assignments',{'course_id':co,'group_id':g,'teacher_id':i+2})
    return sem,groups,room,periods

def test_accounts_revoke_and_rate_limit(client):
    c=client;a=auth(c,1);t=auth(c,4);h=auth(c,2)
    assert c.get('/api/users',headers=h).status_code==403
    assert c.post('/api/users',json={'username':'newteacher','name':'New User','password':'new-password-123','role':'teacher'},headers=a).status_code==201
    assert c.patch('/api/users/1',json={'role':'teacher','active':False},headers=a).status_code==409
    assert c.patch('/api/users/4',json={'role':'teacher','active':False},headers=a).status_code==200
    assert c.get('/api/me',headers=t).status_code==401
    assert c.post('/api/login',json={'username':'u4','password':'test-password-123'}).status_code==401
    assert c.patch('/api/users/4',json={'role':'teacher','active':True},headers=a).status_code==200
    t=auth(c,4)
    assert c.post('/api/me/password',json={'old':'test-password-123','new':'changed-password-123'},headers=t).status_code==200
    assert c.get('/api/me',headers=t).status_code==401
    for _ in range(8):assert c.post('/api/login',json={'username':'u5','password':'wrong'}).status_code==401
    assert c.post('/api/login',json={'username':'u5','password':'wrong'}).status_code==429

def test_catalog_validation_and_profile_rules(client):
    c=client;h=auth(c,2);t=auth(c,4);sem,groups,room,periods=catalog(c,h)
    assert c.get('/api/academic',headers=t).status_code==403
    assert c.post('/api/academic/periods',json={'semester_id':sem,'name':'Bad','start':'08:30','end':'09:30','shift':'morning'},headers=h).status_code==422
    assert c.post('/api/academic/unavailable',json={'period_id':periods[0],'weekday':6,'teacher_id':2,'room_id':room},headers=h).status_code==422
    create(c,h,'conflicts',{'first_id':groups[1],'second_id':groups[0]})
    assert c.post('/api/academic/conflicts',json={'first_id':groups[0],'second_id':groups[1]},headers=h).status_code==409
    assert c.delete('/api/academic/semesters/'+str(sem),headers=h).status_code==409
    p=c.get('/api/me',headers=t).json();p['max_load']=60
    assert c.patch('/api/teachers/4',json=p,headers=t).status_code==403

def test_catalog_generation_publication_and_versions(client):
    c=client;h=auth(c,2);co=auth(c,3);t=auth(c,4);sem,groups,room,periods=catalog(c,h)
    create(c,h,'unavailable',{'period_id':periods[0],'weekday':6,'room_id':room})
    payload={'semester_id':sem,'kind':'weekly','start_date':'2026-10-25','end_date':'2026-10-29','weekdays':[6,0,1,2,3]}
    r=c.post('/api/plans/generate',json=payload,headers=co);assert r.status_code==200,r.text
    first=r.json();id=first['id'];assert first['status']=='draft'
    assert len(first['result']['entries'])==4
    assert all(not(e['date']=='2026-10-25' and e['start']=='08:00') for e in first['result']['entries'])
    assert c.get('/api/schedules',headers=t).json()==[]
    assert c.get(f'/api/schedules/{id}/export.csv',headers=t).status_code==403
    assert c.post(f'/api/schedules/{id}/approve',headers=co).status_code==403
    assert c.post(f'/api/schedules/{id}/publish',headers=h).status_code==409
    assert c.post(f'/api/schedules/{id}/approve',headers=h).status_code==200
    assert c.get('/api/schedules',headers=t).json()==[]
    assert c.post(f'/api/schedules/{id}/publish',headers=h).status_code==200
    assert len(c.get('/api/schedules',headers=t).json())==1
    assert c.get(f'/api/schedules/{id}/export.csv',headers=t).content.startswith(b'\xef\xbb\xbf')
    second=c.post('/api/plans/generate',json=payload,headers=h).json();assert second['version']==2
    assert c.post(f"/api/schedules/{second['id']}/approve",headers=h).status_code==200
    assert c.post(f"/api/schedules/{second['id']}/publish",headers=h).status_code==200
    published=c.get('/api/schedules',headers=t).json();assert len(published)==1 and published[0]['version']==2
    # Actual exam plan with two additional invigilators, excluding the course teacher.
    exam={**payload,'kind':'exam','start_date':'2026-11-01','end_date':'2026-11-12','monitor_ids':[2,3,4,5]}
    response=c.post('/api/plans/generate',json=exam,headers=h);assert response.status_code==200,response.text
    for e in response.json()['result']['entries']:assert len(e['invigilators'])==2 and e['teacher'] not in e['invigilators']

def test_notice_view_archive_content_and_csv(client):
    c=client;h=auth(c,2);t=auth(c,4);other=auth(c,5)
    nid=c.post('/api/notices',json={'title':'Notice','body':'Contents','recipients':[4]},headers=h).json()['id']
    assert c.post(f'/api/notices/{nid}/view',headers=other).status_code==403
    c.post(f'/api/notices/{nid}/view',headers=t)
    notice=c.get('/api/notices',headers=t).json()[0];assert notice['viewed_at'] and not notice['acknowledged_at']
    assert c.get('/api/notices?state=unread',headers=t).json()==[]
    assert len(c.get('/api/notices?state=pending',headers=t).json())==1
    assert c.post(f'/api/notices/{nid}/attachments',files={'file':('fake.pdf',b'MZ executable')},headers=h).status_code==415
    assert c.get(f'/api/notices/{nid}/receipts.csv',headers=t).status_code==403
    assert c.get(f'/api/notices/{nid}/receipts.csv',headers=h).status_code==200
    assert c.patch(f'/api/notices/{nid}/archive',json={'archived':True},headers=t).status_code==403
    c.patch(f'/api/notices/{nid}/archive',json={'archived':True},headers=h)
    assert c.get('/api/notices',headers=t).json()==[]
    assert len(c.get('/api/notices?archived=true',headers=t).json())==1

def plan(**changes):
    data={'kind':'exam','days':3,'periods':2,'dates':['2026-11-01','2026-11-03','2026-11-05'],
      'timeline':[{'name':'AM','start':'08:00','end':'09:00','shift':'morning'},{'name':'PM','start':'16:00','end':'17:00','shift':'evening'}],
      'rooms':[{'id':'R1','capacity':50,'room_type':'lab','equipment':['projector'],'blocked':[0]}],
      'lessons':[{'id':'A','teacher':2,'group':'G1','title':'One','room_type':'lab','equipment':['projector'],'monitors':2},{'id':'B','teacher':3,'group':'G2','title':'Two','monitors':2}],
      'conflicts':[['G1','G2']],'monitor_pool':[{'teacher':i,'blocked':[1] if i==4 else []} for i in [2,3,4,5]],'exam_gap_days':1}
    return Request.model_validate({**data,**changes})
def test_joint_monitoring_shared_students_and_resources():
    req=plan();result=solve(req);assert result['entries'],result
    a,b=result['entries'];assert abs((date.fromisoformat(a['date'])-date.fromisoformat(b['date'])).days)>=2
    for e in result['entries']:
        assert e['day']*2+e['period']!=0
        assert len(set(e['invigilators']))==2 and e['teacher'] not in e['invigilators']
        if 4 in e['invigilators']:assert e['day']*2+e['period']!=1
    assert solve(plan(monitor_pool=[{'teacher':2}]))['status']=='INFEASIBLE'
    req=plan();req.rooms[0].equipment=[];assert solve(req)['status']=='INFEASIBLE'
    req=plan(kind='weekly',teacher_limits={2:0});assert solve(req)['status']=='INFEASIBLE'

def test_unknown_timeout_never_saves_fake_result():
    req=plan(time_limit=0.000000001)
    r=solve(req);assert r['status']=='UNKNOWN' and r['entries']==[]

def test_migration_preserves_v01_data(tmp_path):
    eng=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with eng.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80), password VARCHAR(256), role VARCHAR(20), name VARCHAR(150), rank VARCHAR(80), specialty VARCHAR(100), bio TEXT)'))
        c.execute(text("INSERT INTO users VALUES (1,'original','hash','admin','Original','','','')"))
    upgrade(eng);upgrade(eng)
    with eng.connect() as c:
        r=c.execute(text('SELECT username, active, token_version FROM users')).one();assert r==('original',1,0)
        assert list(c.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())==[1,2,3]
        assert 'assignments' in inspect(c).get_table_names()
    eng.dispose()

def test_faculty_import_isolated_idempotent_and_safe(client):
    c=client;a=auth(c,1);h=auth(c,2)
    p={'source_ref':'faculty:unique-test-reference','name':'New Faculty','name_en':'English Name','qualification':'PhD','email':'faculty@example.invalid','profile_links':{'orcid':'https://orcid.org/example'}}
    assert c.post('/api/faculty-import',json={'profiles':[p]},headers=h).status_code==403
    r=c.post('/api/faculty-import',json={'profiles':[p]},headers=a);assert r.status_code==200,r.text
    assert r.json()['created']==1
    assert c.post('/api/faculty-import',json={'profiles':[p]},headers=a).json()['skipped']==1
    faculty=next(t for t in c.get('/api/teachers',headers=a).json() if t['source_ref']==p['source_ref'])
    assert faculty['active'] is False and faculty['role']=='teacher'
    assert c.post('/api/login',json={'username':faculty['username'],'password':'test-password-123'}).status_code==401
    conflict={**p,'email':'different@example.invalid'}
    assert c.post('/api/faculty-import',json={'profiles':[conflict]},headers=a).status_code==409
    bad={**p,'source_ref':'faculty:second-reference','name':'Another Faculty','profile_links':{'orcid':'javascript:alert(1)'}}
    assert c.post('/api/faculty-import',json={'profiles':[bad]},headers=a).status_code==422

def test_reviewed_group_import_atomic_and_guarded(client):
    c=client;h=auth(c,2);t=auth(c,4)
    payload={'semester':{'name':'Imported term','year':'2026-2027','start_date':'2026-10-01','end_date':'2027-02-01'},'groups':[{'name':'Imported A','stage':2,'shift':'morning','size':40}],'rooms':[{'name':'3201','capacity':50}],'periods':[{'name':'1','start':'08:30','end':'09:30','shift':'morning'},{'name':'2','start':'09:30','end':'10:30','shift':'morning'}]}
    assert c.post('/api/academic-import',json=payload,headers=t).status_code==403
    bad={**payload,'rooms':[{'name':'3201','capacity':None}]}
    assert c.post('/api/academic-import',json=bad,headers=h).status_code==422
    assert c.get('/api/academic',headers=h).json()['semesters']==[]
    assert c.post('/api/academic-import',json=payload,headers=h).status_code==201
    assert c.post('/api/academic-import',json=payload,headers=h).status_code==409
    assert len(c.get('/api/academic',headers=h).json()['semesters'])==1

def test_body_limit_and_formula_safe_csv(client):
    c=client;h=auth(c,2)
    assert c.post('/api/notices',content=b'x'*(6*1024*1024+1),headers=h).status_code==413
    from app.workflow import csv_response
    data=csv_response([['=1+1','Normal','@formula']], 'test.csv').body.decode('utf-8-sig')
    assert "'=1+1" in data and "'@formula" in data

def test_manual_teacher_information_and_privilege_boundary(client):
    c=client;h=auth(c,2);t=auth(c,4)
    data={'name':'Manual Faculty','rank':'Lecturer','specialty':'Management','bio':'Manually entered','qualification':'MSc','detailed_specialty':'Operations','email':'manual@example.invalid','profile_links':{'scholar':'https://scholar.google.com/example'}}
    assert c.post('/api/teachers',json=data,headers=t).status_code==403
    r=c.post('/api/teachers',json={**data,'role':'admin','active':True},headers=h);assert r.status_code==201,r.text
    p=r.json();assert p['role']=='teacher' and not p['active'] and p['qualification']=='MSc'
    assert c.post('/api/teachers',json=data,headers=h).status_code==409
    assert c.post('/api/teachers',json={**data,'name':'Different Faculty'},headers=h).status_code==409
    assert c.patch('/api/teachers/'+str(p['id']),json={**data,'detailed_specialty':'Updated'},headers=h).status_code==200
    assert c.post('/api/teachers',json={**data,'name':'Unsafe','email':'','profile_links':{'scholar':'javascript:alert(1)'}},headers=h).status_code==422
