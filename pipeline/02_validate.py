"""
02_validate.py — Data validation step.

Reads the cleaned records, validates each against a Pydantic v2 model, and
splits them into valid / invalid output files. A summary is written to
logs/02_validate_log.json.

Validation rules:
  - id          : required
  - full_name   : required, not null
  - age         : 0-120 if present
  - email       : must contain "@"
  - salary      : positive if present
  - created     : valid YYYY-MM-DD if present
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
    print(f"Valid   -> {VALID_PATH}")
    print(f"Invalid -> {INVALID_PATH}")
    print(f"Log     -> {LOG_PATH}")


if __name__ == "__main__":
    main()
