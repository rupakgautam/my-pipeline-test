# Version 1 — Local Pipeline: FULL Detailed Walkthrough (nothing skipped)

This is the **original, local** version of the project — the one that runs on
your laptop with **SQLite**. Every script, command, and expected result is here,
explained for a beginner. (The cloud version is in `AWS-WALKTHROUGH-DETAILED.md`.)

---

## 0. The end-to-end flow (read this first)

```
 data/raw/sample_raw.json
        │
        ▼  python pipeline/01_clean.py        (skill: /clean)
 data/cleaned/sample_cleaned.json   + logs/01_clean_log.json
        │
        ▼  python pipeline/02_validate.py     (skill: /validate)
 data/validated/sample_valid.json
 data/invalid/sample_invalid.json   + logs/02_validate_log.json
        │
        ▼  python pipeline/03_store.py        (skill: /store)
 db/pipeline.db  (SQLite "users" table)        + logs/03_store_log.json
        │
        ▼  python pipeline/04_monitor.py      (skill: /monitor)
 logs/pipeline_report.json   (funnel + health flags)

 Separately:  uvicorn api.main:app --reload   →  http://localhost:8000
              FastAPI reads db/pipeline.db, guarded by an API key.
```

**How each step connects to the next:** every step reads the **file the previous
step wrote** and writes its own output file plus a **JSON log**. The final
`monitor` step reads those three logs (`01_clean_log.json`, `02_validate_log.json`,
`03_store_log.json`) to compute a health report. **You** run the steps in order —
there is no automatic trigger (that's the big difference from the AWS version).

> **Key contrast with AWS:** here, steps communicate through **files on disk +
> log files**, and a **human** runs them in order. In AWS, steps pass a **JSON
> payload** to each other and an **event** runs them automatically.

---

## 1. Project layout (local pieces only)

```
my-pipeline/
├── data/
│   ├── raw/         ← you drop raw JSON here (input)
│   ├── cleaned/     ← output of step 1
│   ├── validated/   ← output of step 2 (passed records)
│   └── invalid/     ← output of step 2 (failed records)
├── pipeline/
│   ├── 01_clean.py
│   ├── 02_validate.py
│   ├── 03_store.py
│   └── 04_monitor.py
├── models/db_models.py   ← SQLAlchemy ORM (SQLite)
├── api/main.py           ← FastAPI app
├── db/pipeline.db        ← the SQLite database (created on first store)
├── logs/                 ← one JSON log per step
└── requirements.txt
```

---

## 2. Setup (one time)

### Commands
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
### `requirements.txt`
```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
pydantic>=2.6.0
python-dateutil>=2.9.0
```
### What each does
- `python -m venv venv` — create an isolated "virtual environment" so this
  project's packages don't clash with others on your machine.
- `source venv/bin/activate` — switch your shell into that environment.
- `pip install -r requirements.txt` — install the libraries the project needs:
  - **fastapi** — the web framework for the API.
  - **uvicorn** — the server that runs FastAPI locally.
  - **sqlalchemy** — talks to the database with Python objects instead of raw SQL.
  - **pydantic** — validates data against rules.
  - **python-dateutil** — flexible date parsing.

### Why
Everything runs with plain `python` on your laptop; there are no servers or cloud
accounts. The virtual environment keeps it clean and reproducible.

---

## 3. The input data

File `data/raw/sample_raw.json` — deliberately messy, to exercise the pipeline:
```json
[
  { "id": "USR-001", "full_name": "Alice Chen", "age": "29", "email": "alice.chen@example.com",
    "sensor_data": { "temperature": 72.3, "humidity": null, "pressure": 1012.5 },
    "tags": ["active", "vip"], "department": "Engineering", "salary": "$95,000",
    "created": "2024-01-15", "last_login": "2024-03-10T14:32:00Z", "is_active": "true" },

  { "id": "USR-001", "full_name": "Alice Chen", "age": 29, "email": "alice.chen@example.com",
    "sensor_data": { "temperature": 72.3, "humidity": 45.1, "pressure": 1012.5 },
    "tags": "active", "department": "Engineering", "salary": "$95,000",
    "created": "01/15/2024", "last_login": "2024-03-10T14:32:00Z", "is_active": true },

  { "id": "USR-002", "full_name": "Bob Martinez", "age": 34, "email": "bob.martinez@example.com",
    "sensor_data": { "temperature": 68.1, "humidity": 55.0, "pressure": null },
    "tags": ["active", "manager"], "department": "Sales", "salary": "82500",
    "created": "2023-11-20", "last_login": "2024-03-11T09:15:00Z", "is_active": true },

  { "id": "USR-003", "full_name": null, "age": -5, "email": "not-an-email",
    "sensor_data": {}, "tags": [], "department": null, "salary": null,
    "created": null, "last_login": null, "is_active": null },

  { "id": "USR-004", "full_name": "Diana Patel", "age": 41, "email": "diana.patel@example.com",
    "sensor_data": { "temperature": 70.5, "humidity": 48.3, "pressure": 1015.2 },
    "tags": ["active", "lead", "remote"], "department": "Data Science", "salary": 110000,
    "created": "2022-06-01", "last_login": "2024-03-12T11:00:00Z", "is_active": true },

  { "id": "USR-005", "full_name": "Ethan Brooks", "age": "UNKNOWN", "email": "ethan@example.com",
    "sensor_data": { "temperature": null, "humidity": 60.2, "pressure": 1008.1 },
    "tags": ["inactive"], "department": "HR", "salary": "$72,000",
    "created": "03-22-2023", "last_login": null, "is_active": "false" },

  { "id": "USR-006", "full_name": "Fiona Kim", "age": 27, "email": "fiona.kim@example.com",
    "sensor_data": { "temperature": 69.8, "humidity": 52.0, "pressure": 1011.3 },
    "tags": ["active", "intern"], "department": "Design", "salary": 58000,
    "created": "2024-02-01", "last_login": "2024-03-09T08:45:00Z", "is_active": true }
]
```
**The problems planted here (so you can watch the pipeline fix/catch them):**
- **`USR-001` appears twice** (a duplicate) → clean keeps the last one.
- Mixed types: `age` as `"29"` (string) and `"UNKNOWN"`; `salary` as `"$95,000"`, `"82500"`, and `110000`.
- Mixed date formats: `2024-01-15`, `01/15/2024`, `03-22-2023`.
- `tags` sometimes a list, sometimes a string `"active"`.
- `is_active` as `"true"`, `true`, `"false"`, `null`.
- **`USR-003` is broken**: `full_name` null, `email` "not-an-email", `age` -5 → validation will reject it.

So: **7 records in → 1 duplicate removed → 6 cleaned → 1 invalid → 5 valid → 5 stored.**

---

## 4. The skills (`/clean`, `/validate`, `/store`, `/monitor`)

Each slash-command is a saved instruction that writes **and runs** one pipeline
script. For example, `.claude/commands/clean.md` says:
> "When I run `/clean`: read `data/raw/sample_raw.json`, print the problems, write
> `pipeline/01_clean.py` that fixes duplicates/age/dates/salary/tags/is_active/
> sensor_data, run it, write a log to `logs/01_clean_log.json`, and report counts."

The result of those skills is the four scripts below. You can re-run them anytime
with plain `python`.

---

## 5. Step 1 — `pipeline/01_clean.py` (clean)

### How to run
```bash
python pipeline/01_clean.py
```
### Why
Raw data is messy and inconsistent. Cleaning makes every record structurally
uniform so the later steps can trust the shape of the data.

### Full script
```python
"""
01_clean.py — Data cleaning step.
Reads data/raw/sample_raw.json, fixes structural/type problems, writes
data/cleaned/, and a change log to logs/01_clean_log.json.
"""

import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PATH = os.path.join(BASE_DIR, "data", "raw", "sample_raw.json")
CLEANED_DIR = os.path.join(BASE_DIR, "data", "cleaned")
CLEANED_PATH = os.path.join(CLEANED_DIR, "sample_cleaned.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "01_clean_log.json")

SENSOR_KEYS = ("temperature", "humidity", "pressure")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d")
TRUE_VALUES = {"true", "1", "yes", "y", "t"}
FALSE_VALUES = {"false", "0", "no", "n", "f"}


def clean_age(value):
    """Coerce age to a positive int; return None if not possible."""
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return None
    return age if age > 0 else None


def clean_date(value):
    """Normalize a date string to YYYY-MM-DD; return None on failure."""
    if not value:
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def clean_salary(value):
    """Strip $ and commas, convert to float; return None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def clean_tags(value):
    """Always return a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value else []
    return [value]


def clean_is_active(value):
    """Coerce to boolean; return None when unknown."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def clean_sensor_data(value):
    """Ensure all sensor keys exist; fill missing with None."""
    data = value if isinstance(value, dict) else {}
    return {key: data.get(key, None) for key in SENSOR_KEYS}


def clean_record(record):
    cleaned = dict(record)
    cleaned["age"] = clean_age(record.get("age"))
    cleaned["created"] = clean_date(record.get("created"))
    cleaned["last_login"] = clean_date(record.get("last_login"))
    cleaned["salary"] = clean_salary(record.get("salary"))
    cleaned["tags"] = clean_tags(record.get("tags"))
    cleaned["is_active"] = clean_is_active(record.get("is_active"))
    cleaned["sensor_data"] = clean_sensor_data(record.get("sensor_data"))
    return cleaned


def main():
    os.makedirs(CLEANED_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    with open(RAW_PATH, "r", encoding="utf-8") as fh:
        raw_records = json.load(fh)

    records_in = len(raw_records)

    # Deduplicate by id, keeping the LAST occurrence.
    deduped = {}
    for record in raw_records:
        deduped[record.get("id")] = record
    duplicates_removed = records_in - len(deduped)

    cleaned_records = [clean_record(rec) for rec in deduped.values()]

    with open(CLEANED_PATH, "w", encoding="utf-8") as fh:
        json.dump(cleaned_records, fh, indent=2)

    log = {
        "step": "01_clean",
        "timestamp": datetime.now().isoformat(),
        "input_path": RAW_PATH,
        "output_path": CLEANED_PATH,
        "records_in": records_in,
        "duplicates_removed": duplicates_removed,
        "records_out": len(cleaned_records),
        "fixes_applied": [
            "duplicates removed (kept last by id)",
            "age coerced to int (invalid -> None)",
            "dates normalized to YYYY-MM-DD",
            "salary stripped of $ and commas -> float",
            "tags coerced to list",
            "is_active coerced to boolean",
            "sensor_data missing keys filled with None",
        ],
    }
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)

    print(f"Records in:          {records_in}")
    print(f"Duplicates removed:  {duplicates_removed}")
    print(f"Records out:         {len(cleaned_records)}")
    print(f"Output location:     {CLEANED_PATH}")
    print(f"Log location:        {LOG_PATH}")


if __name__ == "__main__":
    main()
```
### What the code does
- `BASE_DIR/...` lines build absolute file paths so the script works from any folder.
- Each `clean_*` function fixes one field: `clean_age` turns `"29"`→29 and `"UNKNOWN"`/`-5`→None; `clean_date` understands several date formats and strips the time off ISO timestamps; `clean_salary` removes `$` and `,`; `clean_tags` forces a list; `clean_is_active` maps `"true"`/`"false"`→booleans; `clean_sensor_data` guarantees all three sensor keys exist.
- `main()` loads the raw file, **dedupes by `id` keeping the last** (a dict overwrites earlier entries), cleans each record, writes `cleaned/`, and writes a log with counts.
- `if __name__ == "__main__": main()` runs `main()` when you execute the file.

### Expected output
```
Records in:          7
Duplicates removed:  1
Records out:         6
```
Plus `data/cleaned/sample_cleaned.json` and `logs/01_clean_log.json`. Matters
because every later step depends on clean, uniform records.

---

## 6. Step 2 — `pipeline/02_validate.py` (validate)

### How to run
```bash
python pipeline/02_validate.py
```
### Why
Cleaning makes data *uniform*; validation enforces *business rules* (required
fields, valid email, sane ranges) and separates good records from bad ones so
bad data never reaches the database.

### Full script
```python
"""
02_validate.py — Data validation step.
Reads cleaned records, validates each against a Pydantic v2 model, and splits
them into valid / invalid output files. Summary -> logs/02_validate_log.json.
"""

import json
import os
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEANED_PATH = os.path.join(BASE_DIR, "data", "cleaned", "sample_cleaned.json")
VALID_DIR = os.path.join(BASE_DIR, "data", "validated")
VALID_PATH = os.path.join(VALID_DIR, "sample_valid.json")
INVALID_DIR = os.path.join(BASE_DIR, "data", "invalid")
INVALID_PATH = os.path.join(INVALID_DIR, "sample_invalid.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "02_validate_log.json")


class Record(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    full_name: str
    age: Optional[int] = None
    email: str
    salary: Optional[float] = None
    created: Optional[str] = None

    @field_validator("id")
    @classmethod
    def id_required(cls, v):
        if v is None or str(v).strip() == "":
            raise ValueError("id is required")
        return v

    @field_validator("full_name")
    @classmethod
    def full_name_not_null(cls, v):
        if v is None or str(v).strip() == "":
            raise ValueError("full_name is required and must not be null")
        return v

    @field_validator("age")
    @classmethod
    def age_in_range(cls, v):
        if v is not None and not (0 <= v <= 120):
            raise ValueError("age must be between 0 and 120")
        return v

    @field_validator("email")
    @classmethod
    def email_has_at(cls, v):
        if v is None or "@" not in v:
            raise ValueError("email must contain '@'")
        return v

    @field_validator("salary")
    @classmethod
    def salary_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("salary must be positive if present")
        return v

    @field_validator("created")
    @classmethod
    def created_valid_date(cls, v):
        if v is not None:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError("created must be a valid YYYY-MM-DD date")
        return v


def main():
    os.makedirs(VALID_DIR, exist_ok=True)
    os.makedirs(INVALID_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    with open(CLEANED_PATH, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    valid_records = []
    invalid_records = []

    for record in records:
        try:
            Record.model_validate(record)
            valid_records.append(record)
        except Exception as exc:
            reasons = []
            errors = getattr(exc, "errors", None)
            if callable(errors):
                for err in exc.errors():
                    field = ".".join(str(p) for p in err.get("loc", [])) or "?"
                    msg = err.get("msg", "invalid")
                    reasons.append(f"{field}: {msg}")
            else:
                reasons.append(str(exc))
            invalid_records.append({**record, "_errors": reasons})

    with open(VALID_PATH, "w", encoding="utf-8") as fh:
        json.dump(valid_records, fh, indent=2)
    with open(INVALID_PATH, "w", encoding="utf-8") as fh:
        json.dump(invalid_records, fh, indent=2)

    log = {
        "step": "02_validate",
        "timestamp": datetime.now().isoformat(),
        "input_path": CLEANED_PATH,
        "valid_path": VALID_PATH,
        "invalid_path": INVALID_PATH,
        "records_in": len(records),
        "passed": len(valid_records),
        "failed": len(invalid_records),
        "failures": [
            {"id": r.get("id"), "reasons": r["_errors"]} for r in invalid_records
        ],
    }
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)

    print(f"Records in:  {len(records)}")
    print(f"Passed:      {len(valid_records)}")
    print(f"Failed:      {len(invalid_records)}")
    for r in invalid_records:
        print(f"  - {r.get('id')}: {'; '.join(r['_errors'])}")


if __name__ == "__main__":
    main()
```
### What the code does
- `class Record(BaseModel)` defines the rules. `extra="allow"` keeps fields not
  listed (like `tags`, `sensor_data`). Each `@field_validator` is a rule: `id`
  and `full_name` required, `age` 0–120, `email` must contain `@`, `salary`
  positive, `created` a real `YYYY-MM-DD` date.
- `main()` loads cleaned records, tries `Record.model_validate(record)` on each;
  passers go to `validated/`, failures (with human-readable `_errors`) go to
  `invalid/`. A log records who failed and why.

### Expected output
```
Records in:  6
Passed:      5
Failed:      1
  - USR-003: full_name: ... ; email: must contain '@'
```
`USR-003` is rejected (null name + bad email). Matters because only the 5 good
records continue to the database.

---

## 7. Step 3 — `pipeline/03_store.py` (store)

### How to run
```bash
python pipeline/03_store.py
```
### Why
Files are fine for processing, but to **query** the data you need a database.
This step writes the valid records into SQLite, upserting by `id`.

### The database models — `models/db_models.py`
```python
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
```
**What it does:** `DATABASE_URL = "sqlite:///db/pipeline.db"` points SQLAlchemy at
a local file. `UserRecord` describes the `users` table as a Python class (one
attribute per column). `init_db()` creates the tables if they don't exist.

### The store script — `pipeline/03_store.py`
```python
"""
03_store.py — Database store step.
Reads data/validated/sample_valid.json and upserts each record into the SQLite
`users` table. sensor_data is flattened into temperature/humidity/pressure; tags
is stored as a comma-separated string. Results -> logs/03_store_log.json.
"""

import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from models.db_models import UserRecord, SessionLocal, init_db, DATABASE_URL  # noqa: E402

VALID_PATH = os.path.join(BASE_DIR, "data", "validated", "sample_valid.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "03_store_log.json")


def to_columns(record):
    """Map a validated record onto UserRecord columns."""
    sensor = record.get("sensor_data") or {}
    tags = record.get("tags") or []
    tags_str = ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
    return {
        "id": record.get("id"),
        "full_name": record.get("full_name"),
        "age": record.get("age"),
        "email": record.get("email"),
        "department": record.get("department"),
        "salary": record.get("salary"),
        "created": record.get("created"),
        "last_login": record.get("last_login"),
        "is_active": record.get("is_active"),
        "temperature": sensor.get("temperature"),
        "humidity": sensor.get("humidity"),
        "pressure": sensor.get("pressure"),
        "tags": tags_str,
    }


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    init_db()

    with open(VALID_PATH, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    inserted, updated, failed = 0, 0, 0
    failures = []

    session = SessionLocal()
    try:
        for record in records:
            rec_id = record.get("id")
            try:
                cols = to_columns(record)
                existing = session.get(UserRecord, rec_id)
                if existing is None:
                    session.add(UserRecord(**cols))
                    inserted += 1
                else:
                    for key, value in cols.items():
                        if key == "id":
                            continue
                        setattr(existing, key, value)
                    updated += 1
                session.commit()
            except Exception as exc:
                session.rollback()
                failed += 1
                failures.append({"id": rec_id, "error": str(exc)})
    finally:
        session.close()

    log = {
        "step": "03_store",
        "timestamp": datetime.now().isoformat(),
        "input_path": VALID_PATH,
        "database_url": DATABASE_URL,
        "records_in": len(records),
        "inserted": inserted,
        "updated": updated,
        "failed": failed,
        "failures": failures,
    }
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)

    print(f"Records in:  {len(records)}")
    print(f"Inserted:    {inserted}")
    print(f"Updated:     {updated}")
    print(f"Failed:      {failed}")


if __name__ == "__main__":
    main()
```
### What the code does
- `sys.path.insert` + `os.chdir(BASE_DIR)` make sure it can import `models/` and
  that the SQLite file path resolves correctly.
- `to_columns` flattens each record to match the table: `sensor_data` becomes
  three columns; the `tags` list becomes a comma string.
- The loop is a manual **upsert**: `session.get(UserRecord, id)` — if not found,
  `add` a new row (insert); if found, copy each field onto it (update).
  `commit()` saves; `rollback()` undoes on error.

### Expected output
```
Records in:  5
Inserted:    5
Updated:     0
Failed:      0
```
Creates `db/pipeline.db`. Run it again → `Updated: 5` (the upsert in action).
Matters because the data is now queryable.

---

## 8. Step 4 — `pipeline/04_monitor.py` (monitor)

### How to run
```bash
python pipeline/04_monitor.py
```
### Why
After a run you want a single health check: how many records made it through,
where they were lost, and whether anything looks wrong.

### Full script
```python
"""
04_monitor.py — Pipeline monitor / health report.
Reads the per-step logs, computes funnel metrics and yield, raises WARNING/ERROR
flags, and writes logs/pipeline_report.json.
"""

import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CLEAN_LOG = os.path.join(LOG_DIR, "01_clean_log.json")
VALIDATE_LOG = os.path.join(LOG_DIR, "02_validate_log.json")
STORE_LOG = os.path.join(LOG_DIR, "03_store_log.json")
REPORT_PATH = os.path.join(LOG_DIR, "pipeline_report.json")


def load_log(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def pct(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def main():
    clean = load_log(CLEAN_LOG)
    validate = load_log(VALIDATE_LOG)
    store = load_log(STORE_LOG)

    flags = []

    for name, log in (("01_clean", clean), ("02_validate", validate), ("03_store", store)):
        if log is None:
            flags.append({"level": "ERROR", "message": f"Missing log for step {name}"})

    received = clean.get("records_in") if clean else 0
    survived_cleaning = clean.get("records_out") if clean else 0
    passed_validation = validate.get("passed") if validate else 0
    stored = (store.get("inserted", 0) + store.get("updated", 0)) if store else 0
    store_failed = store.get("failed", 0) if store else 0

    overall_yield = pct(stored, received)
    rejection_rate = pct(received - stored, received)
    store_failure_rate = pct(store_failed, stored + store_failed)

    if rejection_rate > 20:
        flags.append({"level": "WARNING", "message": f"Rejection rate {rejection_rate}% exceeds 20% threshold"})
    if store_failure_rate > 5:
        flags.append({"level": "ERROR", "message": f"Store failure rate {store_failure_rate}% exceeds 5% threshold"})

    status = "OK"
    if any(f["level"] == "ERROR" for f in flags):
        status = "ERROR"
    elif any(f["level"] == "WARNING" for f in flags):
        status = "WARNING"

    report = {
        "step": "04_monitor",
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "funnel": {
            "records_received": received,
            "survived_cleaning": survived_cleaning,
            "passed_validation": passed_validation,
            "stored_successfully": stored,
            "store_failed": store_failed,
        },
        "rates": {
            "overall_yield_pct": overall_yield,
            "rejection_rate_pct": rejection_rate,
            "store_failure_rate_pct": store_failure_rate,
        },
        "flags": flags,
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"  PIPELINE HEALTH REPORT          status: {status}")
    print(f"  Records received      : {received}")
    print(f"  Stored successfully   : {stored}  ({overall_yield}%)")
    print(f"  Rejection rate        : {rejection_rate}%")
    for f in flags:
        print(f"   [{f['level']}] {f['message']}")


if __name__ == "__main__":
    main()
```
### What the code does
- `load_log` reads each step's JSON log (returns `None` if missing → an ERROR flag).
- `pct` is a safe percentage (avoids divide-by-zero).
- It builds a **funnel** (received → survived cleaning → passed validation →
  stored) and **rates** (yield, rejection, store-failure), then flags WARNING if
  rejection > 20% or ERROR if store failures > 5%, and writes the report.

### Expected output
```
  PIPELINE HEALTH REPORT          status: WARNING
  Records received      : 7
  Stored successfully   : 5  (71.43%)
  Rejection rate        : 28.57%
   [WARNING] Rejection rate 28.57% exceeds 20% threshold
```
`WARNING` is correct: 2 of 7 records dropped (1 duplicate + 1 invalid). Matters
because it's your at-a-glance data-quality signal.

---

## 9. The API — `api/main.py`

### How to run
```bash
uvicorn api.main:app --reload
# then open http://localhost:8000/docs
```
### Why
The pipeline fills the database; the API lets people/apps **read** it over HTTP,
with an API key controlling access.

### How it works (the important parts)
- **API keys** loaded from `API_KEYS` env (`.env`): first key = `admin`, rest =
  `readonly`. Sent in the `X-API-Key` header. No key → `401`; wrong key → `403`.
- **`authenticate`** (AuthN = who are you) checks the key; **`require_admin`**
  (AuthZ = what may you do) blocks readonly keys from write/delete routes.
- **RateLimiter** caps each key at 60 requests/minute → `429` if exceeded.
- Routes are versioned under `/api/v1/`: list/get/filter users, stats summary,
  active-users summary, create/delete (admin only), pipeline runs (admin only).
- It connects to the **same SQLite file** the store step wrote.

The complete file is `api/main.py`. To run it you use `uvicorn` (the local dev
server). `--reload` restarts it automatically when you edit the code.

### Test it
```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/users                                   # 401 (no key)
curl -H "X-API-Key: dev-key-12345" http://localhost:8000/api/v1/users     # data
```
### Expected result
`/health` works without a key; `/api/v1/users` needs the key; with the admin key
you get the 5 stored users back as JSON.

---

## 10. Run the whole thing, start to finish

```bash
source venv/bin/activate
python pipeline/01_clean.py        # 7 in → 6 out (1 dup removed)
python pipeline/02_validate.py     # 6 in → 5 passed, 1 failed
python pipeline/03_store.py        # 5 inserted into SQLite
python pipeline/04_monitor.py      # health report (WARNING: 28.57% rejection)
uvicorn api.main:app --reload      # serve the data at http://localhost:8000
```
(Or run the skills in order: `/clean` → `/validate` → `/store` → `/monitor`.)

---

## 11. Local vs AWS — same brain, different body

| | **Local (this doc)** | **AWS (AWS-WALKTHROUGH-DETAILED.md)** |
|---|---|---|
| Trigger | you run each script | a file landing in S3 (automatic) |
| Compute | `python` on your laptop | Lambda functions |
| Order kept by | you / CLAUDE.md | Step Functions |
| Step-to-step comms | output files + log files | a JSON payload passed forward |
| Database | SQLite (`db/pipeline.db`) | RDS Postgres |
| API server | `uvicorn` on localhost | API Gateway → Lambda |
| Files | `data/` folders | S3 bucket |

**The cleaning/validation/store/monitor logic is identical in both.** The cloud
version only changed the *edges* — where files live, what runs the code, and
which database it writes to.
```
