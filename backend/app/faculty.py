import secrets
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Audit
from .security import admin, hash_password
from .catalog import commit

router=APIRouter(prefix='/api')
LINKS={'scholar','researchgate','ris','orcid','scopus','wos'}
def validate_links(links):
    if len(links)>6:raise HTTPException(422,'روابط أكاديمية كثيرة')
    for key,value in links.items():
        if key not in LINKS or len(value)>2000:raise HTTPException(422,'نوع رابط أكاديمي غير صالح')
        if not value:continue
        try:parsed=urlsplit(value)
        except ValueError:raise HTTPException(422,'رابط أكاديمي غير صالح')
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422,'يجب أن يبدأ الرابط بـ http أو https وألا يحتوي بيانات دخول')

class FacultyData(BaseModel):
    source_ref:str=Field(min_length=8,max_length=100)
    name:str=Field(min_length=2,max_length=150)
    name_en:str=Field(default='',max_length=200)
    qualification:str=Field(default='',max_length=100)
    specialty:str=Field(default='',max_length=100)
    specialty_en:str=Field(default='',max_length=200)
    detailed_specialty:str=Field(default='',max_length=150)
    detailed_specialty_en:str=Field(default='',max_length=200)
    email:str=Field(default='',max_length=150)
    profile_links:dict[str,str]=Field(default_factory=dict)
    bio:str=Field(default='',max_length=4000)
class FacultyBatch(BaseModel):
    profiles:list[FacultyData]=Field(min_length=1,max_length=100)

def apply_faculty(db,user,batch):
    if len({p.source_ref for p in batch.profiles})!=len(batch.profiles) or len({p.name for p in batch.profiles})!=len(batch.profiles):raise HTTPException(422,'سجلات أو أسماء مكررة؛ راجع البيانات قبل الاستيراد')
    created=skipped=0
    for p in batch.profiles:
        validate_links(p.profile_links)
        old=db.scalar(select(User).where(User.source_ref==p.source_ref))
        if old:
            if any(getattr(old,k)!=v for k,v in p.model_dump().items()):raise HTTPException(409,'توجد نسخة مختلفة من سجل مستورد؛ راجعه بدل الكتابة فوقه')
            skipped+=1;continue
        if db.scalar(select(User.id).where(User.name==p.name)):raise HTTPException(409,'الاسم موجود بحساب آخر؛ يلزم ربط يدوي لتجنب الدمج الخاطئ')
        username='faculty-'+p.source_ref[-12:]
        db.add(User(**p.model_dump(),username=username,password=hash_password(secrets.token_urlsafe(48)),role='teacher',active=False,rank='',employment='غير مؤكد',max_load=18))
        created+=1
    db.add(Audit(user_id=user.id,action=f'faculty_import:created={created}:skipped={skipped}'));commit(db)
    return {'created':created,'skipped':skipped,'note':'الحسابات غير مفعلة؛ يحدد المدير أدوارها وألقابها ونصابها وكلمات مرورها قبل استخدامها. 18 فترة حد نظام افتراضي وليس بيانًا من المصدر.'}
@router.post('/faculty-import')
def import_faculty(batch:FacultyBatch,u=Depends(admin),db:Session=Depends(get_db)):
    return apply_faculty(db,u,batch)

if __name__=='__main__':
    import argparse,json
    from pathlib import Path
    from .db import Session
    from .migrations import upgrade
    parser=argparse.ArgumentParser();parser.add_argument('path');args=parser.parse_args()
    batch=FacultyBatch.model_validate(json.loads(Path(args.path).read_text(encoding='utf-8-sig')))
    upgrade()
    with Session() as db:
        administrator=db.scalar(select(User).where(User.role=='admin',User.active==True))
        if not administrator:raise RuntimeError('Initialize an administrator first')
        result=apply_faculty(db,administrator,batch)
        print(f"Imported {result['created']}; skipped {result['skipped']}. Accounts inactive pending administrator review.")
