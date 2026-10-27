"""Native document-backed API. No SQL cache or local mirror in Firebase mode."""
import hashlib,json,secrets,time,uuid,os
from pathlib import Path
from datetime import date,timedelta
from types import SimpleNamespace
import jwt
from fastapi import FastAPI,Depends,HTTPException,Request as HttpRequest,UploadFile,File
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse,JSONResponse
from pydantic import ValidationError
from .security import SECRET,hash_password,verify,token
from .models import now
from .scheduler import Request,solve
from .catalog import REGISTRY,AccountCreate,AccountEdit,Reset,ReviewedImport
from .faculty import FacultyBatch,validate_links
from .workflow import Generate,Archive,csv_response
from .files import validate_file
from .limits import BodyLimit
from .firestore_store import FirestoreStore

CATALOG=tuple(REGISTRY)
REFS={'semester_id':'semesters','course_id':'courses','group_id':'groups','teacher_id':'users','room_id':'rooms','period_id':'periods','first_id':'groups','second_id':'groups'}
def require(state,col,id):
    row=state.get_row(col,id)
    if not row:raise HTTPException(404,'السجل غير موجود')
    return row
def audit(state,user,action):state.insert('audit',{'user_id':user['id'],'action':action,'created_at':now()})
def public(user):return {k:v for k,v in user.items() if k not in ('password','token_version')}
def base_user(**data):
    return {'username':'','name':'','password':'','role':'teacher','active':False,'token_version':0,'rank':'','specialty':'','bio':'','qualification':'','detailed_specialty':'','email':'','employment':'غير مؤكد','max_load':18,'name_en':'','specialty_en':'','detailed_specialty_en':'','profile_links':{},'source_ref':None,**data}
def catalog_validate(state,kind,data,id=None):
    for key,col in REFS.items():
        if data.get(key) is not None:
            obj=require(state,col,data[key])
            if col=='users' and (not obj['active'] or obj['role']=='admin'):raise HTTPException(422,'اختر تدريسيًا نشطًا')
    if kind=='semesters' and data['start_date']>data['end_date']:raise HTTPException(422,'تواريخ فصل غير صالحة')
    if kind=='periods':
        from datetime import time as clock
        try:a,b=clock.fromisoformat(data['start']),clock.fromisoformat(data['end'])
        except ValueError:raise HTTPException(422,'وقت غير صالح')
        if a>=b:raise HTTPException(422,'ترتيب الفترات غير صالح')
        if any(p['id']!=id and p['semester_id']==data['semester_id'] and data['start']<p['end'] and p['start']<data['end'] for p in state.rows('periods')):raise HTTPException(422,'الفترات متداخلة')
    if kind=='unavailable' and (data['teacher_id'] is None)==(data['room_id'] is None):raise HTTPException(422,'اختر قاعة أو تدريسيًا فقط')
    if kind=='conflicts':
        a,b=require(state,'groups',data['first_id']),require(state,'groups',data['second_id'])
        if a['id']==b['id'] or a['semester_id']!=b['semester_id']:raise HTTPException(422,'اختر شعبتين مختلفتين في الفصل نفسه')
        data['first_id'],data['second_id']=sorted((a['id'],b['id']))
    for old in state.rows(kind):
        if old['id']==id:continue
        keys=('course_id','group_id') if kind=='assignments' else ('first_id','second_id') if kind=='conflicts' else ()
        if keys and all(old[k]==data[k] for k in keys):raise HTTPException(409,'ارتباط مكرر')

