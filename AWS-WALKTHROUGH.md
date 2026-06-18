# AWS Migration — Complete Beginner Walkthrough

This document explains, step by step, how we moved the local data pipeline
(`/clean → /validate → /store → /monitor` + a FastAPI) onto AWS as a real
**event-driven** system, and exposed it through an authenticated API.

It's written for someone new to AWS. Read it top to bottom.

---

## The one big idea

**Local:** *you* are the trigger. You type `/clean`, then `/validate`, etc.
The order lives in your head, and everything runs on your laptop.

**AWS:** *an event* is the trigger. A file landing in storage automatically
starts the whole pipeline. The order lives in a service called Step Functions.
Nothing runs on your laptop — it all runs in Amazon's data centers.

Everything below is just plumbing around that one shift.

---

## Service cheat-sheet (AWS thing ↔ local thing)

| AWS service | Plain English | Replaced this locally |
|---|---|---|
| **S3** | Infinite cloud folder for files | `data/` folders |
| **Lambda** | Run a function with no server to manage | running a `.py` script |
| **IAM** | Permissions: who can do what | (nothing — your laptop trusted you) |
| **S3 event / EventBridge** | "When a file lands, do X" | you double-clicking run |
| **Step Functions** | A flowchart that runs steps in order | the order in `CLAUDE.md` |
| **VPC** | A private network | your laptop's local network |
| **RDS** | A managed database server | the SQLite file |
| **API Gateway** | A public front door (HTTPS URL) | `uvicorn` on localhost |
| **CloudWatch** | Logs + metrics | the `logs/*.json` files |

**CLI verbs in plain English** (the AWS CLI is just `aws <service> <verb>`):
- `create-*` = make a new thing
- `describe-* / list-* / get-*` = read/look at things
- `update-* / put-*` = change a thing (`put` usually overwrites)
- `invoke` = run a Lambda now
- `add-permission` = "allow this other service to call me"

---

## Phase 0 — Tools & setup

**What:** Made sure the AWS command-line tool worked and picked a region.

**How:**
```bash
aws sts get-caller-identity      # who am I, in AWS?
```
**Plain English:** `sts get-caller-identity` is the AWS version of `whoami`. It
prints your account number and user, proving your CLI is authenticated.

**Why:** Every later command talks to AWS through this CLI. If this doesn't
work, nothing else will.

**Result:** It printed our account ID (`905204392314`). We chose region
`us-east-1` and a naming prefix `mypipe-` for every resource.

---

## Phase 1 — S3, the landing zone

**What:** Created one cloud bucket with four "folders": `raw/ cleaned/
validated/ invalid/` — mirroring the local `data/` layout.

**How:**
```bash
aws s3 mb s3://mypipe-data-rg --region us-east-1
aws s3api put-public-access-block --bucket mypipe-data-rg \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-object --bucket mypipe-data-rg --key raw/
aws s3 cp data/raw/sample_raw.json s3://mypipe-data-rg/raw/
```
**Plain English:**
- `s3 mb` = "make bucket" (a bucket is a top-level container for files).
- `put-public-access-block` = "lock this bucket so nothing is public."
- `put-object --key raw/` = create an empty marker so the folder is visible.
- `s3 cp` = copy a local file up to the cloud.

**Why:** S3 is where files live in the cloud, and a new file in `raw/` is the
spark that will eventually trigger the whole pipeline. We keep it private
because security happens later at the API layer, not on the raw data.

**Result:** Bucket created; `raw/sample_raw.json` uploaded. `aws s3 ls`
showed the four prefixes and our file.

**Key fact:** S3 has no real folders. `raw/sample_raw.json` is just one long
filename ("key"). The part before the `/` acts like a folder.

---

## Phase 2 — The first Lambda (`clean`), triggered automatically

**What:** Took `pipeline/01_clean.py`, turned it into a Lambda function, and
made it run automatically whenever a file lands in `raw/`.

