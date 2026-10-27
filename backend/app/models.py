from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now():
    return datetime.now(timezone.utc).isoformat()

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    rank: Mapped[str] = mapped_column(String(80), default='')
    specialty: Mapped[str] = mapped_column(String(100), default='')
    bio: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default='true')
    token_version: Mapped[int] = mapped_column(default=0, server_default='0')
    qualification: Mapped[str] = mapped_column(String(100), default='', server_default='')
    detailed_specialty: Mapped[str] = mapped_column(String(150), default='', server_default='')
    email: Mapped[str] = mapped_column(String(150), default='', server_default='')
    employment: Mapped[str] = mapped_column(String(80), default='مستمر', server_default='')
    max_load: Mapped[int] = mapped_column(default=18, server_default='18')
    name_en: Mapped[str] = mapped_column(String(200),default='',server_default='')
    specialty_en: Mapped[str] = mapped_column(String(200),default='',server_default='')
    detailed_specialty_en: Mapped[str] = mapped_column(String(200),default='',server_default='')
    profile_links: Mapped[dict] = mapped_column(JSON,default=dict,server_default='{}')
    source_ref: Mapped[str | None] = mapped_column(String(100),nullable=True,unique=True)

class Notice(Base):
    __tablename__ = 'notices'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')

class Recipient(Base):
    __tablename__ = 'recipients'
    __table_args__ = (UniqueConstraint('notice_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey('notices.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    acknowledged_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    viewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

class Attachment(Base):
    __tablename__ = 'attachments'
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey('notices.id'))
    name: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(50))
    size: Mapped[int]

class Schedule(Base):
    __tablename__ = 'schedules'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='draft', server_default='draft')
    plan_key: Mapped[str] = mapped_column(String(100), default='', server_default='')
    version: Mapped[int] = mapped_column(default=1, server_default='1')
    approved_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

class Semester(Base):
    __tablename__ = 'semesters'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    year: Mapped[str] = mapped_column(String(30))
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))

class StudentGroup(Base):
    __tablename__ = 'student_groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey('semesters.id'))
    name: Mapped[str] = mapped_column(String(80))
    stage: Mapped[int]
    shift: Mapped[str] = mapped_column(String(10))
    size: Mapped[int]

class Course(Base):
    __tablename__ = 'courses'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    sessions: Mapped[int]
    duration: Mapped[int]
    exam_duration: Mapped[int]
    monitors: Mapped[int]
    room_type: Mapped[str] = mapped_column(String(40))
    equipment: Mapped[str] = mapped_column(String(200))

class Assignment(Base):
    __tablename__ = 'assignments'
    __table_args__ = (UniqueConstraint('course_id','group_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    group_id: Mapped[int] = mapped_column(ForeignKey('student_groups.id'))
    teacher_id: Mapped[int] = mapped_column(ForeignKey('users.id'))

class Classroom(Base):
    __tablename__ = 'classrooms'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    capacity: Mapped[int]
    room_type: Mapped[str] = mapped_column(String(40))
    equipment: Mapped[str] = mapped_column(String(200))

class Period(Base):
    __tablename__ = 'periods'
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey('semesters.id'))
    name: Mapped[str] = mapped_column(String(60))
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    shift: Mapped[str] = mapped_column(String(10))

class Unavailable(Base):
    __tablename__ = 'unavailable'
    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('periods.id'))
    weekday: Mapped[int]
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey('classrooms.id'), nullable=True)

class GroupConflict(Base):
    __tablename__ = 'group_conflicts'
    __table_args__ = (UniqueConstraint('first_id','second_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    first_id: Mapped[int] = mapped_column(ForeignKey('student_groups.id'))
    second_id: Mapped[int] = mapped_column(ForeignKey('student_groups.id'))

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    attempted: Mapped[float]

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
