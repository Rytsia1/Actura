"""
Centralized database infrastructure for Actura backend.
Exposes a shared SQLAlchemy engine and MetaData object for all repositories.
Also provides SQLAlchemy ORM Session components.
"""
import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import text

db_url = os.environ.get("DATABASE_URL", "sqlite:///jobs.db")

# SQLAlchemy requires postgresql:// instead of postgres://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(db_url, connect_args=connect_args)
metadata = MetaData()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """Create the schema if it doesn't exist."""
    metadata.create_all(engine)
    Base.metadata.create_all(engine)

    # SQLite compatibility migration helper for development databases
    if db_url.startswith("sqlite"):
        try:
            with engine.begin() as conn:
                res = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
                cols = {r[1] for r in res}
                if cols and "owner_id" not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN owner_id VARCHAR(100)"))
                if cols and "is_pinned" not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN is_pinned BOOLEAN DEFAULT 0"))
                if cols and "sandbox_state" not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN sandbox_state JSON"))
        except Exception:
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_db_health() -> bool:
    """Ping the database to verify connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
