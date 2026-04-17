from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Define the path to the SQLite database file within the persistent /config volume.
SQLALCHEMY_DATABASE_URL = "sqlite:////config/aikore.db"
DATABASE_URL = SQLALCHEMY_DATABASE_URL

# NEW: Define connect_args as a separate variable to be imported
connect_args={"check_same_thread": False}

# Create the SQLAlchemy engine.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args
)

# Each instance of the SessionLocal class will be a new database session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Modern SQLAlchemy 2.0+ base class
class Base(DeclarativeBase):
    pass

# Dependency for FastAPI endpoints to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()