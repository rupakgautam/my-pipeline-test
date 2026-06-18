"""
mypipe-clean — Lambda version of pipeline/01_clean.py

Accepts EITHER input shape:
  - Step Functions / manual: {"bucket": "...", "key": "raw/<file>"}
  - Raw S3 event:            {"Records": [{"s3": {...}}]}   (back-compat)

Reads the raw JSON, cleans it, writes cleaned/<file>, and RETURNS an
accumulator dict that the next step (validate) builds on:
    {"bucket","key":"cleaned/<file>","clean":{records_in,duplicates_removed,records_out}}

The cleaning FUNCTIONS are copied verbatim from 01_clean.py.
DEPENDENCIES: standard library + boto3 only.
"""

import json
import boto3
from datetime import datetime
from urllib.parse import unquote_plus

s3 = boto3.client("s3")

SENSOR_KEYS = ("temperature", "humidity", "pressure")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d")
TRUE_VALUES = {"true", "1", "yes", "y", "t"}
FALSE_VALUES = {"false", "0", "no", "n", "f"}


# ── cleaning logic: copied verbatim from pipeline/01_clean.py ──────────────────

def clean_age(value):
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return None
    return age if age > 0 else None


def clean_date(value):
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
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value else []
    return [value]


def clean_is_active(value):
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


# ── input parsing: support both shapes ────────────────────────────────────────

def parse_input(event):
    """Return (bucket, key) whether we got an S3 event or a {bucket,key} payload."""
    if "Records" in event:
        s3rec = event["Records"][0]["s3"]
        return s3rec["bucket"]["name"], unquote_plus(s3rec["object"]["key"])
    return event["bucket"], event["key"]


# ── the Lambda entry point ────────────────────────────────────────────────────

def lambda_handler(event, context):
    bucket, key = parse_input(event)
    print(f"Cleaning s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    raw_records = json.loads(obj["Body"].read())
    records_in = len(raw_records)

    # dedupe by id, keep LAST (same as local)
    deduped = {}
    for record in raw_records:
        deduped[record.get("id")] = record
    duplicates_removed = records_in - len(deduped)

    cleaned_records = [clean_record(r) for r in deduped.values()]

    filename = key.split("/")[-1]
    out_key = f"cleaned/{filename}"
    s3.put_object(
        Bucket=bucket, Key=out_key,
        Body=json.dumps(cleaned_records, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    # Accumulator: carry the pointer forward + record what this step did
    result = {
        "bucket": bucket,
        "key": out_key,                       # next step reads cleaned/<file>
        "clean": {
            "records_in": records_in,
            "duplicates_removed": duplicates_removed,
            "records_out": len(cleaned_records),
        },
    }
    print(f"Done. {result['clean']} -> s3://{bucket}/{out_key}")
    return result
