"""
04_monitor.py — Pipeline monitor / health report.

Reads the per-step logs (clean, validate, store), computes funnel metrics and
overall yield, raises WARNING/ERROR flags, and writes logs/pipeline_report.json.

Flag rules:
  - ERROR   : a required step log is missing
  - WARNING : overall rejection rate > 20%
  - ERROR   : store failure rate > 5%
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

    # 1) Missing-log checks.
    for name, log in (("01_clean", clean), ("02_validate", validate), ("03_store", store)):
        if log is None:
            flags.append({"level": "ERROR", "message": f"Missing log for step {name}"})

    # 2) Funnel metrics (use 0 when a log is absent so the report still renders).
    received = clean.get("records_in") if clean else 0
    survived_cleaning = clean.get("records_out") if clean else 0
    passed_validation = validate.get("passed") if validate else 0
    stored = (store.get("inserted", 0) + store.get("updated", 0)) if store else 0
    store_failed = store.get("failed", 0) if store else 0

    overall_yield = pct(stored, received)
    rejection_rate = pct(received - stored, received)
    store_failure_rate = pct(store_failed, stored + store_failed)

    # 3) Threshold flags.
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
        "stage_drops": {
            "deduped_in_cleaning": (received - survived_cleaning) if clean else None,
            "failed_validation": (survived_cleaning - passed_validation) if validate else None,
            "failed_store": store_failed,
        },
        "flags": flags,
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    bar = "=" * 52
    print(bar)
    print(f"  PIPELINE HEALTH REPORT          status: {status}")
    print(bar)
    print(f"  Records received      : {received}")
    print(f"  Survived cleaning     : {survived_cleaning}  ({pct(survived_cleaning, received)}%)")
    print(f"  Passed validation     : {passed_validation}  ({pct(passed_validation, received)}%)")
    print(f"  Stored successfully   : {stored}  ({overall_yield}%)")
    print("  " + "-" * 48)
    print(f"  Overall yield         : {overall_yield}%")
    print(f"  Rejection rate        : {rejection_rate}%")
    print(f"  Store failure rate    : {store_failure_rate}%")
    print(bar)
    if flags:
        print("  FLAGS:")
        for f in flags:
            print(f"   [{f['level']}] {f['message']}")
    else:
        print("  No flags. Pipeline healthy.")
    print(bar)
    print(f"  Report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
