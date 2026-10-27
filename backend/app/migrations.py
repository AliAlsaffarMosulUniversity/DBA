"""Versioned, additive migrations; supports the delivered 0.1 database in place.

All identifiers are application-owned constants. Run once before starting workers.
Migration 1 establishes/adopts 0.1 tables; migration 2 adds workflow and catalog.
"""
from sqlalchemy import inspect, text
from .db import Base, engine
from . import models  # register metadata

ADDITIONS = {
    'users': {'active': 'BOOLEAN NOT NULL DEFAULT true', 'token_version': 'INTEGER NOT NULL DEFAULT 0',
              'qualification': "VARCHAR(100) NOT NULL DEFAULT ''", 'detailed_specialty': "VARCHAR(150) NOT NULL DEFAULT ''",
              'email': "VARCHAR(150) NOT NULL DEFAULT ''", 'employment': "VARCHAR(80) NOT NULL DEFAULT ''", 'max_load': 'INTEGER NOT NULL DEFAULT 18'},
    'notices': {'archived': 'BOOLEAN NOT NULL DEFAULT false'},
    'recipients': {'viewed_at': 'VARCHAR(40)'},
    'schedules': {'status': "VARCHAR(20) NOT NULL DEFAULT 'draft'", 'plan_key': "VARCHAR(100) NOT NULL DEFAULT ''",
                  'version': 'INTEGER NOT NULL DEFAULT 1', 'approved_by': 'INTEGER REFERENCES users(id)',
                  'approved_at': 'VARCHAR(40)', 'published_at': 'VARCHAR(40)'}
}

def upgrade(target=engine):
    with target.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)'))
        versions = set(conn.execute(text('SELECT version FROM schema_migrations')).scalars())
        if 1 not in versions:
            # create_all is safe for new installations and adopts unchanged 0.1 tables.
            Base.metadata.create_all(conn)
            conn.execute(text("INSERT INTO schema_migrations VALUES (1, CURRENT_TIMESTAMP)"))
        if 2 not in versions:
            for table, columns in ADDITIONS.items():
                present = {c['name'] for c in inspect(conn).get_columns(table)}
                for name, definition in columns.items():
                    if name not in present:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
            Base.metadata.create_all(conn)
            conn.execute(text("UPDATE schedules SET plan_key = 'legacy-' || CAST(id AS VARCHAR) WHERE plan_key = ''"))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS schedule_plan_version ON schedules (plan_key, version)'))
            conn.execute(text("INSERT INTO schema_migrations VALUES (2, CURRENT_TIMESTAMP)"))
        if 3 not in versions:
            present={c['name'] for c in inspect(conn).get_columns('users')}
            additions={'name_en':"VARCHAR(200) NOT NULL DEFAULT ''",'specialty_en':"VARCHAR(200) NOT NULL DEFAULT ''",'detailed_specialty_en':"VARCHAR(200) NOT NULL DEFAULT ''",'profile_links':"JSON NOT NULL DEFAULT '{}'",'source_ref':'VARCHAR(100)'}
            for name,definition in additions.items():
                if name not in present:conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {definition}'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS user_source_ref ON users (source_ref)'))
            conn.execute(text("INSERT INTO schema_migrations VALUES (3, CURRENT_TIMESTAMP)"))

if __name__ == '__main__':
    upgrade()
    print('Schema upgraded to version 3 (additive, existing records preserved).')
