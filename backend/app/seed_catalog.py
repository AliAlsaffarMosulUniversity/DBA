from sqlalchemy import select
from .db import Session
from .seed import seed
from .models import Semester, StudentGroup, Classroom, Period, Course, Assignment, User

def seed_catalog():
    seed()
    with Session() as db:
        if db.scalar(select(Semester.id).limit(1)):return
        s=Semester(name='الفصل الأول التجريبي',year='2026–2027',start_date='2026-10-25',end_date='2027-02-28');db.add(s);db.flush()
        groups=[]
        for shift,label in [('morning','صباحي'),('evening','مسائي')]:
            g=StudentGroup(semester_id=s.id,name='المرحلة الأولى / '+label,stage=1,shift=shift,size=35);db.add(g);groups.append(g)
        db.add_all([Classroom(name='قاعة تجريبية 1',capacity=60,room_type='محاضرات',equipment='عارض'),Classroom(name='قاعة تجريبية 2',capacity=45,room_type='محاضرات',equipment='عارض')])
        for shift,hour in [('morning',8),('evening',16)]:
            for i in range(4):db.add(Period(semester_id=s.id,name=f'{"صباح" if shift=="morning" else "مساء"} {i+1}',start=f'{hour+i:02}:00',end=f'{hour+i+1:02}:00',shift=shift))
        teachers=list(db.scalars(select(User).where(User.role!='admin',User.active==True).order_by(User.id)))
        for i,name in enumerate(['مبادئ الإدارة','التسويق','الإدارة المالية','الموارد البشرية']):
            c=Course(name=name,sessions=2,duration=1,exam_duration=2,monitors=2,room_type='محاضرات',equipment='عارض');db.add(c);db.flush()
            for j,g in enumerate(groups):db.flush();db.add(Assignment(course_id=c.id,group_id=g.id,teacher_id=teachers[i+j*4].id))
        db.commit()
if __name__=='__main__':seed_catalog();print('Synthetic catalog initialized without duplicating existing semesters.')
