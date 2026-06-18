# AWS Migration — FULL Detailed Walkthrough (nothing skipped)

Every script, every command, every config file we used to move the local
pipeline onto AWS — with plain-English explanations and expected results.

---

## 0. The end-to-end flow (read this first)

```
 ┌─────────┐   upload .json    ┌────────────┐   "Object Created"   ┌──────────────┐
 │  client │ ────────────────► │  S3  raw/  │ ───────────────────► │ EventBridge  │
 └─────────┘                   └────────────┘                      └──────┬───────┘
                                                                          │ starts
                                                                          ▼
                                            ┌───────────────────────────────────────────┐
                                            │  Step Functions state machine               │
                                            │  Clean ─► Validate ─► Store ─► Monitor       │
                                            └───┬───────┬───────────┬──────────┬──────────┘
                                                ▼       ▼           ▼          ▼
                                          S3 cleaned/ S3 validated/ RDS users  S3 reports/
                                                                  (Postgres)
                                                                     ▲
   ┌──────────┐   HTTPS + X-API-Key    ┌──────────────┐   reads     │
   │ internet │ ─────────────────────► │ API Gateway  │ ─► Lambda ──┘
   └──────────┘                        └──────────────┘   (FastAPI)
```

**How each step connects to the next:**
1. A file lands in `s3://mypipe-data-rg/raw/`.
2. S3 emits an event; EventBridge matches it and **starts the state machine**.
3. The state machine runs four Lambdas in order. Each one reads the previous
   step's S3 output (or, for Monitor, the running totals), and passes a JSON
   payload forward.
4. `Store` writes rows into the RDS Postgres database.
5. Separately, anyone on the internet can call the API Gateway URL; it forwards
   to a FastAPI Lambda that reads the same database, guarded by an API key.

---

## 1. Naming + shared variables

Every command reused these shell variables:

```bash
export BUCKET=mypipe-data-rg
export REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```
- `BUCKET` — our S3 bucket name (globally unique; `-rg` = your initials).
- `REGION` — the AWS data-center region we deploy to.
- `ACCOUNT_ID` — your 12-digit AWS account number (`905204392314`), needed in ARNs.

An **ARN** ("Amazon Resource Name") is the full unique address of any AWS thing,
e.g. `arn:aws:lambda:us-east-1:905204392314:function:mypipe-clean`.

---

## 2. Phase 1 — S3 landing zone

### Commands
```bash
aws s3 mb s3://mypipe-data-rg --region us-east-1

aws s3api put-public-access-block --bucket mypipe-data-rg \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-object --bucket mypipe-data-rg --key raw/
aws s3api put-object --bucket mypipe-data-rg --key cleaned/
aws s3api put-object --bucket mypipe-data-rg --key validated/
aws s3api put-object --bucket mypipe-data-rg --key invalid/

aws s3 cp data/raw/sample_raw.json s3://mypipe-data-rg/raw/
aws s3 ls s3://mypipe-data-rg/
```
### What each does
- `s3 mb` — **m**ake **b**ucket. (In `us-east-1` you must NOT pass a location constraint; every other region requires one.)
- `put-public-access-block` — turns on all four "block public access" switches so the bucket can never be accidentally exposed.
- `put-object --key raw/` — writes an empty object whose name ends in `/`, so the "folder" shows up in the console.
- `s3 cp` — uploads a local file.
- `s3 ls` — lists bucket contents.

### Why
S3 is the durable cloud home for files, and a new file in `raw/` is the trigger
for the whole pipeline. Kept private; auth is enforced later at the API.

### Expected result
`s3 ls` shows `PRE cleaned/`, `PRE invalid/`, `PRE raw/`, `PRE validated/`, and
`raw/sample_raw.json`. This matters because the folder layout now mirrors the
local `data/` directory, so the pipeline logic ports over unchanged.

---

## 3. Phase 2 — the `clean` Lambda

### 3a. The IAM trust policy (shared by all Lambdas)
File `aws/iam/lambda-trust-policy.json` — "who is allowed to BECOME this role":
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```
Plain English: only the **Lambda service** may assume (run as) this role.

### 3b. The clean S3 permission policy
File `aws/iam/clean-s3-policy.json` — least-privilege: read `raw/`, write `cleaned/`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ReadRaw",      "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::mypipe-data-rg/raw/*" },
    { "Sid": "WriteCleaned", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::mypipe-data-rg/cleaned/*" }
  ]
}
```

