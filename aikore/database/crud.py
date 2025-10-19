from sqlalchemy.orm import Session
from . import models
from ..schemas import instance as schemas

def get_instance_by_name(db: Session, name: str):
    """
    Retrieve a single instance from the database by its unique name.
    """
    return db.query(models.Instance).filter(models.Instance.name == name).first()

def get_instances(db: Session, skip: int = 0, limit: int = 100):
    """
    Retrieve a list of all instances from the database, with pagination.
    """
    return db.query(models.Instance).offset(skip).limit(limit).all()

def create_instance(db: Session, instance: schemas.InstanceCreate):
    """
    Create a new instance record in the database.
    """
    db_instance = models.Instance(**instance.model_dump())
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    return db_instance

def update_instance_status(db: Session, instance_id: int, status: str, pid: int | None = None, port: int | None = None):
    """
    Update the status, PID, and port of an instance.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        db_instance.status = status
        db_instance.pid = pid
        db_instance.port = port # <-- Update port as well
        db.commit()
        db.refresh(db_instance)
    return db_instance

def get_instance(db: Session, instance_id: int):
    """
    Retrieve a single instance by its ID.
    """
    return db.query(models.Instance).filter(models.Instance.id == instance_id).first()

def delete_instance(db: Session, instance_id: int):
    """
    Delete an instance from the database by its ID.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        db.delete(db_instance)
        db.commit()
    return db_instance