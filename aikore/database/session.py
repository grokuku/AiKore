from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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

# This Base class will be used by our ORM models to inherit from.
Base = declarative_base()