import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

URL = os.getenv('DATABASE_URL', 'sqlite:///./ba_dms.db')
@event.listens_for(Engine, 'connect')
def sqlite_foreign_keys(connection, record):
    if type(connection).__module__.startswith('sqlite3'):
        cursor=connection.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
engine = create_engine(URL, connect_args={'check_same_thread': False} if URL.startswith('sqlite') else {})
Session = sessionmaker(engine)
class Base(DeclarativeBase):
    pass
def get_db():
    with Session() as session:
        yield session
