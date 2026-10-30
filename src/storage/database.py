import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager

from src.core.constants import ROOT_DIR

logger = logging.getLogger(__name__)

# Define where the local SQLite database will be stored
DB_DIR = ROOT_DIR / "data"
os.makedirs(DB_DIR, exist_ok=True)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_DIR}/assistant.db"

# Create the SQLAlchemy Engine
# connect_args={"check_same_thread": False} is required for SQLite in multi-threaded apps (like our Audio pipeline)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a Base class for our database models to inherit from
Base = declarative_base()

def init_db():
    """
    Creates all tables in the database. 
    Should be called once when the application boots up.
    """
    logger.info(f"Initializing database at {SQLALCHEMY_DATABASE_URL}")
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_db():
    """
    Dependency / Context Manager for getting a database session.
    Automatically handles closing the session after the database operation is complete,
    even if an error occurs.
    
    Usage:
        with get_db() as db:
            user = db.query(User).first()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
