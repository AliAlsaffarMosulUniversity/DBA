from sqlalchemy import select, func
from .db import Session, engine
from .models import User

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--expected-teachers',type=int,default=45);args=parser.parse_args()
    with Session() as db:
        count = db.scalar(select(func.count(User.id)).where(User.role != 'admin'))
        assert count == args.expected_teachers, f'Expected {args.expected_teachers} teachers, got {count}'
        assert db.scalar(select(User.id).where(User.role == 'admin', User.active == True))
    print(f'PASS: database={engine.dialect.name}; teachers={count}; administrator present')
if __name__ == '__main__': main()