### 3c. The full clean Lambda script
File `aws/lambdas/clean/lambda_function.py`:
```python
import json
import boto3
from datetime import datetime
from urllib.parse import unquote_plus

s3 = boto3.client("s3")

SENSOR_KEYS = ("temperature", "humidity", "pressure")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d")
TRUE_VALUES = {"true", "1", "yes", "y", "t"}
FALSE_VALUES = {"false", "0", "no", "n", "f"}


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


def parse_input(event):
    """Return (bucket, key) whether we got an S3 event or a {bucket,key} payload."""
    if "Records" in event:
        s3rec = event["Records"][0]["s3"]
        return s3rec["bucket"]["name"], unquote_plus(s3rec["object"]["key"])
    return event["bucket"], event["key"]


def lambda_handler(event, context):
    bucket, key = parse_input(event)
    print(f"Cleaning s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    raw_records = json.loads(obj["Body"].read())
    records_in = len(raw_records)

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

    result = {
        "bucket": bucket,
        "key": out_key,
        "clean": {
            "records_in": records_in,
            "duplicates_removed": duplicates_removed,
            "records_out": len(cleaned_records),
        },
    }
    print(f"Done. {result['clean']} -> s3://{bucket}/{out_key}")
    return result
```
**What it does in simple terms:** `boto3` is the AWS SDK. `parse_input` figures
out the bucket+key whether triggered by S3 directly or by Step Functions.
`s3.get_object` downloads the raw JSON, the cleaning functions fix it (dedupe,
type-coerce, normalize dates), `s3.put_object` uploads the result to `cleaned/`,
and it **returns a dict** carrying the counts forward to the next step.

### 3d. Commands to deploy it
```bash
export FN=mypipe-clean
export ROLE_NAME=mypipe-clean-role

aws iam create-role --role-name $ROLE_NAME \
  --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name $ROLE_NAME \
  --policy-name mypipe-clean-s3 --policy-document file://aws/iam/clean-s3-policy.json
export ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query Role.Arn --output text)

zip -j /tmp/mypipe-clean.zip aws/lambdas/clean/lambda_function.py
aws lambda create-function --function-name $FN \
  --runtime python3.12 --role $ROLE_ARN \
  --handler lambda_function.lambda_handler \
  --timeout 30 --memory-size 256 \
  --zip-file fileb:///tmp/mypipe-clean.zip --region $REGION
```
- `create-role` — make the identity, attaching the trust policy.
- `attach-role-policy` (AWSLambdaBasicExecutionRole) — AWS-managed permission to write CloudWatch logs.
- `put-role-policy` — inline our custom S3 rule.
- `get-role --query Role.Arn` — read the role's ARN into a variable.
- `zip -j` — bundle the code (`-j` = drop the folder path so the file sits at the zip root, where Lambda looks).
- `create-function` — upload + register; `--handler lambda_function.lambda_handler` means "file `lambda_function.py`, function `lambda_handler`."

### 3e. Wiring the S3 trigger
```bash
aws lambda add-permission --function-name $FN --statement-id s3invoke \
  --action lambda:InvokeFunction --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::$BUCKET --source-account $ACCOUNT_ID --region $REGION

export FN_ARN=$(aws lambda get-function --function-name $FN \
  --query Configuration.FunctionArn --output text --region $REGION)
```
Notification config (later replaced by EventBridge):
```json
{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "<clean-arn>",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": { "Key": { "FilterRules": [
        { "Name": "prefix", "Value": "raw/" },
        { "Name": "suffix", "Value": ".json" }
      ] } }
    }
  ]
}
```
```bash
aws s3api put-bucket-notification-configuration --bucket $BUCKET \
  --notification-configuration file:///tmp/notif.json
```
- `add-permission` — lets the S3 service call the Lambda (must happen BEFORE the notification, or it errors).
- `put-bucket-notification-configuration` — "run the Lambda when a `.json` lands in `raw/`." The `raw/` prefix is critical: the Lambda writes to `cleaned/`, and without the filter that write would re-trigger the Lambda forever.

### Expected result
Uploading `raw/sample_raw.json` auto-created `cleaned/sample_raw.json`.
CloudWatch logs showed `in=7 dupes_removed=1 out=6`. It matters because it proves
event-driven execution works: a file caused code to run with no human.

### Reading logs (you're on AWS CLI v1)
```bash
aws logs filter-log-events --log-group-name /aws/lambda/$FN \
  --limit 20 --query 'events[*].message' --output text --region $REGION
```
(`aws logs tail` is v2-only and errored on your v1 CLI.)

---

## 4. Phase 3.1 — the `validate` Lambda (with a dependency)