def compile_state(s,data):
    semester=require(s,'semesters',data.semester_id)
    if data.start_date>data.end_date or (data.end_date-data.start_date).days>60:raise HTTPException(422,'مدى الخطة غير صالح')
    if data.start_date.isoformat()<semester['start_date'] or data.end_date.isoformat()>semester['end_date']:raise HTTPException(422,'الخطة خارج الفصل')
    if any(w not in range(7) for w in data.weekdays):raise HTTPException(422,'أيام غير صالحة')
    dates=[data.start_date+timedelta(days=i) for i in range((data.end_date-data.start_date).days+1) if (data.start_date+timedelta(days=i)).weekday() in data.weekdays]
    if not 1<=len(dates)<=30 or data.kind=='weekly' and (data.end_date-data.start_date).days>6:raise HTTPException(422,'اختر أسبوعًا واحدًا للأسبوعي أو حتى 30 يوم عمل للامتحاني')
    periods=sorted([p for p in s.rows('periods') if p['semester_id']==data.semester_id],key=lambda p:p['start'])
    if not 2<=len(periods)<=12:raise HTTPException(422,'الفترات غير مكتملة')
    def blocked(teacher=None,room=None):return [d*len(periods)+p for d,dt in enumerate(dates) for p,period in enumerate(periods) if any(a['weekday']==dt.weekday() and a['period_id']==period['id'] and ((teacher is not None and a['teacher_id']==teacher) or (room is not None and a['room_id']==room)) for a in s.rows('unavailable'))]
    equipment=lambda text:[x.strip() for x in text.replace('،',',').split(',') if x.strip()]
    rooms=[{'id':f"R{r['id']}",'capacity':r['capacity'],'room_type':r['room_type'],'equipment':equipment(r['equipment']),'blocked':blocked(room=r['id'])} for r in s.rows('rooms')]
    groups={g['id']:g for g in s.rows('groups') if g['semester_id']==data.semester_id};lessons=[];limits={}
    for a in s.rows('assignments'):
        if a['group_id'] not in groups:continue
        c=require(s,'courses',a['course_id']);g=groups[a['group_id']];t=require(s,'users',a['teacher_id'])
        if not t['active'] or t['role']=='admin':raise HTTPException(422,'تكليف مرتبط بتدريسي غير نشط')
        limits[t['id']]=t['max_load']
        for i in range(c['sessions'] if data.kind=='weekly' else 1):lessons.append({'id':f"A{a['id']}-{i+1}",'teacher':t['id'],'group':f"G{g['id']}",'title':c['name'],'shift':g['shift'],'size':g['size'],'duration':c['duration'] if data.kind=='weekly' else c['exam_duration'],'blocked':blocked(teacher=t['id']),'room_type':c['room_type'],'equipment':equipment(c['equipment']),'monitors':c['monitors'] if data.kind=='exam' else 0})
    pool=[]
    for id in set(data.monitor_ids):
        t=require(s,'users',id)
        if not t['active'] or t['role']=='admin':raise HTTPException(422,'مراقب غير نشط')
        pool.append({'teacher':id,'blocked':blocked(teacher=id),'max_sessions':data.monitor_max_sessions})
    payload={'kind':data.kind,'plan_key':f'{data.semester_id}:{data.kind}:{data.plan_name}','days':len(dates),'periods':len(periods),'dates':dates,'timeline':[{k:p[k] for k in ('name','start','end','shift')} for p in periods],'rooms':rooms,'lessons':lessons,'monitor_pool':pool,'teacher_limits':limits,'exam_gap_days':data.exam_gap_days,'conflicts':[(f"G{p['first_id']}",f"G{p['second_id']}") for p in s.rows('conflicts') if p['first_id'] in groups and p['second_id'] in groups]}
    try:return Request.model_validate(payload)
    except ValidationError as e:raise HTTPException(422,'بيانات الخطة غير مكتملة: '+str(e))

