"""
mypipe-validate — Lambda version of pipeline/02_validate.py

WHAT CHANGED vs the local script:
  - Reads cleaned/<file> from S3 instead of data/cleaned/
  - Writes validated/<file> and invalid/<file> to S3
  - Input is a Step Functions payload: {"bucket": "...", "key": "cleaned/<file>"}
    (this is what the previous step, clean, will hand us)
  - Returns a JSON summary that Step Functions threads to the next step
  - The Record model + validators are copied verbatim from 02_validate.py

DEPENDENCY: pydantic (NOT in the Lambda runtime — must be packaged in the zip).
"""

import json
import boto3
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

s3 = boto3.client("s3")


# ── validation model: copied verbatim from pipeline/02_validate.py ─────────────

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


# ── NEW: the Lambda entry point ───────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Input (from Step Functions / clean step):
        {"bucket": "mypipe-data-rg", "key": "cleaned/sample_raw.json"}
    Reads that cleaned file, splits valid/invalid, writes both to S3,
    and returns a summary for the next step.
    """
    bucket = event["bucket"]
    key = event["key"]            # e.g. cleaned/sample_raw.json
    filename = key.split("/")[-1]  # sample_raw.json

    print(f"Validating s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    records = json.loads(obj["Body"].read())

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

    valid_key = f"validated/{filename}"
    invalid_key = f"invalid/{filename}"

    s3.put_object(
        Bucket=bucket, Key=valid_key,
        Body=json.dumps(valid_records, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=bucket, Key=invalid_key,
        Body=json.dumps(invalid_records, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    # Carry forward everything we received (e.g. clean's counts), then add ours.
    result = dict(event)
    result["bucket"] = bucket
    result["key"] = valid_key      # next step (store) reads the VALID file
    result["invalid_key"] = invalid_key
    result["validate"] = {
        "records_in": len(records),
        "passed": len(valid_records),
        "failed": len(invalid_records),
    }
    print(f"Done. {result['validate']}")
    return result
