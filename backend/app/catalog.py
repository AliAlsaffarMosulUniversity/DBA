from datetime import date, time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Semester, StudentGroup, Course, Assignment, Classroom, Period, Unavailable, GroupConflict, Audit
from .security import managers, admin, current, hash_password

router=APIRouter(prefix='/api')
class SemesterData(BaseModel):
    name:str=Field(min_length=2,max_length=100)
    year:str=Field(min_length=4,max_length=30)
    start_date:date
    end_date:date
class GroupData(BaseModel):
    semester_id:int
    name:str=Field(min_length=2,max_length=80)
    stage:int=Field(ge=1,le=8)
    shift:Literal['morning','evening']
    size:int=Field(ge=1,le=1000)
class CourseData(BaseModel):
    name:str=Field(min_length=2,max_length=150)
    sessions:int=Field(ge=1,le=8)
    duration:int=Field(ge=1,le=4)
    exam_duration:int=Field(ge=1,le=4)
    monitors:int=Field(ge=0,le=8)
    room_type:str=Field(default='',max_length=40)
    equipment:str=Field(default='',max_length=200)
class AssignmentData(BaseModel):
    course_id:int
    group_id:int
    teacher_id:int
class RoomData(BaseModel):
    name:str=Field(min_length=2,max_length=60)
    capacity:int=Field(ge=1,le=1000)
    room_type:str=Field(default='',max_length=40)
    equipment:str=Field(default='',max_length=200)
class PeriodData(BaseModel):
    semester_id:int
    name:str=Field(min_length=1,max_length=60)
    start:str=Field(pattern=r'^\d{2}:\d{2}$')
    end:str=Field(pattern=r'^\d{2}:\d{2}$')
    shift:Literal['morning','evening']
class UnavailableData(BaseModel):
    period_id:int
    weekday:int=Field(ge=0,le=6)
    teacher_id:int|None=None
    room_id:int|None=None
class ConflictData(BaseModel):
    first_id:int
    second_id:int

REGISTRY={'semesters':(Semester,SemesterData),'groups':(StudentGroup,GroupData),'courses':(Course,CourseData),'assignments':(Assignment,AssignmentData),'rooms':(Classroom,RoomData),'periods':(Period,PeriodData),'unavailable':(Unavailable,UnavailableData),'conflicts':(GroupConflict,ConflictData)}
REFS={'semester_id':Semester,'course_id':Course,'group_id':StudentGroup,'teacher_id':User,'room_id':Classroom,'period_id':Period,'first_id':StudentGroup,'second_id':StudentGroup}
def required(db,model,id):
    obj=db.get(model,id)
    if not obj:raise HTTPException(404,'السجل غير موجود')
    return obj
def row(obj):return {c.name:getattr(obj,c.name) for c in obj.__table__.columns}
def commit(db):
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'السجل مكرر أو مرتبط بسجلات أخرى؛ عدّل الارتباطات أولًا')
def registry(kind):
    if kind not in REGISTRY:raise HTTPException(404,'نوع بيانات غير معروف')
    return REGISTRY[kind]
def validate(db,kind,data,id=None):
    for field,model in REFS.items():
        if data.get(field) is not None:
            obj=required(db,model,data[field])
            if model is User and (not obj.active or obj.role=='admin'):raise HTTPException(422,'يجب اختيار تدريسي نشط')
    if kind=='semesters' and data['start_date']>data['end_date']:raise HTTPException(422,'نهاية الفصل تسبق بدايته')
    if kind=='periods':
        try:start,end=time.fromisoformat(data['start']),time.fromisoformat(data['end'])
        except ValueError:raise HTTPException(422,'وقت غير صالح')
        if start>=end:raise HTTPException(422,'نهاية الفترة يجب أن تكون بعد بدايتها')
        for p in db.scalars(select(Period).where(Period.semester_id==data['semester_id'])):
            if p.id!=id and data['start']<p.end and p.start<data['end']:raise HTTPException(422,'هذه الفترة تتداخل مع فترة موجودة')
    if kind=='unavailable' and (data['teacher_id'] is None)==(data['room_id'] is None):raise HTTPException(422,'اختر تدريسيًا أو قاعة واحدة فقط')
    if kind=='conflicts':
        a,b=required(db,StudentGroup,data['first_id']),required(db,StudentGroup,data['second_id'])
        if a.id==b.id or a.semester_id!=b.semester_id:raise HTTPException(422,'اختر شعبتين مختلفتين في الفصل نفسه')
        data['first_id'],data['second_id']=sorted((a.id,b.id))

