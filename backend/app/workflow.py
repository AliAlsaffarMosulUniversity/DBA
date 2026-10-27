import csv, io
from datetime import date, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Semester, StudentGroup, Course, Assignment, Classroom, Period, Unavailable, GroupConflict, Schedule, Notice, Recipient, Audit, now
from .security import current, managers, approver
from .catalog import required, commit
from .scheduler import Request, solve

router=APIRouter(prefix='/api')
def schedule_view(s):
    return {'id':s.id,'kind':s.kind,'created_at':s.created_at,'status':s.status,'plan_key':s.plan_key,'version':s.version,'approved_by':s.approved_by,'approved_at':s.approved_at,'published_at':s.published_at,**s.data}
def save_schedule(db,u,data,result):
    key=data.plan_key or data.kind
    version=(db.scalar(select(func.max(Schedule.version)).where(Schedule.plan_key==key)) or 0)+1
    s=Schedule(kind=data.kind,author_id=u.id,plan_key=key,version=version,status='draft',data={'request':data.model_dump(mode='json'),'result':result})
    db.add(s);db.add(Audit(user_id=u.id,action=f'schedule_generate:{key}:v{version}'));commit(db);return s
class Generate(BaseModel):
    semester_id:int
    kind:Literal['weekly','exam']
    start_date:date
    end_date:date
    weekdays:list[int]=Field(default_factory=lambda:[6,0,1,2,3],min_length=1,max_length=7)
    exam_gap_days:int=Field(default=1,ge=0,le=7)
    monitor_ids:list[int]=Field(default_factory=list,max_length=100)
    monitor_max_sessions:int=Field(default=20,ge=1,le=150)
    plan_name:str=Field(default='الخطة الرئيسية',min_length=1,max_length=50)

def compile_plan(db,data:Generate):
    semester=required(db,Semester,data.semester_id)
    if data.start_date>data.end_date or (data.end_date-data.start_date).days>60:raise HTTPException(422,'مدى الخطة غير صالح أو يتجاوز 60 يومًا')
    if data.start_date.isoformat()<semester.start_date or data.end_date.isoformat()>semester.end_date:raise HTTPException(422,'تواريخ الخطة خارج حدود الفصل')
    if any(w<0 or w>6 for w in data.weekdays):raise HTTPException(422,'أيام عمل غير صالحة')
    dates=[data.start_date+timedelta(days=i) for i in range((data.end_date-data.start_date).days+1) if (data.start_date+timedelta(days=i)).weekday() in data.weekdays]
    if not dates or len(dates)>30:raise HTTPException(422,'اختر من يوم إلى 30 يوم عمل')
    if data.kind=='weekly' and (data.end_date-data.start_date).days>6:raise HTTPException(422,'الجدول الأسبوعي يمثل أسبوعًا واحدًا فقط')
    periods=list(db.scalars(select(Period).where(Period.semester_id==semester.id).order_by(Period.start)))
    if not 2<=len(periods)<=12:raise HTTPException(422,'عرّف من فترتين إلى 12 فترة للفصل')
    availability=list(db.scalars(select(Unavailable).where(Unavailable.period_id.in_([p.id for p in periods]))))
    def blocked(teacher=None,room=None):
        return [d*len(periods)+p for d,dt in enumerate(dates) for p,period in enumerate(periods) if any(a.weekday==dt.weekday() and a.period_id==period.id and ((teacher is not None and a.teacher_id==teacher) or (room is not None and a.room_id==room)) for a in availability)]
    def equipment(text):return [x.strip() for x in text.replace('،',',').split(',') if x.strip()]
    rooms=[{'id':f'R{r.id}','capacity':r.capacity,'room_type':r.room_type,'equipment':equipment(r.equipment),'blocked':blocked(room=r.id)} for r in db.scalars(select(Classroom))]
    groups={g.id:g for g in db.scalars(select(StudentGroup).where(StudentGroup.semester_id==semester.id))}
    lessons=[];limits={};teachers={}
    for a in db.scalars(select(Assignment).where(Assignment.group_id.in_(groups))):
        c=required(db,Course,a.course_id);g=groups[a.group_id];t=required(db,User,a.teacher_id)
        if not t.active or t.role=='admin':raise HTTPException(422,f'تكليف مرتبط بحساب معطل: {t.name}')
        limits[t.id]=t.max_load;teachers[str(t.id)]=t.name
        for n in range(c.sessions if data.kind=='weekly' else 1):
            lessons.append({'id':f'A{a.id}-{n+1}','teacher':t.id,'group':f'G{g.id}','title':c.name,'shift':g.shift,'size':g.size,'duration':c.duration if data.kind=='weekly' else c.exam_duration,'blocked':blocked(teacher=t.id),'room_type':c.room_type,'equipment':equipment(c.equipment),'monitors':c.monitors if data.kind=='exam' else 0})
    pool=[]
    for id in set(data.monitor_ids):
        t=required(db,User,id)
        if not t.active or t.role=='admin':raise HTTPException(422,'المراقب يجب أن يكون تدريسيًا نشطًا')
        teachers[str(t.id)]=t.name;pool.append({'teacher':t.id,'blocked':blocked(teacher=t.id),'max_sessions':data.monitor_max_sessions})
    conflicts=[(f'G{c.first_id}',f'G{c.second_id}') for c in db.scalars(select(GroupConflict)) if c.first_id in groups and c.second_id in groups]
    payload={'kind':data.kind,'plan_key':f'{semester.id}:{data.kind}:{data.plan_name}','days':len(dates),'periods':len(periods),'dates':dates,'timeline':[{'name':p.name,'start':p.start,'end':p.end,'shift':p.shift} for p in periods],'rooms':rooms,'lessons':lessons,'conflicts':conflicts,'monitor_pool':pool,'teacher_limits':limits,'exam_gap_days':data.exam_gap_days}
    try:req=Request.model_validate(payload)
    except ValidationError as e:raise HTTPException(422,'بيانات الخطة غير مكتملة: '+str(e))
    labels={'teachers':teachers,'groups':{f'G{g.id}':g.name for g in groups.values()},'rooms':{f'R{r.id}':r.name for r in db.scalars(select(Classroom))},'semester':semester.name,'year':semester.year}
    return req,labels

