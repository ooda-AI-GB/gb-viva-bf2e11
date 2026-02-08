from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./data/maintenance.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # tenant, worker, manager

class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("users.id"))
    unit_number = Column(String)
    category = Column(String)  # plumbing, electrical, HVAC, general
    urgency = Column(String)   # low, medium, high, emergency
    description = Column(Text)
    status = Column(String, default="Pending")  # Pending, In Progress, Completed
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    assigned_worker_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    tenant = relationship("User", foreign_keys=[tenant_id])
    worker = relationship("User", foreign_keys=[assigned_worker_id])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