**How (the function):** We copied the cleaning logic unchanged and only swapped
the edges — read from S3 instead of a local file, write to S3 instead of a
folder. The new entry point is `lambda_handler(event, context)`.

**How (the commands):**
```bash
# 1. A "role" = the identity the Lambda runs as, with permissions attached
aws iam create-role --role-name mypipe-clean-role \
  --assume-role-policy-document file://aws/iam/lambda-trust-policy.json
aws iam attach-role-policy --role-name mypipe-clean-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name mypipe-clean-role \
  --policy-name mypipe-clean-s3 --policy-document file://aws/iam/clean-s3-policy.json

# 2. Zip the code and create the function
zip -j /tmp/mypipe-clean.zip aws/lambdas/clean/lambda_function.py
aws lambda create-function --function-name mypipe-clean \
  --runtime python3.12 --role <role-arn> \
  --handler lambda_function.lambda_handler \
  --zip-file fileb:///tmp/mypipe-clean.zip --region us-east-1

# 3. Let S3 call the Lambda, then connect the trigger
aws lambda add-permission --function-name mypipe-clean --statement-id s3invoke \
  --action lambda:InvokeFunction --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::mypipe-data-rg
aws s3api put-bucket-notification-configuration --bucket mypipe-data-rg \
  --notification-configuration file:///tmp/notif.json   # prefix raw/, suffix .json
```
**Plain English:**
- **Trust policy** = "who is allowed to *become* this role" (here: the Lambda service).
- **`attach-role-policy` (AWSLambdaBasicExecutionRole)** = lets the Lambda write logs.
- **`put-role-policy` (clean-s3)** = our custom rule: may read `raw/`, write `cleaned/`. Nothing else.
- **`zip -j`** = bundle the code (the `-j` puts the file at the top of the zip).
- **`create-function`** = upload the zip and make it a runnable Lambda.
- **`add-permission`** = allow the S3 service to trigger this function.
- **`put-bucket-notification-configuration`** = "when a `.json` lands under `raw/`, run the Lambda."

**Why:** This is the first taste of event-driven computing — code that runs by
itself in response to a file, with no server and no human.

**Why the `raw/` prefix matters:** the Lambda *writes* to `cleaned/` in the same
bucket. If the trigger watched the whole bucket, that write would trigger the
Lambda again → infinite loop → surprise bill. Scoping to `raw/` prevents it.

**Result:** Uploading to `raw/` auto-created `cleaned/sample_raw.json`. The logs
showed `in=7 dupes_removed=1 out=6` — identical to the local run.

---

## Phase 3 — More steps + orchestration (Step Functions + EventBridge)

**What:** Added `validate` and `monitor` Lambdas, then chained
`clean → validate → monitor` with **Step Functions**, and switched the trigger
so an upload starts the whole chain automatically.

### 3.1 — `validate` (packaging a dependency)
`validate` uses **pydantic**, which isn't built into Lambda. And pydantic has a
compiled (Linux) piece, so we had to fetch the **Linux** build, not the Mac one:
```bash
pip install pydantic -t /tmp/validate-build \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.12 --only-binary=:all:
```
**Plain English:** "install pydantic into a folder, but grab the Linux version
that matches Lambda." Without `--platform`, we'd ship a Mac build and Lambda
would crash on import.

### 3.2 — the accumulator idea
Locally, `/monitor` read each step's `logs/*.json`. In AWS we made each Lambda
**return everything it received plus what it did**. So the record counts pile up
as the data moves down the chain, and `monitor` gets the whole picture as input.

### 3.3 — Step Functions (the flowchart)
```bash
aws stepfunctions create-state-machine --name mypipe-pipeline \
  --definition file:///tmp/mypipe-statemachine.json --role-arn <sfn-role-arn>
aws stepfunctions start-execution --state-machine-arn <sm-arn> \
  --input '{"bucket":"mypipe-data-rg","key":"raw/sample_raw.json"}'
```
**Plain English:** The "definition" file is a flowchart in JSON: `Clean → Validate
→ Monitor`. `start-execution` runs it once. Each step's output becomes the next
step's input automatically, and Step Functions retries a step if it fails.