@router.post('/plans/generate')
def generate_catalog(data:Generate,u=Depends(managers),db:Session=Depends(get_db)):
    # Serialize version allocation per semester on PostgreSQL.
    db.execute(select(Semester).where(Semester.id==data.semester_id).with_for_update())
    req,labels=compile_plan(db,data);result=solve(req)
    if not result['entries']:raise HTTPException(409,result)
    # Snapshot human labels so later catalog edits do not alter an approved schedule.
    for e in result['entries']:
        e['teacher_name']=labels['teachers'].get(str(e['teacher']),str(e['teacher']))
        e['group_name']=labels['groups'].get(e['group'],e['group'])
        e['room_name']=labels['rooms'].get(e['room'],e['room'])
        e['invigilator_names']=[labels['teachers'][str(t)] for t in e['invigilators']]
    s=save_schedule(db,u,req,result)
    return schedule_view(s)
@router.post('/schedules/{id}/approve')
def approve(id:int,u=Depends(approver),db:Session=Depends(get_db)):
    s=db.scalar(select(Schedule).where(Schedule.id==id).with_for_update())
    if not s:raise HTTPException(404,'الجدول غير موجود')
    if s.status!='draft':raise HTTPException(409,'يمكن اعتماد المسودة فقط')
    req=Request.model_validate(s.data['request'])
    if not req.dates or not req.timeline:raise HTTPException(422,'لا يمكن اعتماد جدول دون تواريخ وأوقات فعلية؛ أعد التوليد من البيانات الأكاديمية')
    s.status='approved';s.approved_by=u.id;s.approved_at=now();db.add(Audit(user_id=u.id,action=f'schedule_approve:{id}'));commit(db);return schedule_view(s)
