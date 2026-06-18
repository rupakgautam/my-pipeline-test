"""
03_store.py — Database store step.

Reads data/validated/sample_valid.json and upserts each record into the
SQLite `users` table (insert if the id is new, update if it already exists).
sensor_data is flattened into temperature/humidity/pressure columns, and the
tags list is stored as a comma-separated string.

Results are written to logs/03_store_log.json.
"""

import json
import os
import sys
from datetime import datetime

# Ensure project root is importable and is the CWD (db path in db_models is relative).
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
            except Exception as exc:  # noqa: BLE001
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
    for f in failures:
        print(f"  - {f['id']}: {f['error']}")
    print(f"Database:    {os.path.join(BASE_DIR, 'db', 'pipeline.db')}")
    print(f"Log:         {LOG_PATH}")


if __name__ == "__main__":
    main()
