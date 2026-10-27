"""Initialize a clean non-demo installation. Never seeds fictional staff."""
import os
from sqlalchemy import select
from .db import Session
from .models import User
from .migrations import upgrade
from .security import hash_password

def initialize():
    password=os.environ.get('ADMIN_PASSWORD','')
    if len(password)<12:raise RuntimeError('Set ADMIN_PASSWORD (12+ characters)')
    upgrade()
    with Session() as db:
        if db.scalar(select(User.id).where(User.role=='admin')):print('Administrator already exists; no password or data changed.');return
        username=os.environ.get('ADMIN_USERNAME','admin')
        if db.scalar(select(User.id).where(User.username==username)):raise RuntimeError('Administrator username already used')
        db.add(User(username=username,name='مدير النظام',role='admin',password=hash_password(password)));db.commit()
    print('Administrator initialized. No fictional teachers created.')
if __name__=='__main__':initialize()
