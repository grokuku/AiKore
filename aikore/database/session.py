from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Define the path to the SQLite database file within the persistent /config volume.
SQLALCHEMY_DATABASE_URL = "sqlite:////config/aikore.db"
DATABASE_URL = SQLALCHEMY_DATABASE_URL

# NEW: Define connect_args as a separate variable to be imported
connect_args={"check_same_thread": False}

# Create the SQLAlchemy engine.
# WAL mode enables concurrent reads while a write is in progress, preventing
# the "database is locked" errors that occur with the default journal mode.
# busy_timeout sets how long SQLite waits (in ms) for a lock before raising an error.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={**connect_args, "timeout": 30},
    pool_pre_ping=True,
)

# Enable WAL mode at engine creation time
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

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