@router.get('/academic')
def catalog(u=Depends(managers),db:Session=Depends(get_db)):
    return {kind:[row(o) for o in db.scalars(select(model).order_by(model.id))] for kind,(model,schema) in REGISTRY.items()}
@router.post('/academic/{kind}',status_code=201)
def create(kind:str,body:dict,u=Depends(managers),db:Session=Depends(get_db)):
    model,schema=registry(kind)
    try:data=schema.model_validate(body).model_dump(mode='json')
    except ValidationError as e:raise HTTPException(422,'بيانات غير صالحة: '+str(e))
    validate(db,kind,data);obj=model(**data);db.add(obj);db.add(Audit(user_id=u.id,action=f'catalog_create:{kind}'));commit(db);return row(obj)
@router.put('/academic/{kind}/{id}')
def edit(kind:str,id:int,body:dict,u=Depends(managers),db:Session=Depends(get_db)):
    model,schema=registry(kind);obj=required(db,model,id)
    try:data=schema.model_validate(body).model_dump(mode='json')
    except ValidationError as e:raise HTTPException(422,'بيانات غير صالحة: '+str(e))
    validate(db,kind,data,id)
    for key,value in data.items():setattr(obj,key,value)
    db.add(Audit(user_id=u.id,action=f'catalog_update:{kind}:{id}'));commit(db);return row(obj)
@router.delete('/academic/{kind}/{id}')
def remove(kind:str,id:int,u=Depends(managers),db:Session=Depends(get_db)):
    model,schema=registry(kind);obj=required(db,model,id)
    # Explicit reference protection also covers SQLite when foreign keys are disabled externally.
    for target,_ in REGISTRY.values():
        for column in target.__table__.columns:
            for fk in column.foreign_keys:
                if fk.column.table.name==obj.__tablename__ and db.scalar(select(target.id).where(getattr(target,column.name)==id).limit(1)):
                    raise HTTPException(409,'السجل مستخدم؛ أزل الارتباطات أولًا')
    db.delete(obj);db.add(Audit(user_id=u.id,action=f'catalog_delete:{kind}:{id}'));commit(db);return {'ok':True}