### Permission policy
File `aws/iam/validate-s3-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ReadCleaned", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::mypipe-data-rg/cleaned/*" },
    { "Sid": "WriteValidatedAndInvalid", "Effect": "Allow", "Action": "s3:PutObject",
      "Resource": [ "arn:aws:s3:::mypipe-data-rg/validated/*", "arn:aws:s3:::mypipe-data-rg/invalid/*" ] }
  ]
}
```

### The full validate Lambda script
File `aws/lambdas/validate/lambda_function.py`:
```python
import json
import boto3
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

s3 = boto3.client("s3")


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


def lambda_handler(event, context):
    bucket = event["bucket"]
    key = event["key"]
    filename = key.split("/")[-1]

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

    s3.put_object(Bucket=bucket, Key=valid_key,
                  Body=json.dumps(valid_records, indent=2).encode("utf-8"),
                  ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=invalid_key,
                  Body=json.dumps(invalid_records, indent=2).encode("utf-8"),
                  ContentType="application/json")

    result = dict(event)
    result["bucket"] = bucket
    result["key"] = valid_key
    result["invalid_key"] = invalid_key
    result["validate"] = {
        "records_in": len(records),
        "passed": len(valid_records),
        "failed": len(invalid_records),
    }
    print(f"Done. {result['validate']}")
    return result
```
**What it does:** validates each record against the same pydantic `Record` model
from the local pipeline, writes passers to `validated/` and failures (with
reasons) to `invalid/`, and **copies the incoming payload forward** (`dict(event)`)
so the clean counts survive — then adds its own `validate` block.

### Packaging a dependency (the new skill)
```bash
rm -rf /tmp/validate-build && mkdir -p /tmp/validate-build
pip install pydantic -t /tmp/validate-build \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.12 --only-binary=:all:
cp aws/lambdas/validate/lambda_function.py /tmp/validate-build/
( cd /tmp/validate-build && zip -rq /tmp/mypipe-validate.zip . )
```
- `pip install -t <dir>` — install INTO a folder (not the system).
- `--platform manylinux2014_x86_64` — fetch the **Linux** build (Lambda is Linux), not your Mac's. pydantic ships a compiled core, so the OS must match.
- `--only-binary=:all:` — use prebuilt wheels, never compile locally.
- `zip -rq` — recursively zip the whole folder (deps + handler) quietly.

