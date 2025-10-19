from sqlalchemy import Boolean, Column, Integer, String
from .session import Base

class Instance(Base):
    """
    SQLAlchemy model representing a configurable WebUI instance.
    """
    __tablename__ = "instances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    base_blueprint = Column(String, nullable=False)
    gpu_ids = Column(String, nullable=True)
    autostart = Column(Boolean, default=False, nullable=False)
    persistent_mode = Column(Boolean, default=False, nullable=False) # <-- ADD THIS LINE
    status = Column(String, default="stopped", nullable=False)
    pid = Column(Integer, nullable=True)
    port = Column(Integer, nullable=True)