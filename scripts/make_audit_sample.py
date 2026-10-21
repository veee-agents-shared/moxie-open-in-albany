#!/usr/bin/env python3
"""Create a deterministic, stratified status-audit sample."""
import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/moxie-albany.sqlite"
OUT = ROOT / "data/audit-sample-2026-10-21.csv"
SEED = "moxie-albany-audit-2026-10-21-v1"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT source_id,name,address,city,zip,municipality,status,inspection_date FROM businesses")]
con.close()

sample = []
for status, size in (("open", 20), ("likely closed", 20), ("unknown", 10)):
    group = [r for r in rows if r["status"] == status]
    group.sort(key=lambda r: hashlib.sha256(f"{SEED}:{r['source_id']}".encode()).hexdigest())
    sample.extend(group[:size])

sample.sort(key=lambda r: (r["status"], r["name"].casefold()))
with OUT.open("w", newline="", encoding="utf-8") as f:
    fields = ["source_id","name","address","city","zip","municipality","directory_status","inspection_date","website","check_result","checked_at","evidence_note"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in sample:
        w.writerow({k: r[k] for k in fields if k in r} | {"directory_status": r["status"], "website": "", "check_result": "pending", "checked_at": "", "evidence_note": ""})

print(f"wrote {len(sample)} records to {OUT}")
