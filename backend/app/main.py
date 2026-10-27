import os, uuid, hashlib, time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request as HttpRequest
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .models import User, Notice, Recipient, Attachment, Schedule, Audit, LoginAttempt, now
from .migrations import upgrade
from .security import current, managers, verify, token, hash_password
from .scheduler import Request, solve

UPLOAD = Path(os.getenv('UPLOAD_DIR', 'uploads')); UPLOAD.mkdir(parents=True, exist_ok=True)
@asynccontextmanager
async def lifespan(app):
    if get_db not in app.dependency_overrides: upgrade(engine)
    yield
app = FastAPI(title='BA-DMS | قسم إدارة الأعمال', lifespan=lifespan)
from .limits import BodyLimit
app.add_middleware(BodyLimit)
def log(db, user, action): db.add(Audit(user_id=user.id, action=action))
def profile(u): return {k: getattr(u,k) for k in ('id','username','role','name','rank','specialty','bio','active','qualification','detailed_specialty','email','employment','max_load','name_en','specialty_en','detailed_specialty_en','profile_links','source_ref')}
def required(db, model, id):
    obj = db.get(model, id)
    if not obj: raise HTTPException(404, 'السجل غير موجود')
    return obj
def access(db, notice_id, user):
    n = required(db, Notice, notice_id)
    r = db.scalar(select(Recipient).where(Recipient.notice_id == notice_id, Recipient.user_id == user.id))
    if user.role not in ('admin','head','coordinator') and not r: raise HTTPException(403, 'التبليغ غير موجه إليك')
    return n, r

class Login(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=256)
@app.post('/api/login')
def login(data: Login, request: HttpRequest, db: Session=Depends(get_db)):
    bucket=hashlib.sha256((data.username.lower()+'|'+(request.client.host if request.client else 'local')).encode()).hexdigest()
    recent=time.time()-300
    db.query(LoginAttempt).filter(LoginAttempt.attempted<recent).delete()
    if db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.bucket==bucket,LoginAttempt.attempted>=recent))>=8:
        db.commit(); raise HTTPException(429,'محاولات دخول كثيرة؛ انتظر خمس دقائق')
    db.add(LoginAttempt(bucket=bucket,attempted=time.time()));db.commit()
    u = db.scalar(select(User).where(User.username == data.username))
    if not u or not verify(data.password, u.password) or not u.active: raise HTTPException(401, 'بيانات الدخول غير صحيحة')
    db.query(LoginAttempt).filter(LoginAttempt.bucket==bucket).delete();db.commit()
    return {'access_token': token(u), 'user': profile(u)}
@app.get('/api/me')
def me(u=Depends(current)): return profile(u)
class Password(BaseModel):
    old: str
    new: str = Field(min_length=12, max_length=256)
@app.post('/api/me/password')
def password(data: Password, u=Depends(current), db: Session=Depends(get_db)):
    user = required(db, User, u.id)
    if not verify(data.old, user.password): raise HTTPException(400, 'كلمة المرور الحالية غير صحيحة')
    user.password = hash_password(data.new); user.token_version+=1; log(db,u,'password_change'); db.commit()
    return {'ok': True}
@app.get('/api/teachers')
def teachers(u=Depends(current), db: Session=Depends(get_db)):
    return [profile(x) for x in db.scalars(select(User).where(User.role != 'admin').order_by(User.id))]
