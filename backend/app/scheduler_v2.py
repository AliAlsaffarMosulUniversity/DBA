from datetime import date, time
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from ortools.sat.python import cp_model

class Room(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    capacity: int = Field(ge=1, le=1000)
    room_type: str = ''
    equipment: list[str] = Field(default_factory=list, max_length=30)
    blocked: list[int] = Field(default_factory=list, max_length=400)
class Slot(BaseModel):
    name: str = Field(max_length=60)
    start: str = Field(pattern=r'^\d{2}:\d{2}$')
    end: str = Field(pattern=r'^\d{2}:\d{2}$')
    shift: Literal['morning','evening']
class Lesson(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    teacher: int = Field(ge=1)
    group: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=150)
    shift: Literal['morning','evening'] = 'morning'
    size: int = Field(default=30, ge=1, le=1000)
    duration: int = Field(default=1, ge=1, le=4)
    blocked: list[int] = Field(default_factory=list, max_length=400)
    preferred: list[int] = Field(default_factory=list, max_length=400)
    room_type: str = ''
    equipment: list[str] = Field(default_factory=list, max_length=30)
    monitors: int = Field(default=0, ge=0, le=8)
class Monitor(BaseModel):
    teacher: int = Field(ge=1)
    blocked: list[int] = Field(default_factory=list, max_length=400)
    max_sessions: int = Field(default=20, ge=1, le=150)
class Request(BaseModel):
    kind: Literal['weekly','exam']
    plan_key: str = Field(default='', max_length=100)
    days: int = Field(default=5, ge=1, le=30)
    periods: int = Field(default=8, ge=2, le=12)
    dates: list[date] = Field(default_factory=list, max_length=30)
    timeline: list[Slot] = Field(default_factory=list, max_length=12)
    rooms: list[Room] = Field(min_length=1, max_length=100)
    lessons: list[Lesson] = Field(min_length=1, max_length=1000)
    conflicts: list[tuple[str,str]] = Field(default_factory=list, max_length=500)
    monitor_pool: list[Monitor] = Field(default_factory=list, max_length=100)
    teacher_limits: dict[int,int] = Field(default_factory=dict)
    exam_gap_days: int = Field(default=1, ge=0, le=7)
    time_limit: float = Field(default=15, gt=0, le=30)
    @model_validator(mode='after')
    def validate_plan(self):
        if len({x.id for x in self.rooms}) != len(self.rooms) or len({x.id for x in self.lessons}) != len(self.lessons): raise ValueError('معرفات القاعات والجلسات يجب أن تكون فريدة')
        if len({m.teacher for m in self.monitor_pool}) != len(self.monitor_pool): raise ValueError('مراقب مكرر')
        if self.dates and (len(self.dates)!=self.days or self.dates!=sorted(set(self.dates))): raise ValueError('التواريخ يجب أن تكون مرتبة وفريدة وتساوي عدد الأيام')
        if self.timeline:
            if len(self.timeline)!=self.periods: raise ValueError('عدد الفترات لا يطابق الخط الزمني')
            previous=None
            for slot in self.timeline:
                start,end=time.fromisoformat(slot.start),time.fromisoformat(slot.end)
                if start>=end or previous is not None and start<previous: raise ValueError('الفترات متداخلة أو غير مرتبة')
                previous=end
        if len(self.lessons)*(len(self.rooms)+(len(self.monitor_pool) if self.kind=='exam' else 0))>100000: raise ValueError('حجم الخطة كبير؛ قلّل الموارد أو الجلسات')
        return self

from .interval_solver import solve
