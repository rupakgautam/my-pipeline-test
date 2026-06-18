"""
mypipe-monitor — Lambda version of pipeline/04_monitor.py

WHAT CHANGED vs the local script:
  - Local read the per-step files in logs/*.json.
  - Here the counts arrive in the event payload, accumulated by the previous
    steps (clean/validate/store each added a sub-dict). Step Functions threaded
    them here. The execution history IS the log.

Computes the same funnel metrics + WARNING/ERROR flags, writes the report to
s3://<bucket>/reports/<file>, and returns it.

DEPENDENCIES: standard library + boto3 only.
"""

import json
import boto3
from datetime import datetime

s3 = boto3.client("s3")


def pct(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def lambda_handler(event, context):
    clean = event.get("clean", {})
    validate = event.get("validate", {})
    store = event.get("store", {})          # absent until Phase 4 — defaults to {}

    flags = []

    # Missing-step checks (mirror the local "missing log" ERRORs)
    if not clean:
        flags.append({"level": "ERROR", "message": "Missing results for step clean"})
    if not validate:
        flags.append({"level": "ERROR", "message": "Missing results for step validate"})
    # store is optional for now; it gets added in Phase 4.

    received = clean.get("records_in", 0)
    survived_cleaning = clean.get("records_out", 0)
    passed_validation = validate.get("passed", 0)
    stored = store.get("inserted", 0) + store.get("updated", 0)
    store_failed = store.get("failed", 0)

    overall_yield = pct(stored, received)
    rejection_rate = pct(received - stored, received)
    store_failure_rate = pct(store_failed, stored + store_failed)

    if rejection_rate > 20:
        flags.append({
            "level": "WARNING",
            "message": f"Rejection rate {rejection_rate}% exceeds 20% threshold",
        })
    if store_failure_rate > 5:
        flags.append({
            "level": "ERROR",
            "message": f"Store failure rate {store_failure_rate}% exceeds 5% threshold",
        })

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

    # Write the report to S3 (replaces logs/pipeline_report.json)
    bucket = event.get("bucket")
    if bucket:
        key = event.get("key", "unknown.json")
        filename = key.split("/")[-1]
        report_key = f"reports/{filename}"
        s3.put_object(
            Bucket=bucket, Key=report_key,
            Body=json.dumps(report, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        report["report_key"] = report_key
        print(f"Report -> s3://{bucket}/{report_key}")

    print(f"STATUS={status} funnel={report['funnel']} flags={flags}")
    return report
