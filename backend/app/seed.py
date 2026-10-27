import os
from sqlalchemy import select
from .db import Base, engine, Session
from .models import User, Notice, Recipient
from .security import hash_password
from .migrations import upgrade

def seed():
    upgrade(engine)
    password = os.environ.get('DEMO_PASSWORD')
    if not password or len(password) < 12: raise RuntimeError('Set DEMO_PASSWORD (12+ characters)')
    with Session() as db:
        if db.scalar(select(User.id).limit(1)): return
        db.add(User(username='admin', password=hash_password(password), role='admin', name='مدير النظام التجريبي'))
        first = ['أحمد','سارة','عمر','مريم','خالد','نور','علي','زينب','حسن']
        last = ['التجريبي الأول','التجريبي الثاني','التجريبي الثالث','التجريبي الرابع','التجريبي الخامس']
        for i in range(45):
            db.add(User(username=f'teacher{i+1:02}', password=hash_password(password), role='head' if i == 0 else 'coordinator' if i == 1 else 'teacher', name=f'{first[i%9]} {last[i//9]}', rank=['أستاذ','أستاذ مساعد','مدرس'][i%3], specialty=['إدارة الموارد البشرية','الإدارة الاستراتيجية','التسويق','إدارة العمليات','التمويل'][i%5], qualification='دكتوراه' if i%2==0 else 'ماجستير',detailed_specialty='تخصص تجريبي',email=f'teacher{i+1:02}@example.invalid',employment='مستمر',max_load=18,bio='ملف تجريبي مصطنع لا يمثل شخصًا حقيقيًا.'))
        db.flush()
        notice = Notice(title='مرحبًا بنظام BA-DMS التجريبي', body='يرجى مراجعة ملفك وتأكيد الاطلاع على هذا التبليغ.', author_id=2)
        db.add(notice); db.flush()
        for user in db.scalars(select(User).where(User.role != 'admin')):
            db.add(Recipient(notice_id=notice.id, user_id=user.id))
        db.commit()
if __name__ == '__main__': seed()
