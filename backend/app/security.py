import os, hashlib, secrets, hmac
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from .db import get_db
from .models import User

SECRET = os.environ.get('JWT_SECRET', '')
if len(SECRET) < 32:
    raise RuntimeError('JWT_SECRET must contain at least 32 characters')
bearer = HTTPBearer()
def hash_password(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()
def verify(password, stored):
    salt, expected = stored.split(':')
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex(), expected)
def token(user):
    return jwt.encode({'sub': str(user.id), 'ver': user.token_version, 'exp': datetime.now(timezone.utc) + timedelta(hours=2)}, SECRET, algorithm='HS256')
def current(credentials=Depends(bearer), db: Session=Depends(get_db)):
    try:
        data = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'])
        user = db.get(User, int(data['sub']))
        if not user or not user.active or data.get('ver') != user.token_version: raise ValueError()
        return user
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, 'جلسة غير صالحة أو منتهية')
def managers(user=Depends(current)):
    if user.role not in ('admin', 'head', 'coordinator'):
        raise HTTPException(403, 'تحتاج صلاحية رئيس القسم أو المقرر')
    return user

def admin(user=Depends(current)):
    if user.role != 'admin': raise HTTPException(403, 'هذه العملية لمدير النظام فقط')
    return user

def approver(user=Depends(current)):
    if user.role not in ('head','admin'): raise HTTPException(403, 'الاعتماد والنشر لرئيس القسم أو المدير')
    return user
