#!/usr/bin/env python3
"""Generate a conservative queue of inactive-to-active entity matches for review."""
import csv
import difflib
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "data/raw/nysdoh_active_albany_2026-10-21.csv"
INACTIVE_IDS = ROOT / "data/raw/nysdoh_inactive_ids_albany_2026-10-21.csv"
INACTIVE_DETAILS = ROOT / "data/raw/nysdoh_inactive_details_albany_2026-10-21.csv"
REVIEWED = ROOT / "data/entity-matches.csv"
OVERRIDES = ROOT / "data/status-overrides.csv"
OUTPUT = ROOT / "data/entity-match-candidates-2026-10-21.csv"

GENERIC_NAME_TOKENS = {
    "AND", "AT", "CAFE", "CAFETERIA", "CO", "COMPANY", "DORMANT", "FOOD",
    "INC", "INACTIVE", "LLC", "OF", "RESTAURANT", "SERVICE", "SERVICES", "THE",
}


def clean(value):
    return (value or "").strip()


def normalized(value):
    value = clean(value).upper()
    for old, new in (("STREET", "ST"), ("ROAD", "RD"), ("AVENUE", "AVE"),
                     ("ROUTE", "RT"), ("BOULEVARD", "BLVD")):
        value = value.replace(old, new)
    return re.sub(r"[^A-Z0-9]", "", value)


def name_tokens(value):
    return {
        token for token in re.findall(r"[A-Z0-9]+", clean(value).upper())
        if len(token) > 1 and token not in GENERIC_NAME_TOKENS
    }


def terminal_designator(value):
    """Return a store/version suffix whose mismatch makes a merge ambiguous."""
    tokens = re.findall(r"[A-Z0-9]+", clean(value).upper())
    if tokens and (tokens[-1].isdigit() or tokens[-1] in {"I", "II", "III", "IV", "V"}):
        return tokens[-1]
    return ""


active = {}
with ACTIVE.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if clean(row.get("county")).upper() != "ALBANY":
            continue
        source_id = clean(row.get("nys_health_operation_id"))
        candidate = {
            "source_id": source_id,
            "name": clean(row.get("operation_name")) or clean(row.get("facility")),
            "address": clean(row.get("facility_address")),
            "inspection_date": clean(row.get("date_of_inspection"))[:10],
        }
        if source_id not in active or candidate["inspection_date"] > active[source_id]["inspection_date"]:
            active[source_id] = candidate

inactive_dates = {}
with INACTIVE_IDS.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        inactive_dates[clean(row.get("nys_health_operation_id"))] = clean(row.get("last_inspection"))[:10]

inactive = {}
with INACTIVE_DETAILS.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        source_id = clean(row.get("nys_health_operation_id"))
        raw_name = clean(row.get("operation_name"))
        inactive[source_id] = {
            "source_id": source_id,
            "name": re.sub(r"(?:/(?:inactive|dormant))+\s*$", "", raw_name, flags=re.I).strip(),
            "address": clean(row.get("facility_address")),
            "inspection_date": inactive_dates.get(source_id, ""),
        }

# Mirror the build's exact-identity collapse so every queued ID is still a
# standalone entity by the time reviewed matches are applied.
with OVERRIDES.open(newline="", encoding="utf-8") as f:
    override_ids = {row["source_id"] for row in csv.DictReader(f)}
for records, use_overrides in ((active, False), (inactive, True)):
    groups = defaultdict(list)
    for row in records.values():
        groups[(normalized(row["name"]), normalized(row["address"]))].append(row)
    keep_ids = set()
    for group in groups.values():
        current = max(group, key=lambda row: (
            row["source_id"] in override_ids if use_overrides else False,
            row["inspection_date"], row["source_id"],
        ))
        keep_ids.add(current["source_id"])
    for source_id in set(records) - keep_ids:
        del records[source_id]

reviewed_old_ids = set()
with REVIEWED.open(newline="", encoding="utf-8") as f:
    reviewed_old_ids = {row["old_source_id"] for row in csv.DictReader(f)}

active_by_address = defaultdict(list)
inactive_by_address = defaultdict(list)
for row in active.values():
    active_by_address[normalized(row["address"])].append(row)
for row in inactive.values():
    inactive_by_address[normalized(row["address"])].append(row)

candidates = []
for address_key, old_rows in inactive_by_address.items():
    current_rows = active_by_address.get(address_key, [])
    # Multiple current operation IDs at one address are often legitimately distinct
    # kitchens or frozen-dessert permits, so they require a different review method.
    if len(current_rows) != 1:
        continue
    current = current_rows[0]
    for old in old_rows:
        if old["source_id"] in reviewed_old_ids or normalized(old["name"]) == normalized(current["name"]):
            continue
        old_tokens = name_tokens(old["name"])
        current_tokens = name_tokens(current["name"])
        similarity = difflib.SequenceMatcher(
            None, normalized(old["name"]), normalized(current["name"])
        ).ratio()
        same_core_tokens = bool(old_tokens) and old_tokens == current_tokens
        frozen_mismatch = ("FROZEN DESSERT" in old["name"].upper()) != (
            "FROZEN DESSERT" in current["name"].upper()
        )
        designator_mismatch = terminal_designator(old["name"]) != terminal_designator(current["name"])
        if frozen_mismatch or designator_mismatch or not (same_core_tokens or similarity >= 0.80):
            continue
        reason = "same address; exact core name tokens" if same_core_tokens else "same address; high normalized-name similarity"
        candidates.append({
            "old_source_id": old["source_id"],
            "old_name": old["name"],
            "old_inspection_date": old["inspection_date"],
            "current_source_id": current["source_id"],
            "current_name": current["name"],
            "current_inspection_date": current["inspection_date"],
            "address": current["address"],
            "name_similarity": f"{similarity:.3f}",
            "candidate_reason": reason,
            "inactive_ids_at_address": str(len(old_rows)),
        })

candidates.sort(key=lambda row: (-float(row["name_similarity"]), row["old_name"], row["old_source_id"]))
fields = [
    "old_source_id", "old_name", "old_inspection_date", "current_source_id",
    "current_name", "current_inspection_date", "address", "name_similarity",
    "candidate_reason", "inactive_ids_at_address",
]
with OUTPUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(candidates)

print(f"wrote {len(candidates)} review candidates to {OUTPUT.relative_to(ROOT)}")
