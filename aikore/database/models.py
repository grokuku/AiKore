from sqlalchemy import Boolean, Column, Integer, String, Text
from .session import Base

class AikoreMeta(Base):
    """
    Stores meta-information about the database, such as the version number.
    """
    __tablename__ = "aikore_meta"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)

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
    
    # Tracks if this instance is the one mapped to the static /comfyui/ endpoint
    is_comfyui_active_slot = Column(Boolean, default=False, nullable=False)
    
    # Possible statuses: 'stopped', 'starting', 'stalled', 'started', 'error'
    status = Column(String, default="stopped", nullable=False)
    
    pid = Column(Integer, nullable=True)
    port = Column(Integer, nullable=True) # The public-facing port, user-configurable
    vnc_port = Column(Integer, nullable=True)
    vnc_display = Column(Integer, nullable=True)

    # Defines how the 'Open' URL is constructed: 'port' or 'subdomain'
    access_pattern = Column(String, default="port", nullable=False)