def create_app(store=None):
    # Imported only after main has defined the shared validated request schemas.
    from .main import Profile,Login,Password,NoticeInput
    store=store or FirestoreStore();app=FastAPI(title='BA-DMS | Firebase Firestore',version='0.2.0');app.state.store=store
    app.add_middleware(BodyLimit);bearer=HTTPBearer();upload=Path(os.getenv('UPLOAD_DIR','uploads'));upload.mkdir(parents=True,exist_ok=True)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
    def user(credentials=Depends(bearer)):
        try:
            p=jwt.decode(credentials.credentials,SECRET,algorithms=['HS256']);u=store.get('users',int(p['sub']))
            if not u or not u['active'] or p.get('ver')!=u['token_version']:raise ValueError()
            return u
        except (jwt.InvalidTokenError,ValueError,KeyError):raise HTTPException(401,'جلسة غير صالحة أو منتهية')
    def manager(u=Depends(user)):
        if u['role'] not in ('admin','head','coordinator'):raise HTTPException(403,'للإدارة فقط')
        return u
    def administrator(u=Depends(user)):
        if u['role']!='admin':raise HTTPException(403,'لمدير النظام فقط')
        return u
    def approver(u=Depends(user)):
        if u['role'] not in ('admin','head'):raise HTTPException(403,'لرئيس القسم أو المدير فقط')
        return u
    def tx(names,fn):return store.atomic(tuple(dict.fromkeys((*names,'audit'))),fn)
    @app.get('/api/health')
    def health():store.snapshot(('users',));return {'status':'ok','database':'firestore'}
    @app.post('/api/login')
    def login(data:Login,request:HttpRequest):
        bucket=hashlib.sha256((data.username.lower()+'|'+(request.client.host if request.client else 'local')).encode()).hexdigest()
        def change(s):
            s['login_attempts']={k:r for k,r in s['login_attempts'].items() if r['attempted']>=time.time()-300}
            if sum(r['bucket']==bucket for r in s.rows('login_attempts'))>=8:return {'error':429}
            s.insert('login_attempts',{'bucket':bucket,'attempted':time.time()})
            u=next((x for x in s.rows('users') if x['username']==data.username),None)
            if not u or not verify(data.password,u['password']) or not u['active']:return {'error':401}
            s['login_attempts']={k:r for k,r in s['login_attempts'].items() if r['bucket']!=bucket}
            return {'access_token':token(SimpleNamespace(**u)),'user':public(u)}
        r=tx(('users','login_attempts'),change)
        if 'error' in r:raise HTTPException(r['error'],'محاولات كثيرة؛ انتظر خمس دقائق' if r['error']==429 else 'بيانات الدخول غير صحيحة')
        return r
    @app.get('/api/me')
    def me(u=Depends(user)):return public(u)
    @app.post('/api/me/password')
    def password(data:Password,u=Depends(user)):
        def change(s):
            obj=require(s,'users',u['id'])
            if not verify(data.old,obj['password']):raise HTTPException(400,'كلمة المرور الحالية غير صحيحة')
            obj['password']=hash_password(data.new);obj['token_version']+=1;audit(s,u,'password_change');return {'ok':True}
        return tx(('users',),change)
    @app.get('/api/teachers')
    def teachers(u=Depends(user)):return [public(x) for x in store.snapshot(('users',)).rows('users') if x['role']!='admin']
    @app.post('/api/teachers',status_code=201)
    def add_teacher(data:Profile,u=Depends(manager)):
        validate_links(data.profile_links)
        def change(s):
            if any(x['name']==data.name.strip() or data.email and x['email']==data.email for x in s.rows('users')):raise HTTPException(409,'الاسم أو البريد موجود')
            key=uuid.uuid4().hex;obj=s.insert('users',base_user(**{**data.model_dump(),'name':data.name.strip()},username='faculty-'+key[:12],password=hash_password(secrets.token_urlsafe(48)),source_ref='manual:'+key));audit(s,u,'teacher_manual_create');return public(obj)
        return tx(('users',),change)
    @app.patch('/api/teachers/{id}')
    def edit_teacher(id:int,data:Profile,u=Depends(user)):
        validate_links(data.profile_links)
        def change(s):
            obj=require(s,'users',id)
            if u['role']=='teacher' and (id!=u['id'] or any(getattr(data,k)!=obj[k] for k in ('rank','qualification','employment','max_load'))):raise HTTPException(403,'لا تملك صلاحية تغيير هذه الحقول')
            obj.update(data.model_dump());audit(s,u,f'profile_update:{id}');return public(obj)
        return tx(('users',),change)
    @app.get('/api/users')
    def users(u=Depends(administrator)):return [{k:x[k] for k in ('id','username','name','role','active')} for x in store.snapshot(('users',)).rows('users')]
    @app.post('/api/users',status_code=201)
    def add_user(data:AccountCreate,u=Depends(administrator)):
        def change(s):
            if any(x['username']==data.username for x in s.rows('users')):raise HTTPException(409,'اسم المستخدم موجود')
            obj=s.insert('users',base_user(username=data.username,name=data.name,role=data.role,active=True,password=hash_password(data.password)));audit(s,u,'account_create');return {'id':obj['id']}
        return tx(('users',),change)
    @app.patch('/api/users/{id}')
    def edit_user(id:int,data:AccountEdit,u=Depends(administrator)):
        def change(s):
            obj=require(s,'users',id)
            if id==u['id'] and (data.role!='admin' or not data.active):raise HTTPException(409,'لا يمكن تخفيض حسابك الإداري')
            obj.update(data.model_dump());obj['token_version']+=1;audit(s,u,f'account_update:{id}');return {'ok':True}
        return tx(('users',),change)
    @app.post('/api/users/{id}/reset')
    def reset_user(id:int,data:Reset,u=Depends(administrator)):
        def change(s):
            obj=require(s,'users',id);obj['password']=hash_password(data.password);obj['token_version']+=1;audit(s,u,f'password_reset:{id}');return {'ok':True}
        return tx(('users',),change)
    @app.get('/api/academic')
    def academic(u=Depends(manager)):
        s=store.snapshot(CATALOG);return {k:s.rows(k) for k in CATALOG}
    @app.post('/api/academic/{kind}',status_code=201)
    def academic_add(kind:str,body:dict,u=Depends(manager)):
        if kind not in REGISTRY:raise HTTPException(404,'نوع غير معروف')
        try:data=REGISTRY[kind][1].model_validate(body).model_dump(mode='json')
        except ValidationError as e:raise HTTPException(422,str(e))
        def change(s):catalog_validate(s,kind,data);obj=s.insert(kind,data);audit(s,u,f'catalog_create:{kind}');return obj
        return tx((*CATALOG,'users'),change)
    @app.put('/api/academic/{kind}/{id}')
    def academic_edit(kind:str,id:int,body:dict,u=Depends(manager)):
        if kind not in REGISTRY:raise HTTPException(404,'نوع غير معروف')
        try:data=REGISTRY[kind][1].model_validate(body).model_dump(mode='json')
        except ValidationError as e:raise HTTPException(422,str(e))
        def change(s):obj=require(s,kind,id);catalog_validate(s,kind,data,id);obj.update(data);audit(s,u,f'catalog_update:{kind}:{id}');return obj
        return tx((*CATALOG,'users'),change)
    @app.delete('/api/academic/{kind}/{id}')
    def academic_delete(kind:str,id:int,u=Depends(manager)):
        if kind not in REGISTRY:raise HTTPException(404,'نوع غير معروف')
        def change(s):
            require(s,kind,id)
            if any(row.get(field)==id for col in CATALOG for row in s.rows(col) for field,target in REFS.items() if target==kind):raise HTTPException(409,'السجل مرتبط ببيانات أخرى')
            del s[kind][str(id)];audit(s,u,f'catalog_delete:{kind}:{id}');return {'ok':True}
        return tx(CATALOG,change)
    @app.post('/api/faculty-import')
    def faculty_import(data:FacultyBatch,u=Depends(administrator)):
        def change(s):
            created=skipped=0
            if len({p.name for p in data.profiles})!=len(data.profiles):raise HTTPException(422,'أسماء مكررة')
            for p in data.profiles:
                validate_links(p.profile_links);existing=next((x for x in s.rows('users') if x['source_ref']==p.source_ref),None)
                if existing:
                    if any(existing[k]!=v for k,v in p.model_dump().items()):raise HTTPException(409,'سجل مستورد مختلف؛ راجعه يدويًا')
                    skipped+=1;continue
                if any(x['name']==p.name for x in s.rows('users')):raise HTTPException(409,'اسم موجود بحساب آخر')
                s.insert('users',base_user(**p.model_dump(),username='faculty-'+p.source_ref[-12:],password=hash_password(secrets.token_urlsafe(48))));created+=1
            audit(s,u,f'faculty_import:{created}');return {'created':created,'skipped':skipped,'note':'الحسابات غير مفعلة؛ راجع اللقب والنصاب ثم فعّلها من إدارة الحسابات.'}
        return tx(('users',),change)
    @app.post('/api/academic-import',status_code=201)
    def academic_import(data:ReviewedImport,u=Depends(manager)):
        def change(s):
            sd=data.semester.model_dump(mode='json');catalog_validate(s,'semesters',sd)
            if any(x['name']==sd['name'] and x['year']==sd['year'] for x in s.rows('semesters')):raise HTTPException(409,'الفصل موجود')
            if len({g.name for g in data.groups})!=len(data.groups) or len({r.name for r in data.rooms})!=len(data.rooms):raise HTTPException(422,'أسماء مكررة')
            sem=s.insert('semesters',sd)
            for g in data.groups:s.insert('groups',{**g.model_dump(),'semester_id':sem['id']})
            for p in data.periods:
                row={**p.model_dump(),'semester_id':sem['id']};catalog_validate(s,'periods',row);s.insert('periods',row)
            for r in data.rooms:
                old=next((x for x in s.rows('rooms') if x['name']==r.name),None)
                if old and any(old[k]!=v for k,v in r.model_dump().items()):raise HTTPException(409,'قاعة موجودة ببيانات مختلفة')
                if not old:s.insert('rooms',r.model_dump())
            audit(s,u,'reviewed_catalog_import');return {'semester_id':sem['id'],'groups':len(data.groups),'rooms':len(data.rooms),'periods':len(data.periods)}
        return tx(CATALOG,change)

    def notice_access(s,id,u):
        n=require(s,'notices',id);r=next((r for r in s.rows('recipients') if r['notice_id']==id and r['user_id']==u['id']),None)
        if u['role']=='teacher' and not r:raise HTTPException(403,'التبليغ غير موجه إليك')
        return n,r
    @app.post('/api/notices',status_code=201)
    def notice_add(data:NoticeInput,u=Depends(manager)):
        def change(s):
            ids=set(data.recipients) or {x['id'] for x in s.rows('users') if x['role']!='admin' and x['active']}
            if len(ids)>400:raise HTTPException(422,'أكثر من 400 مستلم؛ قسّم التبليغ')
            if any(not s.get_row('users',id) for id in ids):raise HTTPException(422,'مستلم غير موجود')
            n=s.insert('notices',{'title':data.title,'body':data.body,'author_id':u['id'],'created_at':now(),'archived':False})
            for id in ids:s.insert('recipients',{'notice_id':n['id'],'user_id':id,'acknowledged_at':None,'viewed_at':None})
            audit(s,u,f"notice_create:{n['id']}");return {'id':n['id']}
        return tx(('users','notices','recipients'),change)
    @app.get('/api/notices')
    def notices(q:str='',state:str='all',archived:bool=False,u=Depends(user)):
        s=store.snapshot(('notices','recipients','attachments','users'));out=[]
        for n in sorted(s.rows('notices'),key=lambda n:n['id'],reverse=True):
            if n['archived']!=archived or q and q not in n['title']+n['body']:continue
            recipients=[r for r in s.rows('recipients') if r['notice_id']==n['id']];mine=next((r for r in recipients if r['user_id']==u['id']),None)
            if u['role']=='teacher' and not mine:continue
            if state=='unread' and (not mine or mine['viewed_at']):continue
            if state=='pending' and (not mine or mine['acknowledged_at']):continue
            if state=='confirmed' and (not mine or not mine['acknowledged_at']):continue
            out.append({**n,'author':require(s,'users',n['author_id'])['name'],'is_recipient':bool(mine),'viewed_at':mine['viewed_at'] if mine else None,'acknowledged_at':mine['acknowledged_at'] if mine else None,'total':len(recipients),'acknowledged':sum(bool(r['acknowledged_at']) for r in recipients),'attachments':[{k:a[k] for k in ('id','name','size')} for a in s.rows('attachments') if a['notice_id']==n['id']]})
        return out
    @app.post('/api/notices/{id}/view')
    def notice_view(id:int,u=Depends(user)):
        def change(s):
            n,r=notice_access(s,id,u)
            if not r:raise HTTPException(403,'للمستلم فقط')
            if not r['viewed_at']:r['viewed_at']=now()
            return {'viewed_at':r['viewed_at']}
        return tx(('notices','recipients'),change)
    @app.post('/api/notices/{id}/ack')
    def notice_ack(id:int,u=Depends(user)):
        def change(s):
            n,r=notice_access(s,id,u)
            if not r:raise HTTPException(403,'للمستلم فقط')
            if not r['acknowledged_at']:r['acknowledged_at']=now();audit(s,u,f'notice_ack:{id}')
            return {'acknowledged_at':r['acknowledged_at']}
        return tx(('notices','recipients'),change)
    @app.patch('/api/notices/{id}/archive')
    def notice_archive(id:int,data:Archive,u=Depends(manager)):
        def change(s):require(s,'notices',id)['archived']=data.archived;audit(s,u,f'notice_archive:{id}');return {'ok':True}
        return tx(('notices',),change)
    def receipt_rows(id):
        s=store.snapshot(('notices','recipients','users'));require(s,'notices',id)
        return [{'user_id':r['user_id'],'name':require(s,'users',r['user_id'])['name'],'viewed_at':r['viewed_at'],'acknowledged_at':r['acknowledged_at']} for r in s.rows('recipients') if r['notice_id']==id]
    @app.get('/api/notices/{id}/receipts')
    def receipts(id:int,u=Depends(manager)):return receipt_rows(id)
    @app.get('/api/notices/{id}/receipts.csv')
    def receipt_csv(id:int,u=Depends(manager)):return csv_response([['المستلم','وقت العرض','التأكيد']]+[[r['name'],r['viewed_at'] or '',r['acknowledged_at'] or ''] for r in receipt_rows(id)],f'receipts-{id}.csv')
    @app.post('/api/notices/{id}/attachments',status_code=201)
    async def attach(id:int,file:UploadFile=File(...),u=Depends(manager)):
        name=(file.filename or 'file').replace('\\','/').split('/')[-1][:200];content=await file.read(5*1024*1024+1)
        if len(content)>5*1024*1024:raise HTTPException(413,'الحد الأقصى 5 MB')
        validate_file(name,content);key=uuid.uuid4().hex;path=upload/key
        def change(s):
            n=require(s,'notices',id)
            if n['author_id']!=u['id'] and u['role']!='admin':raise HTTPException(403,'للمرسل أو المدير فقط')
            a=s.insert('attachments',{'notice_id':id,'name':name,'key':key,'size':len(content)});audit(s,u,f'attachment_upload:{id}');return {'id':a['id'],'name':name}
        path.write_bytes(content)
        try:return tx(('notices','attachments'),change)
        except Exception:path.unlink(missing_ok=True);raise
    @app.get('/api/attachments/{id}')
    def attachment(id:int,u=Depends(user)):
        s=store.snapshot(('attachments','notices','recipients'));a=require(s,'attachments',id);notice_access(s,a['notice_id'],u);path=upload/a['key']
        if not path.is_file():raise HTTPException(404,'المرفق غير موجود على الخادم')
        return FileResponse(path,filename=a['name'],media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})

    def save(data,result,u,expected=None):
        def change(s):
            if expected is not None and any(s[col]!=expected[col] for col in (*CATALOG,'users')):raise HTTPException(409,'تغيرت البيانات الأكاديمية أثناء التوليد؛ أعد المحاولة')
            for id in {l.teacher for l in data.lessons}|{m.teacher for m in data.monitor_pool}:
                t=s.get_row('users',id)
                if not t:raise HTTPException(422,'تدريسي غير موجود')
                if not t['active'] or t['role']=='admin':raise HTTPException(422,'تدريسي غير نشط')
            key=data.plan_key or data.kind;version=max((x['version'] for x in s.rows('schedules') if x['plan_key']==key),default=0)+1
            obj=s.insert('schedules',{'kind':data.kind,'created_at':now(),'author_id':u['id'],'plan_key':key,'version':version,'status':'draft','approved_by':None,'approved_at':None,'published_at':None,'request':data.model_dump(mode='json'),'result':result});audit(s,u,f"schedule_generate:{obj['id']}");return obj
        return tx(('users','schedules',*CATALOG) if expected is not None else ('users','schedules'),change)
    @app.post('/api/schedules')
    def direct_schedule(data:Request,u=Depends(manager)):
        result=solve(data)
        if not result['entries']:raise HTTPException(409,result)
        return save(data,result,u)
    @app.post('/api/plans/generate')
    def generate(data:Generate,u=Depends(manager)):
        s=store.snapshot((*CATALOG,'users'));req=compile_state(s,data);result=solve(req)
        if not result['entries']:raise HTTPException(409,result)
        for e in result['entries']:
            e['teacher_name']=require(s,'users',e['teacher'])['name'];e['group_name']=require(s,'groups',int(e['group'][1:]))['name'];e['room_name']=require(s,'rooms',int(e['room'][1:]))['name'];e['invigilator_names']=[require(s,'users',t)['name'] for t in e['invigilators']]
        return save(req,result,u,s)
    @app.get('/api/schedules')
    def schedules(u=Depends(user)):return sorted([s for s in store.snapshot(('schedules',)).rows('schedules') if u['role']!='teacher' or s['status']=='published'],key=lambda s:s['id'],reverse=True)
    @app.post('/api/schedules/{id}/approve')
    def approve(id:int,u=Depends(approver)):
        def change(s):
            obj=require(s,'schedules',id)
            if obj['status']!='draft':raise HTTPException(409,'للمسودة فقط')
            if not obj['request'].get('dates') or not obj['request'].get('timeline'):raise HTTPException(422,'التواريخ والأوقات الفعلية مطلوبة')
            obj.update(status='approved',approved_by=u['id'],approved_at=now());audit(s,u,f'schedule_approve:{id}');return obj
        return tx(('schedules',),change)
    @app.post('/api/schedules/{id}/publish')
    def publish(id:int,u=Depends(approver)):
        def change(s):
            obj=require(s,'schedules',id)
            if obj['status']!='approved':raise HTTPException(409,'اعتمد الجدول أولًا')
            for other in s.rows('schedules'):
                if other['status']!='published':continue
                if other['plan_key']==obj['plan_key']:other['status']='archived';continue
                pairs={frozenset(p) for p in obj['request'].get('conflicts',[])+other['request'].get('conflicts',[])}
                for a in obj['result']['entries']:
                    for b in other['result']['entries']:
                        overlap=a.get('date')==b.get('date') and a.get('start') and b.get('start') and a['start']<b['end'] and b['start']<a['end']
                        if overlap and ({a['teacher'],*a.get('invigilators',[])}&{b['teacher'],*b.get('invigilators',[])} or a['room']==b['room'] or a['group']==b['group'] or frozenset((a['group'],b['group'])) in pairs):raise HTTPException(409,f"تعارض مع الجدول المنشور {other['id']}")
            obj.update(status='published',published_at=now());audit(s,u,f'schedule_publish:{id}');return obj
        return tx(('schedules',),change)
    @app.get('/api/schedules/{id}/export.csv')
    def schedule_csv(id:int,teacher:int|None=None,group:str='',room:str='',shift:str='',u=Depends(user)):
        s=store.get('schedules',id)
        if not s:raise HTTPException(404,'الجدول غير موجود')
        if u['role']=='teacher' and s['status']!='published':raise HTTPException(403,'لم ينشر الجدول بعد')
        rows=[['المادة','التاريخ','البداية','النهاية','التدريسي','الشعبة','القاعة','الدراسة','المراقبون']]
        for e in s['result']['entries']:
            if teacher and teacher not in {e['teacher'],*e.get('invigilators',[])} or group and e['group']!=group or room and e['room']!=room or shift and e['shift']!=shift:continue
            rows.append([e['title'],e.get('date') or e['day']+1,e.get('start') or e['period']+1,e.get('end') or '',e.get('teacher_name',e['teacher']),e.get('group_name',e['group']),e.get('room_name',e['room']),e['shift'],'، '.join(e.get('invigilator_names',[]))])
        return csv_response(rows,f'schedule-{id}.csv')
    @app.get('/api/teachers/{id}/work')
    def teacher_work(id:int,u=Depends(user)):
        s=store.snapshot(('users','assignments','courses','groups','schedules'));require(s,'users',id);assignments=[];duties=[]
        for a in s.rows('assignments'):
            if a['teacher_id']==id:
                c=require(s,'courses',a['course_id']);g=require(s,'groups',a['group_id']);assignments.append({'id':a['id'],'course':c['name'],'group':g['name'],'semester_id':g['semester_id'],'sessions':c['sessions'],'period_load':c['sessions']*c['duration']})
        for plan in s.rows('schedules'):
            if u['role']=='teacher' and plan['status']!='published':continue
            duties.extend({**e,'schedule_id':plan['id'],'kind':plan['kind'],'status':plan['status']} for e in plan['result']['entries'] if id in {e['teacher'],*e.get('invigilators',[])})
        return {'assignments':assignments,'duties':duties}
    @app.get('/api/audit')
    def audit_list(u=Depends(manager)):return sorted(store.snapshot(('audit',)).rows('audit'),key=lambda a:a['id'],reverse=True)[:200]
    return app
