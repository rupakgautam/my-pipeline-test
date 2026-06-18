"""
mypipe-store — Lambda version of pipeline/03_store.py

WHAT CHANGED vs the local script:
  - Target is RDS Postgres instead of SQLite (models/db_models.py).
  - Reads validated/<file> from S3 (the previous step's output).
  - Upsert uses Postgres "INSERT ... ON CONFLICT (id) DO UPDATE", which is
    cleaner than the manual get-or-insert loop in 03_store.py. The
    "RETURNING (xmax = 0)" trick tells us whether each row was inserted (True)
    or updated (False), so we can keep the same inserted/updated counts.
  - Carries the accumulator forward and adds a "store" sub-dict for monitor.

CONNECTION: pg8000 (pure-Python Postgres driver, packaged in the zip).
CONFIG via environment variables:
    DB_HOST, DB_PORT (5432), DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import json
import boto3
import pg8000.dbapi

s3 = boto3.client("s3")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    full_name   TEXT,
    age         INTEGER,
    email       TEXT,
    department  TEXT,
    salary      DOUBLE PRECISION,
    created     TEXT,
    last_login  TEXT,
    is_active   BOOLEAN,
    temperature DOUBLE PRECISION,
    humidity    DOUBLE PRECISION,
    pressure    DOUBLE PRECISION,
    tags        TEXT,
    inserted_at TIMESTAMP DEFAULT now()
);
"""

UPSERT_SQL = """
INSERT INTO users
    (id, full_name, age, email, department, salary, created,
     last_login, is_active, temperature, humidity, pressure, tags)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    full_name   = EXCLUDED.full_name,
    age         = EXCLUDED.age,
    email       = EXCLUDED.email,
    department  = EXCLUDED.department,
    salary      = EXCLUDED.salary,
    created     = EXCLUDED.created,
    last_login  = EXCLUDED.last_login,
    is_active   = EXCLUDED.is_active,
    temperature = EXCLUDED.temperature,
    humidity    = EXCLUDED.humidity,
    pressure    = EXCLUDED.pressure,
    tags        = EXCLUDED.tags
RETURNING (xmax = 0) AS inserted;
"""


def to_row(record):
    """Map a validated record onto the users columns (same as 03_store.to_columns)."""
    sensor = record.get("sensor_data") or {}
    tags = record.get("tags") or []
    tags_str = ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
    return (
        record.get("id"),
        record.get("full_name"),
        record.get("age"),
        record.get("email"),
        record.get("department"),
        record.get("salary"),
        record.get("created"),
        record.get("last_login"),
        record.get("is_active"),
        sensor.get("temperature"),
        sensor.get("humidity"),
        sensor.get("pressure"),
        tags_str,
    )


def connect():
    return pg8000.dbapi.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def lambda_handler(event, context):
    bucket = event["bucket"]
    key = event["key"]            # validated/<file>
    print(f"Storing s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    records = json.loads(obj["Body"].read())

    inserted, updated, failed = 0, 0, 0
    failures = []

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)       # idempotent: like init_db()
        conn.commit()

        for record in records:
            try:
                cur.execute(UPSERT_SQL, to_row(record))
                was_inserted = cur.fetchone()[0]
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
                conn.commit()
            except Exception as exc:        # noqa: BLE001
                conn.rollback()
                failed += 1
                failures.append({"id": record.get("id"), "error": str(exc)})
    finally:
        conn.close()

    result = dict(event)
    result["store"] = {
        "records_in": len(records),
        "inserted": inserted,
        "updated": updated,
        "failed": failed,
        "failures": failures,
    }
    print(f"Done. {result['store']}")
    return result