class AccountCreate(BaseModel):
    username:str=Field(min_length=3,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    name:str=Field(min_length=2,max_length=150)
    password:str=Field(min_length=12,max_length=256)
    role:Literal['admin','head','coordinator','teacher']='teacher'
class AccountEdit(BaseModel):
    role:Literal['admin','head','coordinator','teacher']
    active:bool
class Reset(BaseModel):
    password:str=Field(min_length=12,max_length=256)
@router.get('/users')
def users(u=Depends(admin),db:Session=Depends(get_db)):
    return [{k:getattr(x,k) for k in ('id','username','name','role','active')} for x in db.scalars(select(User).order_by(User.id))]
@router.post('/users',status_code=201)
def create_user(data:AccountCreate,u=Depends(admin),db:Session=Depends(get_db)):
    obj=User(username=data.username,name=data.name,role=data.role,password=hash_password(data.password));db.add(obj)
    db.add(Audit(user_id=u.id,action='account_create'));commit(db);return {'id':obj.id}
@router.patch('/users/{id}')
def edit_user(id:int,data:AccountEdit,u=Depends(admin),db:Session=Depends(get_db)):
    obj=required(db,User,id)
    if id==u.id and (not data.active or data.role!='admin'):raise HTTPException(409,'لا يمكن تعطيل حسابك الإداري أو تخفيض دوره')
    obj.role=data.role;obj.active=data.active;obj.token_version+=1
    db.add(Audit(user_id=u.id,action=f'account_update:{id}'));commit(db);return {'ok':True}
@router.post('/users/{id}/reset')
def reset_user(id:int,data:Reset,u=Depends(admin),db:Session=Depends(get_db)):
    obj=required(db,User,id);obj.password=hash_password(data.password);obj.token_version+=1
    db.add(Audit(user_id=u.id,action=f'account_password_reset:{id}'));commit(db);return {'ok':True}

@router.get('/teachers/{id}/work')
def teacher_work(id:int,u=Depends(current),db:Session=Depends(get_db)):
    from .models import Schedule
    required(db,User,id)
    assignments=[]
    for a in db.scalars(select(Assignment).where(Assignment.teacher_id==id)):
        c=required(db,Course,a.course_id);g=required(db,StudentGroup,a.group_id)
        assignments.append({'id':a.id,'course':c.name,'group':g.name,'semester_id':g.semester_id,'sessions':c.sessions,'period_load':c.sessions*c.duration})
    query=select(Schedule)
    if u.role=='teacher':query=query.where(Schedule.status=='published')
    duties=[]
    for s in db.scalars(query):
        duties.extend({**e,'schedule_id':s.id,'kind':s.kind,'status':s.status} for e in s.data['result']['entries'] if e['teacher']==id or id in e.get('invigilators',[]))
    return {'assignments':assignments,'duties':duties}

class ImportedGroup(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    stage:int=Field(ge=1,le=8)
    shift:Literal['morning','evening']
    size:int=Field(ge=1,le=1000)
class ImportedRoom(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    capacity:int=Field(ge=1,le=1000)
    room_type:str=Field(default='',max_length=40)
    equipment:str=Field(default='',max_length=200)
class ImportedPeriod(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    start:str=Field(pattern=r'^\d{2}:\d{2}$')
    end:str=Field(pattern=r'^\d{2}:\d{2}$')
    shift:Literal['morning','evening']
class ReviewedImport(BaseModel):
    semester:SemesterData
    groups:list[ImportedGroup]=Field(min_length=1,max_length=100)
    rooms:list[ImportedRoom]=Field(min_length=1,max_length=100)
    periods:list[ImportedPeriod]=Field(min_length=2,max_length=12)

@router.post('/academic-import',status_code=201)
def import_review(data:ReviewedImport,u=Depends(managers),db:Session=Depends(get_db)):
    sdata=data.semester.model_dump(mode='json');validate(db,'semesters',sdata)
    if db.scalar(select(Semester.id).where(Semester.name==sdata['name'],Semester.year==sdata['year'])):raise HTTPException(409,'الفصل موجود؛ استخدم شاشة التعديل لتجنب الاستيراد المكرر')
    if len({(g.name,g.shift) for g in data.groups})!=len(data.groups) or len({r.name for r in data.rooms})!=len(data.rooms):raise HTTPException(422,'أسماء شعب أو قاعات مكررة')
    previous=None
    for p in sorted(data.periods,key=lambda p:p.start):
        try:start,end=time.fromisoformat(p.start),time.fromisoformat(p.end)
        except ValueError:raise HTTPException(422,'وقت غير صالح')
        if start>=end or previous is not None and start<previous:raise HTTPException(422,'الفترات متداخلة أو نهايتها غير صحيحة')
        previous=end
    semester=Semester(**sdata);db.add(semester);db.flush()
    for g in data.groups:db.add(StudentGroup(semester_id=semester.id,**g.model_dump()))
    for p in data.periods:db.add(Period(semester_id=semester.id,**p.model_dump()))
    for r in data.rooms:
        existing=db.scalar(select(Classroom).where(Classroom.name==r.name))
        if existing:
            if any(getattr(existing,k)!=v for k,v in r.model_dump().items()):raise HTTPException(409,f'القاعة {r.name} موجودة ببيانات مختلفة؛ راجعها قبل الاستيراد')
        else:db.add(Classroom(**r.model_dump()))
    db.add(Audit(user_id=u.id,action=f'catalog_reviewed_import:{semester.id}'));commit(db)
    return {'semester_id':semester.id,'groups':len(data.groups),'rooms':len(data.rooms),'periods':len(data.periods)}
