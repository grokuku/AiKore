from sqlalchemy import Boolean, Column, Integer, String
from .session import Base

# NEW: Model for storing application metadata, such as schema version.
class AikoreMeta(Base):
    """
    SQLAlchemy model for storing key-value metadata.
    """
    __tablename__ = "aikore_meta"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)


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
    persistent_mode = Column(Boolean, default=False, nullable=False)
    hostname = Column(String, nullable=True) # Schema V2 field
    use_custom_hostname = Column(Boolean, default=False, nullable=False, server_default='0')
    
    # Possible statuses: 'stopped', 'starting', 'stalled', 'started'
    status = Column(String, default="stopped", nullable=False)
    
    pid = Column(Integer, nullable=True)
    port = Column(Integer, nullable=True)
    persistent_port = Column(Integer, nullable=True)
    persistent_display = Column(Integer, nullable=True)