class Profile(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    rank: str = Field(max_length=80)
    specialty: str = Field(max_length=100)
    bio: str = Field(max_length=4000)
    qualification: str = Field(default='',max_length=100)
    detailed_specialty: str = Field(default='',max_length=150)
    email: str = Field(default='',max_length=150)
    employment: str = Field(default='مستمر',max_length=80)
    max_load: int = Field(default=18,ge=1,le=60)
    name_en: str = Field(default='',max_length=200)
    specialty_en: str = Field(default='',max_length=200)
    detailed_specialty_en: str = Field(default='',max_length=200)
    profile_links: dict[str,str] = Field(default_factory=dict)
@app.post('/api/teachers',status_code=201)
def add_teacher(data:Profile,u=Depends(managers),db:Session=Depends(get_db)):
    from .faculty import validate_links
    import secrets
    validate_links(data.profile_links)
    if db.scalar(select(User.id).where(User.name==data.name.strip())):raise HTTPException(409,'يوجد ملف بهذا الاسم؛ ابحث عنه وعدّله بدل تكراره')
    if data.email and db.scalar(select(User.id).where(User.email==data.email)):raise HTTPException(409,'البريد الوظيفي مرتبط بملف موجود')
    key=uuid.uuid4().hex
    obj=User(**{**data.model_dump(),'name':data.name.strip()},username='faculty-'+key[:12],password=hash_password(secrets.token_urlsafe(48)),role='teacher',active=False,source_ref='manual:'+key)
    db.add(obj);log(db,u,'teacher_manual_create')
    from .catalog import commit
    commit(db);return profile(obj)
@app.patch('/api/teachers/{id}')
def edit_teacher(id: int, data: Profile, u=Depends(current), db: Session=Depends(get_db)):
    if id != u.id and u.role not in ('admin','head','coordinator'): raise HTTPException(403, 'يمكنك تعديل ملفك فقط')
    obj = required(db, User, id)
    from .faculty import validate_links
    validate_links(data.profile_links)
    if u.role=='teacher' and (data.max_load!=obj.max_load or data.employment!=obj.employment or data.rank!=obj.rank or data.qualification!=obj.qualification):
        raise HTTPException(403,'اللقب والشهادة والحالة الوظيفية والنصاب تعدّلها الإدارة')
    for key, value in data.model_dump().items(): setattr(obj,key,value)
    log(db,u,f'profile_update:{id}'); db.commit(); return profile(obj)
class NoticeInput(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=10000)
    recipients: list[int] = Field(default_factory=list, max_length=1000)
@app.post('/api/notices', status_code=201)
def create_notice(data: NoticeInput, u=Depends(managers), db: Session=Depends(get_db)):
    ids = set(data.recipients) or set(db.scalars(select(User.id).where(User.role != 'admin')))
    valid = set(db.scalars(select(User.id).where(User.id.in_(ids))))
    if ids != valid: raise HTTPException(422, 'مستلم غير موجود')
    n = Notice(title=data.title,body=data.body,author_id=u.id); db.add(n); db.flush()
    db.add_all([Recipient(notice_id=n.id,user_id=x) for x in ids]); log(db,u,f'notice_create:{n.id}'); db.commit()
    return {'id': n.id}
@app.get('/api/notices')
def notices(q:str='', state:str='all', archived:bool=False, u=Depends(current), db: Session=Depends(get_db)):
    query = select(Notice).order_by(Notice.id.desc())
    query=query.where(Notice.archived==archived)
    if q: query=query.where((Notice.title.contains(q)) | (Notice.body.contains(q)))
    if u.role == 'teacher': query = query.join(Recipient).where(Recipient.user_id == u.id)
    result = []
    for n in db.scalars(query):
        recipients = list(db.scalars(select(Recipient).where(Recipient.notice_id == n.id)))
        mine = next((r for r in recipients if r.user_id == u.id), None)
        if state=='unread' and (not mine or mine.viewed_at): continue
        if state=='pending' and (not mine or mine.acknowledged_at): continue
        if state=='confirmed' and (not mine or not mine.acknowledged_at): continue
        result.append({'id': n.id,'title': n.title,'body': n.body,'created_at': n.created_at,'author_id':n.author_id,'archived':n.archived,'viewed_at':mine.viewed_at if mine else None,'author': required(db,User,n.author_id).name,'acknowledged_at': mine.acknowledged_at if mine else None,'is_recipient': mine is not None,'total': len(recipients),'acknowledged': sum(r.acknowledged_at is not None for r in recipients),'attachments': [{'id': a.id,'name': a.name,'size': a.size} for a in db.scalars(select(Attachment).where(Attachment.notice_id == n.id))]})
    return result
@app.post('/api/notices/{id}/ack')
def ack(id: int, u=Depends(current), db: Session=Depends(get_db)):
    n,r = access(db,id,u)
    if not r: raise HTTPException(403, 'للمستلم فقط')
    changed=db.execute(update(Recipient).where(Recipient.id==r.id,Recipient.acknowledged_at.is_(None)).values(acknowledged_at=now())).rowcount
    if changed:log(db,u,f'notice_ack:{id}')
    db.refresh(r)
    db.commit(); return {'acknowledged_at': r.acknowledged_at}
@app.get('/api/notices/{id}/receipts')
def receipts(id:int,u=Depends(managers),db:Session=Depends(get_db)):
    required(db,Notice,id)
    return [{'name':required(db,User,r.user_id).name,'user_id':r.user_id,'acknowledged_at':r.acknowledged_at} for r in db.scalars(select(Recipient).where(Recipient.notice_id==id))]
@app.post('/api/notices/{id}/attachments', status_code=201)
async def upload(id:int, file:UploadFile=File(...),u=Depends(managers),db:Session=Depends(get_db)):
    notice = required(db,Notice,id)
    if notice.author_id != u.id and u.role != 'admin': raise HTTPException(403,'يمكن للمرسل إرفاق الملفات فقط')
    name = (file.filename or 'file').replace('\\','/').split('/')[-1][:200]
    if Path(name).suffix.lower() not in ('.pdf','.png','.jpg','.jpeg','.txt'):
        raise HTTPException(415,'المسموح: PDF، صور PNG/JPG، TXT')
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content)>5*1024*1024: raise HTTPException(413,'الحد الأقصى 5 MB')
    from .files import validate_file
    validate_file(name,content)
    key=uuid.uuid4().hex; path=UPLOAD/key; path.write_bytes(content)
    try:
        a=Attachment(notice_id=id,name=name,key=key,size=len(content)); db.add(a); log(db,u,f'attachment_upload:{id}'); db.commit()
    except Exception:
        path.unlink(missing_ok=True); raise
    return {'id':a.id,'name':name}