### 3.4 — EventBridge (auto-start on upload)
S3 can't call Step Functions directly, so we route through EventBridge:
```bash
aws s3api put-bucket-notification-configuration --bucket mypipe-data-rg \
  --notification-configuration '{ "EventBridgeConfiguration": {} }'
aws events put-rule --name mypipe-raw-upload --event-pattern file:///tmp/eb-pattern.json
aws events put-targets --rule mypipe-raw-upload --targets file:///tmp/eb-targets.json
```
**Plain English:**
- Turn on "send S3 events to EventBridge" for the bucket.
- A **rule** = "match new `.json` files under `raw/`."
- A **target** = "when matched, start the state machine," with an **input
  transformer** that reshapes the messy S3 event into the tidy `{bucket, key}`
  our pipeline wants.

**Why:** Step Functions gives ordering, retries, and a visual graph you never
had locally. EventBridge makes the whole thing fire on upload — true hands-off
automation.

**Result:** Uploading a file produced a `SUCCEEDED` execution we never started
by hand. Graph view showed `Clean → Validate → Monitor` all green.

---

## Phase 4 — A real database (RDS Postgres) + the `store` step

**What:** Stood up a managed Postgres database, learned VPC networking, and added
the `store` Lambda that writes records into it.

### The new concept: VPC (private network)
S3 and Lambda are reachable over the open internet (with permission). A database
is **not** — it lives inside a **VPC** (a private network). So the `store` Lambda
had to be **placed inside the same VPC** to reach the database. Once inside, it
loses internet access, so we used a free **S3 Gateway endpoint** so it could
still read `validated/`.

### The pieces
```bash
# Two security groups = firewalls
aws ec2 create-security-group --group-name mypipe-rds-sg ...
aws ec2 create-security-group --group-name mypipe-lambda-sg ...
# Rule: only the Lambda's group may reach the DB on port 5432
aws ec2 authorize-security-group-ingress --group-id <rds-sg> \
  --protocol tcp --port 5432 --source-group <lambda-sg>

# A subnet group, then the database itself (private, no public access)
aws rds create-db-subnet-group --db-subnet-group-name mypipe-db-subnets --subnet-ids <3 private subnets>
aws rds create-db-instance --db-instance-identifier mypipe-pg \
  --engine postgres --db-instance-class db.t3.micro --allocated-storage 20 \
  --db-subnet-group-name mypipe-db-subnets --vpc-security-group-ids <rds-sg> \
  --no-publicly-accessible
```
**Plain English:**
- **Security group** = a firewall around a resource. Ours says "only the Lambda
  may knock on the database's door (port 5432)."
- **Subnet** = a slice of the VPC tied to a data-center zone. A **subnet group**
  tells RDS which slices it can live in.
- **`create-db-instance`** = build the actual Postgres server. `--no-publicly-
  accessible` = no public address; only things inside the VPC can reach it.

### The `store` Lambda (in the VPC)
```bash
aws lambda create-function --function-name mypipe-store ... \
  --vpc-config "SubnetIds=<private subnets>,SecurityGroupIds=<lambda-sg>" \
  --environment file:///tmp/api-env.json   # DB host/user/password
```
**Plain English:** `--vpc-config` puts the Lambda inside the private network so
it can reach Postgres. `--environment` passes the DB connection details. The code
uses `pg8000` (a pure-Python Postgres driver) and Postgres's `INSERT ... ON
CONFLICT` for clean upserts.

**Why:** A database is the proper home for the cleaned data — queryable, durable,
shareable with the API. The VPC work is the price of doing databases securely.

**Result:** Invoking `store` returned `inserted: 5`. Running it again returned
`updated: 5` (proving upsert). We then added `Store` to the state machine between
`Validate` and `Monitor`, and the full pipeline reported
`stored_successfully: 5`.

---

## Phase 6 — The authenticated API (FastAPI on Lambda + API Gateway)

**What:** Ran the existing FastAPI app on Lambda (unchanged) and exposed it on a
public HTTPS URL, with the original API-key auth intact, reading from Postgres.

### The pieces
- **Mangum**: a 3-line adapter that lets the same FastAPI `app` run on Lambda.
- Postgres version of `db_models.py` (same models, different connection).
- Packaged FastAPI + Mangum + SQLAlchemy + pg8000, deployed **in the VPC**
  (to reach RDS), with the DB creds and `API_KEYS` as environment variables.

```bash
aws lambda create-function --function-name mypipe-api ... \
  --handler main.handler \
  --vpc-config "SubnetIds=<private subnets>,SecurityGroupIds=<lambda-sg>" \
  --environment file:///tmp/api-env.json

