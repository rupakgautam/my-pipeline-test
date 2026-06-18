"""
01_clean.py — Data cleaning step.

Reads data/raw/sample_raw.json, fixes structural and type problems, and writes
the cleaned records to data/cleaned/. A change log is written to
logs/01_clean_log.json.

Fixes applied:
  - duplicates       : keep the LAST record per `id`
  - age              : coerced to int (invalid/non-numeric/negative -> None)
  - created          : dates normalized to YYYY-MM-DD
  - salary           : strip "$" and "," -> float
  - tags             : always a list
  - is_active        : always a boolean (or None when unknown)
  - sensor_data      : missing keys (temperature, humidity, pressure) filled with None
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
    # Handle ISO timestamps like 2024-03-10T14:32:00Z
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

    # Deduplicate by id, keeping the LAST occurrence (dict preserves insertion order).
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