### Deploy + test
```bash
export VFN=mypipe-validate
export VROLE=mypipe-validate-role
aws iam create-role --role-name $VROLE --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name $VROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name $VROLE --policy-name mypipe-validate-s3 --policy-document file://aws/iam/validate-s3-policy.json
export VROLE_ARN=$(aws iam get-role --role-name $VROLE --query Role.Arn --output text)

aws lambda create-function --function-name $VFN --runtime python3.12 --role $VROLE_ARN \
  --handler lambda_function.lambda_handler --timeout 30 --memory-size 256 \
  --zip-file fileb:///tmp/mypipe-validate.zip --region $REGION

echo '{"bucket":"mypipe-data-rg","key":"cleaned/sample_raw.json"}' > /tmp/payload.json
aws lambda invoke --function-name $VFN --payload file:///tmp/payload.json --region $REGION /tmp/validate-out.json
cat /tmp/validate-out.json
```
- `lambda invoke` — run the function now with a test payload. (On CLI v1 the payload is passed raw; on v2 you'd add `--cli-binary-format raw-in-base64-out`.)

### Expected result
`{"...,"key":"validated/sample_raw.json","records_in":6,"passed":5,"failed":1}`
plus files in `validated/` and `invalid/`. Matters because it proves a Lambda
with a compiled dependency runs correctly.

---

## 5. Phase 3.2 — the `monitor` Lambda

### Permission policy
File `aws/iam/monitor-s3-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "WriteReports", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::mypipe-data-rg/reports/*" }
  ]
}
```

### The full monitor Lambda script
File `aws/lambdas/monitor/lambda_function.py`:
```python
import json
import boto3
from datetime import datetime

s3 = boto3.client("s3")


def pct(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def lambda_handler(event, context):
    clean = event.get("clean", {})
    validate = event.get("validate", {})
    store = event.get("store", {})

    flags = []
    if not clean:
        flags.append({"level": "ERROR", "message": "Missing results for step clean"})
    if not validate:
        flags.append({"level": "ERROR", "message": "Missing results for step validate"})

    received = clean.get("records_in", 0)
    survived_cleaning = clean.get("records_out", 0)
    passed_validation = validate.get("passed", 0)
    stored = store.get("inserted", 0) + store.get("updated", 0)
    store_failed = store.get("failed", 0)

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
        "timestamp": datetime.utcnow().isoformat(),
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

    bucket = event.get("bucket")
    if bucket:
        key = event.get("key", "unknown.json")
        filename = key.split("/")[-1]
        report_key = f"reports/{filename}"
        s3.put_object(Bucket=bucket, Key=report_key,
                      Body=json.dumps(report, indent=2).encode("utf-8"),
                      ContentType="application/json")
        report["report_key"] = report_key
        print(f"Report -> s3://{bucket}/{report_key}")

    print(f"STATUS={status} funnel={report['funnel']} flags={flags}")
    return report
```
**What it does:** reads the accumulated `clean`/`validate`/`store` counts out of
the payload (no log files needed), computes the funnel + rates, raises WARNING/
ERROR flags on the same thresholds as local, writes the report to `reports/`,
and returns it.

### Deploy
```bash
export MFN=mypipe-monitor
export MROLE=mypipe-monitor-role
aws iam create-role --role-name $MROLE --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name $MROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name $MROLE --policy-name mypipe-monitor-s3 --policy-document file://aws/iam/monitor-s3-policy.json
export MROLE_ARN=$(aws iam get-role --role-name $MROLE --query Role.Arn --output text)

zip -j /tmp/mypipe-monitor.zip aws/lambdas/monitor/lambda_function.py
aws lambda create-function --function-name $MFN --runtime python3.12 --role $MROLE_ARN \
  --handler lambda_function.lambda_handler --timeout 30 --memory-size 256 \
  --zip-file fileb:///tmp/mypipe-monitor.zip --region $REGION
```

### Redeploy clean + validate (we changed them to accumulate)
```bash
zip -j /tmp/mypipe-clean.zip aws/lambdas/clean/lambda_function.py
aws lambda update-function-code --function-name $FN --zip-file fileb:///tmp/mypipe-clean.zip --region $REGION

cp aws/lambdas/validate/lambda_function.py /tmp/validate-build/
( cd /tmp/validate-build && zip -rq /tmp/mypipe-validate.zip . )
aws lambda update-function-code --function-name $VFN --zip-file fileb:///tmp/mypipe-validate.zip --region $REGION
```
- `update-function-code` — replace a function's code without recreating it.

### Manual chain test
```bash
echo '{"bucket":"mypipe-data-rg","key":"raw/sample_raw.json"}' > /tmp/p.json
aws lambda invoke --function-name $FN  --payload file:///tmp/p.json  --region $REGION /tmp/o1.json
aws lambda invoke --function-name $VFN --payload file:///tmp/o1.json --region $REGION /tmp/o2.json
aws lambda invoke --function-name $MFN --payload file:///tmp/o2.json --region $REGION /tmp/o3.json
cat /tmp/o3.json
```
### Expected result
`/tmp/o3.json` reports `received 7 → survived 6 → passed 5` with a WARNING. This
proves the accumulator pattern works — feeding one step's output into the next
threads the data all the way to monitor.

---

## 6. Phase 3.3 — Step Functions + EventBridge

### Step Functions trust policy
File `aws/iam/sfn-trust-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": { "Service": "states.amazonaws.com" }, "Action": "sts:AssumeRole" }
  ]
}
```

### Step Functions invoke policy (built with a heredoc because it needs ARNs)
```bash
cat > /tmp/sfn-invoke-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "lambda:InvokeFunction",
      "Resource": ["$FN_ARN", "$VFN_ARN", "$STFN_ARN", "$MFN_ARN"] }
  ]
}
EOF
```

### The state machine definition (final, with Store)
```json
{
  "Comment": "mypipe data pipeline: clean -> validate -> store -> monitor",
  "StartAt": "Clean",
  "States": {
    "Clean":    { "Type": "Task", "Resource": "<clean-arn>",    "Retry": [ {"ErrorEquals":["Lambda.ServiceException","Lambda.TooManyRequestsException","Lambda.AWSLambdaException"],"IntervalSeconds":2,"MaxAttempts":3,"BackoffRate":2} ], "Next": "Validate" },
    "Validate": { "Type": "Task", "Resource": "<validate-arn>", "Retry": [ {"ErrorEquals":["Lambda.ServiceException","Lambda.TooManyRequestsException","Lambda.AWSLambdaException"],"IntervalSeconds":2,"MaxAttempts":3,"BackoffRate":2} ], "Next": "Store" },
    "Store":    { "Type": "Task", "Resource": "<store-arn>",    "Retry": [ {"ErrorEquals":["Lambda.ServiceException","Lambda.TooManyRequestsException","Lambda.AWSLambdaException"],"IntervalSeconds":2,"MaxAttempts":3,"BackoffRate":2} ], "Next": "Monitor" },
    "Monitor":  { "Type": "Task", "Resource": "<monitor-arn>",  "Retry": [ {"ErrorEquals":["Lambda.ServiceException","Lambda.TooManyRequestsException","Lambda.AWSLambdaException"],"IntervalSeconds":2,"MaxAttempts":3,"BackoffRate":2} ], "End": true }
  }
}
```
**What it means:** a flowchart in Amazon States Language. `StartAt` → run Clean →
`Next` Validate → Store → Monitor → `End`. With the plain-ARN `Resource` form,
each step receives the previous step's return value as its input. `Retry` retries
a step up to 3× with growing delays if it hits a transient AWS error.

### Create + run
```bash
export SFNROLE=mypipe-sfn-role
aws iam create-role --role-name $SFNROLE --assume-role-policy-document file://aws/iam/sfn-trust-policy.json
aws iam put-role-policy --role-name $SFNROLE --policy-name mypipe-sfn-invoke --policy-document file:///tmp/sfn-invoke-policy.json
export SFNROLE_ARN=$(aws iam get-role --role-name $SFNROLE --query Role.Arn --output text)

aws stepfunctions create-state-machine --name mypipe-pipeline \
  --definition file:///tmp/mypipe-statemachine.json --role-arn $SFNROLE_ARN --region $REGION

export SM_ARN=$(aws stepfunctions list-state-machines \
  --query "stateMachines[?name=='mypipe-pipeline'].stateMachineArn" --output text --region $REGION)

aws stepfunctions start-execution --state-machine-arn $SM_ARN \
  --input '{"bucket":"mypipe-data-rg","key":"raw/sample_raw.json"}' --region $REGION
```
- `create-state-machine` — register the flowchart, giving it the role that may invoke the Lambdas.
- `start-execution` — run the whole pipeline once.

### EventBridge — auto-start on upload
```bash
cat > /tmp/notif-eb.json <<EOF
{ "EventBridgeConfiguration": {} }
EOF
aws s3api put-bucket-notification-configuration --bucket $BUCKET --notification-configuration file:///tmp/notif-eb.json
```
EventBridge role (trust + permission):
```bash
cat > /tmp/eb-trust.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"events.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
cat > /tmp/eb-sfn-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"states:StartExecution","Resource":"$SM_ARN"}]}
EOF
export EBROLE=mypipe-eventbridge-role
aws iam create-role --role-name $EBROLE --assume-role-policy-document file:///tmp/eb-trust.json
aws iam put-role-policy --role-name $EBROLE --policy-name mypipe-eb-startexec --policy-document file:///tmp/eb-sfn-policy.json
export EBROLE_ARN=$(aws iam get-role --role-name $EBROLE --query Role.Arn --output text)
```
The rule (event pattern):
```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": { "bucket": { "name": ["mypipe-data-rg"] }, "object": { "key": [ { "prefix": "raw/" } ] } }
}
```
The target (with input transformer):
```json
[
  {
    "Id": "mypipe-sfn",
    "Arn": "<state-machine-arn>",
    "RoleArn": "<eventbridge-role-arn>",
    "InputTransformer": {
      "InputPathsMap": { "bucket": "$.detail.bucket.name", "key": "$.detail.object.key" },
      "InputTemplate": "{\"bucket\": <bucket>, \"key\": <key>}"
    }
  }
]
```
```bash
aws events put-rule --name mypipe-raw-upload --event-pattern file:///tmp/eb-pattern.json --region $REGION
aws events put-targets --rule mypipe-raw-upload --targets file:///tmp/eb-targets.json --region $REGION
```
- `put-bucket-notification-configuration {EventBridgeConfiguration:{}}` — tell S3 to publish events to EventBridge (and this overwrite removed the old direct-to-Lambda trigger).
- `put-rule` — "match new `.json` under `raw/`."
- `put-targets` — "when matched, start the state machine," reshaping the S3 event into `{bucket, key}` via the input transformer.

### Expected result
Uploading a file produced a `SUCCEEDED` execution you never started by hand —
full automation: upload → EventBridge → Step Functions → all four steps.

---

## 7. Phase 4 — RDS Postgres + VPC + the `store` step

### The networking (custom "presales" VPC, private subnets)
```bash
export VPC_ID=vpc-0c6e4e2b92412cdfe
export PRIVATE_SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*private*" \
  --query 'Subnets[*].SubnetId' --output text --region $REGION | tr '\t' ' ')

export RDS_SG=$(aws ec2 create-security-group --group-name mypipe-rds-sg \
  --description "RDS Postgres - allow 5432 from Lambda only" --vpc-id $VPC_ID \
  --query GroupId --output text --region $REGION)
export LAMBDA_SG=$(aws ec2 create-security-group --group-name mypipe-lambda-sg \
  --description "store Lambda" --vpc-id $VPC_ID --query GroupId --output text --region $REGION)

aws ec2 authorize-security-group-ingress --group-id $RDS_SG \
  --protocol tcp --port 5432 --source-group $LAMBDA_SG --region $REGION
```
- `describe-subnets ... | tr '\t' ' '` — fetch the private subnet IDs; convert tabs to spaces (so zsh can split them with `${=VAR}`).
- `create-security-group` — make a firewall (×2: one for the DB, one for the Lambda).
- `authorize-security-group-ingress` — "only the Lambda's group may reach the DB on port 5432." This single rule is what keeps the database private.

### The database
```bash
export DB_PASSWORD='ChangeMe-Strong123!'   # your own
export DB_USER=pipelineadmin
export DB_NAME=pipeline

aws rds create-db-subnet-group --db-subnet-group-name mypipe-db-subnets \
  --db-subnet-group-description "mypipe private subnets" \
  --subnet-ids ${=PRIVATE_SUBNETS} --region $REGION

aws rds create-db-instance --db-instance-identifier mypipe-pg \
  --db-instance-class db.t3.micro --engine postgres \
  --master-username $DB_USER --master-user-password "$DB_PASSWORD" \
  --allocated-storage 20 --db-name $DB_NAME \
  --db-subnet-group-name mypipe-db-subnets --vpc-security-group-ids $RDS_SG \
  --no-publicly-accessible --backup-retention-period 0 --region $REGION
```
- `create-db-subnet-group` — tell RDS which network slices it may live in (custom VPCs have no default group). `${=PRIVATE_SUBNETS}` = zsh "split this into separate arguments."
- `create-db-instance` — build the Postgres server. `db.t3.micro` + `20 GB` = free-tier; `--no-publicly-accessible` = private; `--backup-retention-period 0` = no snapshots (cheaper, easy teardown).

Wait for it, then read the endpoint:
```bash
aws rds describe-db-instances --db-instance-identifier mypipe-pg \
  --query 'DBInstances[0].DBInstanceStatus' --output text --region $REGION   # wait for "available"
export DB_HOST=$(aws rds describe-db-instances --db-instance-identifier mypipe-pg \
  --query 'DBInstances[0].Endpoint.Address' --output text --region $REGION)
```
(The S3 Gateway VPC endpoint already existed in this VPC and covered the private
subnets' route tables, so the in-VPC Lambda can read S3 with no extra setup.)

### Store permission policy
File `aws/iam/store-s3-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ReadValidated", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::mypipe-data-rg/validated/*" }
  ]
}
```

### The full store Lambda script
File `aws/lambdas/store/lambda_function.py`:
```python
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
    sensor = record.get("sensor_data") or {}
    tags = record.get("tags") or []
    tags_str = ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
    return (
        record.get("id"), record.get("full_name"), record.get("age"),
        record.get("email"), record.get("department"), record.get("salary"),
        record.get("created"), record.get("last_login"), record.get("is_active"),
        sensor.get("temperature"), sensor.get("humidity"), sensor.get("pressure"),
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
    key = event["key"]
    print(f"Storing s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    records = json.loads(obj["Body"].read())

    inserted, updated, failed = 0, 0, 0
    failures = []

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
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
            except Exception as exc:
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
```
**What it does:** connects to Postgres with `pg8000`, creates the `users` table
if missing, and upserts each record. `INSERT ... ON CONFLICT (id) DO UPDATE` =
"insert, but if the id already exists, update instead." `RETURNING (xmax = 0)`
is a Postgres trick that returns `True` when the row was freshly inserted, so we
can count inserts vs updates.

### Package + deploy (in the VPC)
```bash
rm -rf /tmp/store-build && mkdir -p /tmp/store-build
pip install pg8000 -t /tmp/store-build          # pure-Python, so no --platform needed
cp aws/lambdas/store/lambda_function.py /tmp/store-build/
( cd /tmp/store-build && zip -rq /tmp/mypipe-store.zip . )

export STFN=mypipe-store
export SROLE=mypipe-store-role
aws iam create-role --role-name $SROLE --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name $SROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole
aws iam put-role-policy --role-name $SROLE --policy-name mypipe-store-s3 --policy-document file://aws/iam/store-s3-policy.json
export SROLE_ARN=$(aws iam get-role --role-name $SROLE --query Role.Arn --output text)

aws lambda create-function --function-name $STFN --runtime python3.12 --role $SROLE_ARN \
  --handler lambda_function.lambda_handler --timeout 60 --memory-size 256 \
  --zip-file fileb:///tmp/mypipe-store.zip \
  --vpc-config "SubnetIds=${PRIVATE_SUBNETS// /,},SecurityGroupIds=$LAMBDA_SG" \
  --environment "Variables={DB_HOST=$DB_HOST,DB_PORT=5432,DB_NAME=$DB_NAME,DB_USER=$DB_USER,DB_PASSWORD=$DB_PASSWORD}" \
  --region $REGION
```
- `AWSLambdaVPCAccessExecutionRole` — managed permission that lets the Lambda attach a network interface to the VPC (plus logs). This replaces the basic execution role.
- `--vpc-config` — place the Lambda in the private subnets with the Lambda SG. `${PRIVATE_SUBNETS// /,}` = zsh "replace spaces with commas" (the flag wants a comma list).
- `--environment` — the DB connection details the code reads via `os.environ`.

### Test (wait for Active first — VPC Lambdas start Pending)
```bash
echo '{"bucket":"mypipe-data-rg","key":"validated/sample_raw.json"}' > /tmp/store-test.json
aws lambda invoke --function-name $STFN --payload file:///tmp/store-test.json --region $REGION /tmp/store-out.json
cat /tmp/store-out.json
```
### Expected result
`"store": {"records_in":5,"inserted":5,"updated":0,"failed":0}`. Running it again
flips to `updated:5`, proving the upsert. This is the moment data first lands in
a real database.

### Add Store to the state machine
```bash
export STFN_ARN=$(aws lambda get-function --function-name mypipe-store --query Configuration.FunctionArn --output text --region $REGION)
# rebuild /tmp/sfn-invoke-policy.json to include $STFN_ARN, then:
aws iam put-role-policy --role-name mypipe-sfn-role --policy-name mypipe-sfn-invoke --policy-document file:///tmp/sfn-invoke-policy.json
# rebuild /tmp/mypipe-statemachine.json with the Store state, then:
aws stepfunctions update-state-machine --state-machine-arn $SM_ARN --definition file:///tmp/mypipe-statemachine.json --region $REGION
```
- `update-state-machine` — replace the flowchart with the new one that includes Store.

### Full pipeline result
After uploading, the execution output showed `received 7 → cleaned 6 → validated
5 → stored 5`, `store_failure_rate 0%`, status `WARNING` (28.57% rejection — two
records legitimately dropped). The whole pipeline now runs automatically and
lands data in Postgres.

---

## 8. Phase 6 — FastAPI on Lambda + API Gateway

### The Postgres DB models
File `aws/lambdas/api/db_models.py`:
```python
import os
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean, DateTime, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = (
    f"postgresql+pg8000://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}"
    f"/{os.environ['DB_NAME']}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
```
**What changed vs local:** only the connection string — `postgresql+pg8000://...`
built from environment variables, instead of a SQLite file. The ORM models are
identical. `pool_pre_ping=True` quietly drops dead connections when Lambda reuses
a container.

### The API itself
`aws/lambdas/api/main.py` is your **original `api/main.py`** with exactly two
changes:
1. The import line became `from db_models import ...` (the file sits beside it).
2. These three lines were appended so it runs on Lambda:
```python
# ── LAMBDA ADAPTER ────────────────────────────────────────────────────────────
from mangum import Mangum
handler = Mangum(app)
```
Everything else — the API-key auth, admin/readonly roles, rate limiting, all the
`/api/v1/...` routes — is unchanged. (The complete file lives at
`aws/lambdas/api/main.py`.) **Mangum** is a small adapter that translates between
API Gateway's event format and the ASGI format FastAPI speaks, so the same `app`
object runs unmodified on Lambda.

### Package + deploy (in the VPC, with DB creds + API keys)
```bash
rm -rf /tmp/api-build && mkdir -p /tmp/api-build
pip install fastapi mangum sqlalchemy pg8000 -t /tmp/api-build \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:
cp aws/lambdas/api/main.py aws/lambdas/api/db_models.py /tmp/api-build/
( cd /tmp/api-build && zip -rq /tmp/mypipe-api.zip . )

export AFN=mypipe-api
export AROLE=mypipe-api-role
aws iam create-role --role-name $AROLE --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name $AROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole
export AROLE_ARN=$(aws iam get-role --role-name $AROLE --query Role.Arn --output text)

cat > /tmp/api-env.json <<EOF
{ "Variables": {
    "DB_HOST": "$DB_HOST", "DB_PORT": "5432", "DB_NAME": "$DB_NAME",
    "DB_USER": "$DB_USER", "DB_PASSWORD": "$DB_PASSWORD",
    "API_KEYS": "dev-key-12345,readonly-key-99999"
} }
EOF

aws lambda create-function --function-name $AFN --runtime python3.12 --role $AROLE_ARN \
  --handler main.handler --timeout 30 --memory-size 512 \
  --zip-file fileb:///tmp/mypipe-api.zip \
  --vpc-config "SubnetIds=${PRIVATE_SUBNETS// /,},SecurityGroupIds=$LAMBDA_SG" \
  --environment file:///tmp/api-env.json --region $REGION
```
- `--handler main.handler` — points at the `handler = Mangum(app)` we added.
- Same VPC config as store (to reach RDS); the Lambda SG is already allowed by the DB SG.
- `API_KEYS` env var = the same keys as your local `.env`, so auth behaves identically.

### Put API Gateway in front
```bash
export AFN_ARN=$(aws lambda get-function --function-name $AFN --query Configuration.FunctionArn --output text --region $REGION)

export API_ID=$(aws apigatewayv2 create-api --name mypipe-http-api --protocol-type HTTP --query ApiId --output text --region $REGION)
export INTEG_ID=$(aws apigatewayv2 create-integration --api-id $API_ID --integration-type AWS_PROXY \
  --integration-uri $AFN_ARN --payload-format-version 2.0 --query IntegrationId --output text --region $REGION)
aws apigatewayv2 create-route --api-id $API_ID --route-key '$default' --target "integrations/$INTEG_ID" --region $REGION
aws apigatewayv2 create-stage --api-id $API_ID --stage-name '$default' --auto-deploy --region $REGION
aws lambda add-permission --function-name $AFN --statement-id apigw-invoke \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT_ID:$API_ID/*" --region $REGION

export API_URL=$(aws apigatewayv2 get-api --api-id $API_ID --query ApiEndpoint --output text --region $REGION)
echo "$API_URL"
```
- `create-api` — make a public HTTPS endpoint (HTTP API = the simplest, cheapest type).
- `create-integration` (AWS_PROXY, format 2.0) — forward the whole request to the Lambda in the event shape Mangum expects.
- `create-route '$default'` — send every path/method to that integration (FastAPI routes internally).
- `create-stage --auto-deploy` — publish at the URL root, deploying changes instantly.
- `add-permission` — let API Gateway invoke the Lambda.
- `get-api --query ApiEndpoint` — read the public URL.

### Test over HTTPS
```bash
curl -s $API_URL/health
curl -s $API_URL/api/v1/users
curl -s -H "X-API-Key: dev-key-12345" "$API_URL/api/v1/users/stats/summary"
echo "$API_URL/docs"
```
### Expected result
- `/health` → `200` `{"status":"ok",...}`
- `/api/v1/users` (no key) → `401` `"No API key provided..."`
- with admin key → live stats from Postgres
- `/docs` → full interactive Swagger UI

This matters because it proves the same app, the same auth, now runs serverless
against the cloud database and is reachable by anyone with the URL and a key.

---

## 9. Gotchas we hit (and the fix for each)

| Problem | Cause | Fix |
|---|---|---|
| `aws logs tail` invalid | You're on **CLI v1** | use `aws logs filter-log-events`, or upgrade to v2 |
| `--cli-binary-format` unknown | v2-only flag | drop it on v1 |
| ARN had `...314ole/...` | zsh read `$ACCT:role` `:r` as a modifier | use `${ACCT}` or fetch ARN from AWS |
| `if>` prompt / `command not found: #` | zsh doesn't treat `#` as comment | `setopt interactive_comments` |
| subnet group "control characters" | zsh doesn't word-split `$VAR` | use `${=VAR}` |
| "Some input subnets are invalid" | hand-typed IDs from a screenshot | fetch IDs from the API |
| Invoke "function is Pending" | VPC Lambda still attaching its ENI | wait for `State == Active` |
| token in git remote URL | credentials embedded in URL | revoke + use `gh auth` / keychain |

---

## 10. Cleanup (stops the only meaningful cost — RDS)
```bash
aws rds delete-db-instance --db-instance-identifier mypipe-pg --skip-final-snapshot --delete-automated-backups --region us-east-1
# also: delete the 5 Lambdas, the HTTP API, the state machine, EventBridge rule,
# security groups, subnet group, and empty the S3 bucket.
```

## What's next
- **Phase 7:** GitHub Actions deploys all of this on push (OIDC, no stored keys).
- **Phase 8:** capture everything above as Infrastructure-as-Code (AWS SAM).
- **Later:** Docker + EKS.
```
