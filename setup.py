import os, json
from pathlib import Path

ROOT = Path(__file__).parent

def make(path, content):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.lstrip("\n"))
    print(f"  created  {path}")

def folder(path):
    (ROOT / path).mkdir(parents=True, exist_ok=True)
    print(f"  folder   {path}/")

print("Building your project...")

for d in ["data/raw","data/cleaned","data/validated","data/invalid",
          "pipeline","models","api","db","logs",
          ".claude/commands",".vscode"]:
    folder(d)

make("data/raw/sample_raw.json", json.dumps([
  {"id":"USR-001","full_name":"Alice Chen","age":"29","email":"alice.chen@example.com",
   "sensor_data":{"temperature":72.3,"humidity":None,"pressure":1012.5},
   "tags":["active","vip"],"department":"Engineering","salary":"$95,000",
   "created":"2024-01-15","last_login":"2024-03-10T14:32:00Z","is_active":"true"},
  {"id":"USR-001","full_name":"Alice Chen","age":29,"email":"alice.chen@example.com",
   "sensor_data":{"temperature":72.3,"humidity":45.1,"pressure":1012.5},
   "tags":"active","department":"Engineering","salary":"$95,000",
   "created":"01/15/2024","last_login":"2024-03-10T14:32:00Z","is_active":True},
  {"id":"USR-002","full_name":"Bob Martinez","age":34,"email":"bob.martinez@example.com",
   "sensor_data":{"temperature":68.1,"humidity":55.0,"pressure":None},
   "tags":["active","manager"],"department":"Sales","salary":"82500",
   "created":"2023-11-20","last_login":"2024-03-11T09:15:00Z","is_active":True},
  {"id":"USR-003","full_name":None,"age":-5,"email":"not-an-email",
   "sensor_data":{},"tags":[],"department":None,"salary":None,
   "created":None,"last_login":None,"is_active":None},
  {"id":"USR-004","full_name":"Diana Patel","age":41,"email":"diana.patel@example.com",
   "sensor_data":{"temperature":70.5,"humidity":48.3,"pressure":1015.2},
   "tags":["active","lead","remote"],"department":"Data Science","salary":110000,
   "created":"2022-06-01","last_login":"2024-03-12T11:00:00Z","is_active":True},
  {"id":"USR-005","full_name":"Ethan Brooks","age":"UNKNOWN","email":"ethan@example.com",
   "sensor_data":{"temperature":None,"humidity":60.2,"pressure":1008.1},
   "tags":["inactive"],"department":"HR","salary":"$72,000",
   "created":"03-22-2023","last_login":None,"is_active":"false"},
  {"id":"USR-006","full_name":"Fiona Kim","age":27,"email":"fiona.kim@example.com",
   "sensor_data":{"temperature":69.8,"humidity":52.0,"pressure":1011.3},
   "tags":["active","intern"],"department":"Design","salary":58000,
   "created":"2024-02-01","last_login":"2024-03-09T08:45:00Z","is_active":True}
], indent=2))

make(".claude/commands/clean.md", """
You are a data cleaning expert. When I run /clean, do ALL of this automatically without asking me questions:
1. Read data/raw/sample_raw.json
2. Print what problems you find
3. Write pipeline/01_clean.py that fixes: duplicates (keep last by id), age coerced to int, dates normalized to YYYY-MM-DD, salary stripped of $ and commas converted to float, tags always a list, is_active always boolean, sensor_data missing keys filled with None
4. Run the script immediately
5. Write change log to logs/01_clean_log.json
6. Tell me: how many records in, duplicates removed, output location
""")

make(".claude/commands/validate.md", """
You are a data validation expert. When I run /validate, do ALL of this automatically without asking me questions:
1. Read data/cleaned/sample_clean.json
2. Write pipeline/02_validate.py using Pydantic v2 with these rules: id required, full_name required not null, age 0-120 if present, email must have @, salary positive if present, created valid YYYY-MM-DD if present
3. Run it immediately
4. Write passing records to data/validated/sample_valid.json
5. Write failing records with reasons to data/invalid/sample_invalid.json
6. Write summary to logs/02_validate_log.json
7. Tell me: how many passed, how many failed and why
""")

make(".claude/commands/store.md", """
You are a database engineer. When I run /store, do ALL of this automatically without asking me questions:
1. Read data/validated/sample_valid.json
2. Write pipeline/03_store.py that imports models/db_models.py, calls init_db(), upserts every record (insert if new id, update if exists), flattens sensor_data into columns, converts tags list to comma-separated string
3. Run it immediately
4. Write results to logs/03_store_log.json
5. Tell me: how many inserted, updated, failed, and the database file location
""")

make(".claude/commands/monitor.md", """
You are a pipeline monitor. When I run /monitor, do ALL of this automatically without asking me questions:
1. Read logs/01_clean_log.json, logs/02_validate_log.json, logs/03_store_log.json
2. Flag missing logs as ERROR
3. Calculate: records received, survived cleaning, passed validation, stored successfully, overall yield %
4. Flag WARNING if rejection rate > 20%, ERROR if store failure > 5%
5. Write report to logs/pipeline_report.json
6. Print a clear human-readable summary
""")

make("models/db_models.py", """
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
""")

