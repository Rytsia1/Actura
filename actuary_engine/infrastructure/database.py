"""
Centralized database infrastructure for Actura backend.
Exposes a shared SQLAlchemy engine and MetaData object for all repositories.
"""
import os
from sqlalchemy import create_engine, MetaData
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

def init_db():
    """Create the schema if it doesn't exist."""
    metadata.create_all(engine)

def check_db_health() -> bool:
    """Ping the database to verify connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
