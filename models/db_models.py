from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from pathlib import Path

DB_DIR = Path("db")
DB_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_DIR}/pipeline.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserRecord(Base):
    __tablename__ = "users"
    id          = Column(String, primary_key=True, index=True)
    full_name   = Column(String, nullable=True)
    age         = Column(Integer, nullable=True)
    email       = Column(String, nullable=True)
    department  = Column(String, nullable=True)
    salary      = Column(Float, nullable=True)
    created     = Column(String, nullable=True)
    last_login  = Column(String, nullable=True)
    is_active   = Column(Boolean, nullable=True)
    temperature = Column(Float, nullable=True)
    humidity    = Column(Float, nullable=True)
    pressure    = Column(Float, nullable=True)
    tags        = Column(Text, nullable=True)
    inserted_at = Column(DateTime, default=datetime.utcnow)

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    run_id           = Column(Integer, primary_key=True, autoincrement=True)
    run_at           = Column(DateTime, default=datetime.utcnow)
    records_received = Column(Integer, default=0)
    records_cleaned  = Column(Integer, default=0)
    records_valid    = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    records_failed   = Column(Integer, default=0)
    notes            = Column(Text, nullable=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    print("  Database ready:", DATABASE_URL)