make("api/main.py", """
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.db_models import UserRecord as DBUser, PipelineRun as DBRun, get_db, init_db

app = FastAPI(title="Data Pipeline API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup(): init_db()

class SensorOut(BaseModel):
    temperature: Optional[float]=None
    humidity: Optional[float]=None
    pressure: Optional[float]=None

class UserOut(BaseModel):
    id: str
    full_name: Optional[str]=None
    age: Optional[int]=None
    email: Optional[str]=None
    department: Optional[str]=None
    salary: Optional[float]=None
    created: Optional[str]=None
    last_login: Optional[str]=None
    is_active: Optional[bool]=None
    tags: list[str]=[]
    sensor_data: SensorOut
    inserted_at: Optional[datetime]=None
    model_config={"from_attributes":True}

class UserCreate(BaseModel):
    id: str
    full_name: str
    age: Optional[int]=None
    email: str
    department: Optional[str]=None
    salary: Optional[float]=None
    created: Optional[str]=None
    is_active: Optional[bool]=True
    tags: list[str]=[]
    temperature: Optional[float]=None
    humidity: Optional[float]=None
    pressure: Optional[float]=None

def to_out(u):
    return UserOut(id=u.id,full_name=u.full_name,age=u.age,email=u.email,
        department=u.department,salary=u.salary,created=u.created,
        last_login=u.last_login,is_active=u.is_active,
        tags=u.tags.split(",") if u.tags else [],
        sensor_data=SensorOut(temperature=u.temperature,humidity=u.humidity,pressure=u.pressure),
        inserted_at=u.inserted_at)

@app.get("/health")
def health(): return {"status":"ok","time":datetime.utcnow().isoformat()}

@app.get("/users", response_model=list[UserOut])
def list_users(db:Session=Depends(get_db),limit:int=Query(20,ge=1,le=100),
    offset:int=Query(0,ge=0),department:Optional[str]=None,
    is_active:Optional[bool]=None,min_salary:Optional[float]=None,max_salary:Optional[float]=None):
    q=db.query(DBUser)
    if department: q=q.filter(DBUser.department==department)
    if is_active is not None: q=q.filter(DBUser.is_active==is_active)
    if min_salary: q=q.filter(DBUser.salary>=min_salary)
    if max_salary: q=q.filter(DBUser.salary<=max_salary)
    return [to_out(r) for r in q.offset(offset).limit(limit).all()]

@app.get("/users/stats/summary")
def stats(db:Session=Depends(get_db)):
    all_u=db.query(DBUser).all()
    if not all_u: raise HTTPException(404,"No users yet")
    salaries=[u.salary for u in all_u if u.salary]
    ages=[u.age for u in all_u if u.age]
    depts={}
    for u in all_u:
        d=u.department or "Unknown"
        depts[d]=depts.get(d,0)+1
    return {"total_users":len(all_u),"active_users":sum(1 for u in all_u if u.is_active),
        "avg_salary":round(sum(salaries)/len(salaries),2) if salaries else None,
        "avg_age":round(sum(ages)/len(ages),1) if ages else None,"departments":depts}

@app.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id:str,db:Session=Depends(get_db)):
    u=db.query(DBUser).filter(DBUser.id==user_id).first()
    if not u: raise HTTPException(404,f"User {user_id} not found")
    return to_out(u)

@app.post("/users",response_model=UserOut,status_code=201)
def create_user(p:UserCreate,db:Session=Depends(get_db)):
    if db.query(DBUser).filter(DBUser.id==p.id).first():
        raise HTTPException(409,f"User {p.id} already exists")
    u=DBUser(id=p.id,full_name=p.full_name,age=p.age,email=p.email,
        department=p.department,salary=p.salary,created=p.created,
        is_active=p.is_active,tags=",".join(p.tags) if p.tags else None,
        temperature=p.temperature,humidity=p.humidity,pressure=p.pressure,
        inserted_at=datetime.utcnow())
    db.add(u); db.commit(); db.refresh(u)
    return to_out(u)

@app.delete("/users/{user_id}")
def delete_user(user_id:str,db:Session=Depends(get_db)):
    u=db.query(DBUser).filter(DBUser.id==user_id).first()
    if not u: raise HTTPException(404,f"User {user_id} not found")
    db.delete(u); db.commit()
    return {"message":f"User {user_id} deleted"}

@app.get("/pipeline/runs")
def pipeline_runs(db:Session=Depends(get_db)):
    return db.query(DBRun).order_by(DBRun.run_at.desc()).all()
""")

make("CLAUDE.md", """
# My Data Engineering Project

## Folder structure
- data/raw/           drop new raw JSON files here
- data/cleaned/       output of /clean
- data/validated/     output of /validate
- data/invalid/       records that failed validation
- pipeline/           Python scripts generated by skills
- models/db_models.py SQLAlchemy ORM
- api/main.py         FastAPI app
- db/pipeline.db      SQLite database
- logs/               one JSON log per step

## Pipeline order
/clean then /validate then /store then /monitor

## Start API
uvicorn api.main:app --reload
Open: http://localhost:8000/docs
""")

make("requirements.txt", """fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
pydantic>=2.6.0
python-dateutil>=2.9.0
""")

print()
print("DONE! Everything created.")
print()
print("Next steps:")
print("  1.  python -m venv venv")
print("  2.  source venv/bin/activate")
print("  3.  pip install -r requirements.txt")
print("  4.  npm install -g @anthropic-ai/claude-code")
print("  5.  claude")
print("  6.  Then type /clean at the > prompt")