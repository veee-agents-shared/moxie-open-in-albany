#!/usr/bin/env python3
"""Merge hand-check evidence into the fixed audit sample."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/audit-sample-2026-10-21.csv"
CHECKS = ROOT / "data/audit-checks-2026-10-21.csv"

with CHECKS.open(newline="", encoding="utf-8") as f:
    checks = {r["source_id"]: r for r in csv.DictReader(f)}
with SAMPLE.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fields = reader.fieldnames
    rows = list(reader)
for row in rows:
    if row["source_id"] in checks:
        row.update(checks[row["source_id"]])
with SAMPLE.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print(f"merged {len(checks)} checks; {sum(r['check_result'] != 'pending' for r in rows)}/{len(rows)} complete")
