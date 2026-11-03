from contextlib import contextmanager
from sqlalchemy.orm import Session
from database.connection import make_engine

engine = make_engine()

@contextmanager
def session_scope():
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