@router.post('/schedules/{id}/publish')
def publish(id:int,u=Depends(approver),db:Session=Depends(get_db)):
    s=db.scalar(select(Schedule).where(Schedule.id==id).with_for_update())
    if not s:raise HTTPException(404,'الجدول غير موجود')
    if s.status!='approved':raise HTTPException(409,'يجب اعتماد الجدول قبل نشره')
    # A new series must not silently conflict with a separately published plan.
    for other in db.scalars(select(Schedule).where(Schedule.status=='published',Schedule.plan_key!=s.plan_key).with_for_update()):
        pairs={frozenset(p) for p in s.data['request'].get('conflicts',[])+other.data['request'].get('conflicts',[])}
        for a in s.data['result']['entries']:
            for b in other.data['result']['entries']:
                if not a.get('date') or not b.get('date'):continue
                overlap=a['date']==b['date'] and a['start']<b['end'] and b['start']<a['end']
                people_a={a['teacher'],*a.get('invigilators',[])};people_b={b['teacher'],*b.get('invigilators',[])}
                if overlap and (people_a&people_b or a['room']==b['room'] or a['group']==b['group'] or frozenset((a['group'],b['group'])) in pairs):
                    raise HTTPException(409,f'تعارض مع الجدول المنشور رقم {other.id}؛ راجع الخطة أو استبدل إصدار السلسلة نفسها')
    db.execute(update(Schedule).where(Schedule.plan_key==s.plan_key,Schedule.status=='published').values(status='archived'))
    s.status='published';s.published_at=now();db.add(Audit(user_id=u.id,action=f'schedule_publish:{id}'));commit(db);return schedule_view(s)
@router.post('/notices/{id}/view')
def viewed(id:int,u=Depends(current),db:Session=Depends(get_db)):
    required(db,Notice,id);r=db.scalar(select(Recipient).where(Recipient.notice_id==id,Recipient.user_id==u.id))
    if not r:raise HTTPException(403,'التبليغ غير موجه إليك')
    if not r.viewed_at:r.viewed_at=now()
    commit(db);return {'viewed_at':r.viewed_at}
class Archive(BaseModel):
    archived:bool
@router.patch('/notices/{id}/archive')
def archive_notice(id:int,data:Archive,u=Depends(managers),db:Session=Depends(get_db)):
    n=required(db,Notice,id);n.archived=data.archived;db.add(Audit(user_id=u.id,action=f'notice_archive:{id}:{data.archived}'));commit(db);return {'ok':True}
def csv_response(rows,filename):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    for row in rows:
        # Prevent spreadsheet formula injection in user-controlled values.
        writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@','\t','\r')) else x for x in row])
    return Response(content=('\ufeff'+stream.getvalue()).encode('utf-8'),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{filename}"'})
@router.get('/schedules/{id}/export.csv')
def export_schedule(id:int,teacher:int|None=None,group:str='',room:str='',shift:str='',u=Depends(current),db:Session=Depends(get_db)):
    s=required(db,Schedule,id)
    if u.role=='teacher' and s.status!='published':raise HTTPException(403,'الجدول لم ينشر بعد')
    rows=[['المادة','التاريخ','البداية','النهاية','التدريسي','الشعبة','القاعة','الدراسة','المراقبون']]
    for e in s.data['result']['entries']:
        if teacher and e['teacher']!=teacher and teacher not in e.get('invigilators',[]):continue
        if group and e['group']!=group or room and e['room']!=room or shift and e['shift']!=shift:continue
        rows.append([e['title'],e.get('date') or e['day']+1,e.get('start') or e['period']+1,e.get('end') or '',e.get('teacher_name') or e['teacher'],e.get('group_name') or e['group'],e.get('room_name') or e['room'],'صباحي' if e['shift']=='morning' else 'مسائي','، '.join(e.get('invigilator_names',map(str,e.get('invigilators',[]))))])
    return csv_response(rows,f'schedule-{id}.csv')
@router.get('/notices/{id}/receipts.csv')
def export_receipts(id:int,u=Depends(managers),db:Session=Depends(get_db)):
    required(db,Notice,id)
    rows=[['المستلم','وقت العرض','تأكيد الاطلاع']]
    for r in db.scalars(select(Recipient).where(Recipient.notice_id==id)):
        rows.append([required(db,User,r.user_id).name,r.viewed_at or '',r.acknowledged_at or ''])
    return csv_response(rows,f'receipts-{id}.csv')