@app.get('/api/attachments/{id}')
def download(id:int,u=Depends(current),db:Session=Depends(get_db)):
    a=required(db,Attachment,id); access(db,a.notice_id,u)
    path=UPLOAD/a.key
    if not path.is_file(): raise HTTPException(404,'الملف غير موجود في التخزين')
    return FileResponse(path,filename=a.name,media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})
@app.post('/api/schedules')
def generate(data:Request,u=Depends(managers),db:Session=Depends(get_db)):
    ids={l.teacher for l in data.lessons}|{m.teacher for m in data.monitor_pool}
    if ids != set(db.scalars(select(User.id).where(User.id.in_(ids),User.role!='admin',User.active==True))): raise HTTPException(422,'تدريسي أو مراقب غير موجود أو معطل')
    result=solve(data)
    if not result['entries']: raise HTTPException(409,result)
    from .workflow import save_schedule
    s=save_schedule(db,u,data,result)
    return {'id':s.id,**result}
@app.get('/api/schedules')
def schedules(u=Depends(current),db:Session=Depends(get_db)):
    from .workflow import schedule_view
    query=select(Schedule).order_by(Schedule.id.desc())
    if u.role=='teacher':query=query.where(Schedule.status=='published')
    return [schedule_view(s) for s in db.scalars(query)]
@app.get('/api/audit')
def audit(u=Depends(managers),db:Session=Depends(get_db)):
    return [{'id':a.id,'user_id':a.user_id,'action':a.action,'created_at':a.created_at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(200))]
@app.get('/api/health')
def health(db:Session=Depends(get_db)):
    db.scalar(select(func.count(User.id))); return {'status':'ok'}

from .catalog import router as catalog_router
from .workflow import router as workflow_router
from .faculty import router as faculty_router
app.include_router(catalog_router)
app.include_router(workflow_router)
app.include_router(faculty_router)

if os.environ.get('DATABASE_BACKEND','sql')=='firestore':
    from .firebase_api import create_app
    app=create_app()
