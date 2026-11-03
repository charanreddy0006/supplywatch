import logging
from sqlalchemy.exc import SQLAlchemyError
from database.connection import make_engine, verify_database

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = make_engine()
    try:
        print(f"PostGIS: {verify_database(engine)}")
    except SQLAlchemyError as exc:
        raise SystemExit("Database check failed. Confirm Docker health and DATABASE_URL credentials, then retry.") from exc
    finally:
        engine.dispose()