# Put API Gateway (a public front door) in front of it
aws apigatewayv2 create-api --name mypipe-http-api --protocol-type HTTP
aws apigatewayv2 create-integration --api-id <id> --integration-type AWS_PROXY \
  --integration-uri <lambda-arn> --payload-format-version 2.0
aws apigatewayv2 create-route --api-id <id> --route-key '$default' --target integrations/<int-id>
aws apigatewayv2 create-stage --api-id <id> --stage-name '$default' --auto-deploy
aws lambda add-permission --function-name mypipe-api --principal apigateway.amazonaws.com ...
```
**Plain English:**
- **`create-api`** = make a public HTTPS endpoint.
- **integration (AWS_PROXY)** = "forward the raw request to my Lambda."
- **route `$default`** = "send every path to that Lambda" (FastAPI does the
  internal routing).
- **stage `--auto-deploy`** = publish changes immediately.
- **`add-permission`** = allow API Gateway to call the Lambda.

**Why:** This is how the world reaches your pipeline's data — a stable HTTPS URL,
with your authentication enforced on every request.

**Result (over plain HTTPS with curl):**
- `GET /health` → `200` (public)
- `GET /api/v1/users` with no key → `401` (auth working)
- `GET /api/v1/users/stats/summary` with the admin key → live stats from Postgres
- `/docs` renders the full interactive API documentation

---

## The final architecture

```
        upload ──► EventBridge ──► Step Functions: Clean→Validate→Store→Monitor ──► RDS Postgres
                                   (auto, with retries + visual graph)               │
                                                                                     │
   internet ──► API Gateway ──► Lambda (FastAPI + API-key auth) ─────────────────────┘
```

---

## Gotchas we hit (and the lessons)

1. **AWS CLI v1 vs v2** — `aws logs tail` and `--cli-binary-format` are v2-only.
   You're on v1; we worked around it. Upgrading to v2 removes the friction.
2. **zsh quirks** (your shell is stricter than bash):
   - `$VAR:role` — zsh reads `:r` as a modifier. Fix: `${VAR}` or fetch the ARN
     from AWS instead of building strings.
   - Pasted `#` comments aren't comments by default → run `setopt interactive_comments`.
   - Unquoted `$VAR` does **not** split into multiple arguments → use `${=VAR}`.
3. **No default VPC** — this account uses a custom "presales" VPC, so we pointed
   everything at it explicitly and used its private subnets.
4. **Don't transcribe IDs by eye** — fetch them from the API into variables.
5. **VPC Lambdas start as `Pending`** — they need a network interface; wait for
   `Active` before invoking.
6. **A leaked token in the git remote URL** — never embed credentials in URLs;
   rotate immediately if you do.

---

## What's left

- **Phase 7:** GitHub Actions deploys all of this on push (via OIDC, no stored keys).
- **Phase 8:** Capture the whole setup as Infrastructure-as-Code (SAM) instead of
  clicking/CLI commands.
- **Later:** Docker + EKS.

## Cleanup (to stop costs when done)
RDS is the only piece that costs meaningfully while idle. When finished:
`aws rds delete-db-instance --db-instance-identifier mypipe-pg --skip-final-snapshot --delete-automated-backups`
(plus deleting the Lambdas, API, state machine, and S3 objects).
```
