#!/usr/bin/env python3
"""Build the Albany food-establishment database and static directory."""
import csv
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "data/raw/nysdoh_active_albany_2026-10-21.csv"
INACTIVE_IDS = ROOT / "data/raw/nysdoh_inactive_ids_albany_2026-10-21.csv"
INACTIVE_DETAILS = ROOT / "data/raw/nysdoh_inactive_details_albany_2026-10-21.csv"
OVERRIDES = ROOT / "data/status-overrides.csv"
ENTITY_MATCHES = ROOT / "data/entity-matches.csv"
LIQUOR = ROOT / "data/raw/nysla_active_albany_2026-10-21.csv"
DB = ROOT / "data/moxie-albany.sqlite"
SITE = ROOT / "docs"
AS_OF = "2026-10-21"

def clean(value):
    return (value or "").strip()

def slug(value):
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:70] or "business"
    return base

def esc(value):
    return html.escape(str(value or ""), quote=True)

def normalized(value):
    value = (value or "").upper()
    for old, new in (("STREET", "ST"), ("ROAD", "RD"), ("AVENUE", "AVE"), ("ROUTE", "RT"), ("BOULEVARD", "BLVD")):
        value = value.replace(old, new)
    return re.sub(r"[^A-Z0-9]", "", value)

def entity_key(row):
    return normalized(row["name"]), normalized(row["address"])

def page(title, body, depth=""):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Open in Albany</title><link rel="stylesheet" href="{depth}style.css"></head><body><header><a href="{depth}index.html">Open in Albany</a><span>Food-service directory</span></header><main>{body}</main><footer><p>Built and maintained by <strong>Moxie, an AI agent</strong>. Data is collected from official public sources; see <a href="{depth}methodology.html">methodology and limitations</a>. Corrections or removal: <a href="mailto:moxie@veee.land">moxie@veee.land</a>.</p><p>Last rebuilt {AS_OF}.</p></footer></body></html>'''

active_by_id = {}
with ACTIVE.open(newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if clean(r.get("county")).upper() != "ALBANY":
            continue
        name = clean(r.get("operation_name")) or clean(r.get("facility"))
        key = clean(r.get("nys_health_operation_id")) or hashlib.sha1((name + clean(r.get("facility_address"))).encode()).hexdigest()[:12]
        candidate = {
            "source_id": key, "name": name, "address": clean(r.get("facility_address")),
            "city": clean(r.get("facility_city")), "zip": clean(r.get("facility_postal_zipcode")),
            "municipality": clean(r.get("facility_municipality")) or clean(r.get("facility_city")),
            "category": clean(r.get("food_service_description")) or "Food service establishment",
            "inspection_date": clean(r.get("date_of_inspection"))[:10],
            "permit_expiration": clean(r.get("permit_expiration_date"))[:10],
            "lat": float(r["latitude"]) if clean(r.get("latitude")) else None,
            "lon": float(r["longitude"]) if clean(r.get("longitude")) else None,
            "status": "open", "feed_status": "active",
        }
        old = active_by_id.get(key)
        if old is None or candidate["inspection_date"] > old["inspection_date"]:
            active_by_id[key] = candidate

rows = list(active_by_id.values())

inactive_dates = {}
with INACTIVE_IDS.open(newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        inactive_dates[clean(r.get("nys_health_operation_id"))] = clean(r.get("last_inspection"))[:10]
with INACTIVE_DETAILS.open(newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        key = clean(r.get("nys_health_operation_id"))
        raw_name = clean(r.get("operation_name"))
        name = re.sub(r"(?:/(?:inactive|dormant))+\s*$", "", raw_name, flags=re.I).strip() or raw_name
        rows.append({
            "source_id": key, "name": name, "address": clean(r.get("facility_address")),
            "city": clean(r.get("facility_city")), "zip": clean(r.get("zip")),
            "municipality": clean(r.get("municipality")) or clean(r.get("facility_city")),
            "category": "Food service establishment (inactive record)",
            "inspection_date": inactive_dates.get(key, ""), "permit_expiration": "",
            "lat": None, "lon": None, "status": "likely closed", "feed_status": "inactive",
        })

# One row per operation ID; the source snapshot should already have this granularity.
deduped = {}
for r in rows:
    old = deduped.get(r["source_id"])
    if old is None or (r["status"] == "open" and old["status"] != "open") or r["inspection_date"] > old["inspection_date"]:
        deduped[r["source_id"]] = r
rows = sorted(deduped.values(), key=lambda r: (r["name"].casefold(), r["address"]))

with OVERRIDES.open(newline="", encoding="utf-8") as f:
    overrides = {r["source_id"]: r for r in csv.DictReader(f)}
for r in rows:
    if r["source_id"] in overrides:
        r["status"] = overrides[r["source_id"]]["status"]
        r["override_url"] = overrides[r["source_id"]]["url"]
        r["override_reason"] = overrides[r["source_id"]]["reason"]

# Collapse repeated operation IDs for the same exact normalized identity, retaining
# the most recently inspected record and preserving older IDs as evidence.
superseded = {}
active_groups = {}
for r in rows:
    if r["feed_status"] == "active":
        active_groups.setdefault(entity_key(r), []).append(r)
active_keep = set()
active_collapsed = 0
for group in active_groups.values():
    current = max(group, key=lambda x: (x["inspection_date"], x["source_id"]))
    active_keep.add(current["source_id"])
    for old in group:
        if old["source_id"] != current["source_id"]:
            superseded.setdefault(current["source_id"], []).append(old)
            active_collapsed += 1
rows = [r for r in rows if r["feed_status"] != "active" or r["source_id"] in active_keep]

inactive_groups = {}
for r in rows:
    if r["feed_status"] == "inactive":
        inactive_groups.setdefault(entity_key(r), []).append(r)
inactive_keep = set()
inactive_collapsed = 0
for group in inactive_groups.values():
    # A dated direct check belongs to the entity even when a newer obsolete health ID exists.
    current = max(group, key=lambda x: (x["source_id"] in overrides, x["inspection_date"], x["source_id"]))
    inactive_keep.add(current["source_id"])
    for old in group:
        if old["source_id"] != current["source_id"]:
            superseded.setdefault(current["source_id"], []).append(old)
            inactive_collapsed += 1
rows = [r for r in rows if r["feed_status"] != "inactive" or r["source_id"] in inactive_keep]

# Operation IDs can also change while the same establishment remains open. Reconcile exact
# normalized name+address matches so an old inactive ID does not create a false closure.
active_entities = {entity_key(r): r for r in rows if r["feed_status"] == "active"}
kept = []
active_reconciled = 0
for r in rows:
    current = active_entities.get(entity_key(r))
    if r["feed_status"] == "inactive" and current:
        superseded.setdefault(current["source_id"], []).append(r)
        active_reconciled += 1
    else:
        kept.append(r)
rows = kept

# Reviewed non-exact matches handle clear renames at the same facility without
# broad fuzzy matching. Preserve the old ID as evidence on the current entity.
manual_reconciled = 0
by_id = {r["source_id"]: r for r in rows}
manual_old_ids = set()
with ENTITY_MATCHES.open(newline="", encoding="utf-8") as f:
    for match in csv.DictReader(f):
        old = by_id.get(match["old_source_id"])
        current = by_id.get(match["current_source_id"])
        if not old or not current or current["feed_status"] != "active":
            raise ValueError(f"Invalid reviewed entity match: {match}")
        old = dict(old)
        old["manual_match_reason"] = match["reason"]
        superseded.setdefault(current["source_id"], []).append(old)
        manual_old_ids.add(old["source_id"])
        manual_reconciled += 1
rows = [r for r in rows if r["source_id"] not in manual_old_ids]

# A current liquor license conflicts with an inactive health operation but does not,
# by itself, prove food service is open. Mark exact identity matches unknown for review.
liquor_matches = {}
with LIQUOR.open(newline="", encoding="utf-8-sig") as f:
    for lic in csv.DictReader(f):
        for lic_name in (clean(lic.get("dba")), clean(lic.get("legalname"))):
            if lic_name:
                liquor_matches[(normalized(lic_name), normalized(lic.get("actualaddressofpremises")))] = lic
liquor_conflicts = 0
for r in rows:
    lic = liquor_matches.get(entity_key(r))
    if lic:
        r["liquor_license"] = lic
        if r["status"] == "likely closed" and not r.get("override_url"):
            r["status"] = "unknown"
            liquor_conflicts += 1

DB.unlink(missing_ok=True)
con = sqlite3.connect(DB)
con.executescript('''
CREATE TABLE sources (id TEXT PRIMARY KEY, title TEXT, url TEXT, retrieved TEXT, license TEXT);
CREATE TABLE businesses (source_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, city TEXT, zip TEXT, municipality TEXT, category TEXT, status TEXT NOT NULL, status_as_of TEXT NOT NULL, inspection_date TEXT, permit_expiration TEXT, latitude REAL, longitude REAL, source TEXT NOT NULL);
CREATE TABLE evidence (business_id TEXT, evidence_type TEXT, observed_date TEXT, detail TEXT, source TEXT, PRIMARY KEY (business_id, evidence_type, observed_date));
''')
con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", ("nysdoh-2hcc-shji", "NYS DOH Food Service Establishment Inspections: Beginning 2005 (ACTIVE)", "https://health.data.ny.gov/d/2hcc-shji", AS_OF, "Unspecified on source portal"))
con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", ("nysdoh-aaxz-j6pj", "NYS DOH Food Service Establishment Inspections (INACTIVE)", "https://health.data.ny.gov/d/aaxz-j6pj", AS_OF, "Unspecified on source portal"))
con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", ("nysla-9s3h-dpkz", "NYS Liquor Authority Current Active Licenses", "https://data.ny.gov/d/9s3h-dpkz", AS_OF, "Unspecified on source portal"))
for source_id, override in overrides.items():
    con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (f"business-website:{source_id}", "Direct website status check", override["url"], override["checked_at"], "Linked evidence only; site content not republished"))
for r in rows:
    source = f"business-website:{r['source_id']}" if r.get("override_url") else ("nysdoh-2hcc-shji" if r["status"] == "open" else "nysdoh-aaxz-j6pj")
    con.execute("INSERT INTO businesses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["source_id"], r["name"], r["address"], r["city"], r["zip"], r["municipality"], r["category"], r["status"], AS_OF, r["inspection_date"], r["permit_expiration"], r["lat"], r["lon"], source))
    evidence_type = "business_confirmed_open" if r.get("override_url") else ("listed_active" if r["status"] == "open" else "listed_inactive")
    detail = r.get("override_reason") or ("Included in NYSDOH's active food-service establishment data" if r["status"] == "open" else "Included in NYSDOH's inactive food-service establishment data")
    con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], evidence_type, AS_OF, detail, source))
    if r["inspection_date"]:
        inspection_source = "nysdoh-2hcc-shji" if r["feed_status"] == "active" else "nysdoh-aaxz-j6pj"
        con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], "inspection", r["inspection_date"], "Latest reported inspection date", inspection_source))
    for old in superseded.get(r["source_id"], []):
        old_source = "nysdoh-2hcc-shji" if old["feed_status"] == "active" else "nysdoh-aaxz-j6pj"
        match_detail = old.get("manual_match_reason") or f"Older {old['feed_status']} operation ID {old['source_id']} reconciled by exact normalized name and address"
        con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], f"superseded_{old['feed_status']}_id:{old['source_id']}", old["inspection_date"] or AS_OF, match_detail, old_source))
    if r.get("liquor_license"):
        lic = r["liquor_license"]
        con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], "active_liquor_license", AS_OF, f"Current active liquor license {lic['licensepermitid']} expires {clean(lic.get('expirationdate'))[:10]}", "nysla-9s3h-dpkz"))
con.commit()
con.close()

SITE.mkdir(exist_ok=True)
(SITE / "businesses").mkdir(exist_ok=True)
(SITE / "towns").mkdir(exist_ok=True)
for old_page in (SITE / "businesses").glob("*.html"):
    old_page.unlink()
for old_page in (SITE / "towns").glob("*.html"):
    old_page.unlink()

used = {}
# Allocate existing active slugs first so adding closure history does not break live URLs.
for r in sorted(rows, key=lambda x: (x["status"] != "open", x["name"].casefold(), x["address"])):
    s = slug(r["name"])
    used[s] = used.get(s, 0) + 1
    r["slug"] = s if used[s] == 1 else f"{s}-{r['source_id']}"
    is_open = r["status"] == "open"
    is_unknown = r["status"] == "unknown"
    source_url = r.get("override_url") or ("https://data.ny.gov/d/9s3h-dpkz" if is_unknown else ("https://health.data.ny.gov/d/2hcc-shji" if is_open else "https://health.data.ny.gov/d/aaxz-j6pj"))
    evidence = r.get("override_reason") or (f"NYSDOH lists this operation ID inactive, but NYSLA lists an active liquor license at the exact normalized name and address as retrieved {AS_OF}." if is_unknown else f"Listed in NYSDOH's {'active' if is_open else 'inactive'} food-service feed as retrieved {AS_OF}.")
    meaning = ("The evidence conflicts, so no open-or-closed claim is made until a direct check resolves it." if is_unknown else (("This business-owned source overrides a conflicting inactive operation ID; the conflict is retained in the methodology." if r.get("override_url") else "The official source treats the establishment as currently operating; this is not a guarantee of today's hours.") if is_open else "This is historical closure evidence, not an independent same-day check; a later business at the same address may be unrelated."))
    permit = f"<dt>Permit expiration</dt><dd>{esc(r['permit_expiration'] or 'Not stated')}</dd>" if is_open else ""
    details = f'''<p class="crumb"><a href="../index.html">Directory</a> / {esc(r['municipality'].title())}</p><h1>{esc(r['name'].title())}</h1><p class="status {'unknown' if is_unknown else ('closed' if not is_open else '')}">{esc(r['status'].title())} <small>official-feed evidence</small></p><dl><dt>Address</dt><dd>{esc(r['address'].title())}, {esc(r['city'].title())} {esc(r['zip'])}</dd><dt>Type</dt><dd>{esc(r['category'])}</dd><dt>Latest reported inspection</dt><dd>{esc(r['inspection_date'] or 'Not stated')}</dd>{permit}</dl><h2>Why this status?</h2><p>{esc(evidence)} {esc(meaning)}</p><p class="source"><a href="{source_url}">View supporting source</a> · NYS Health Operation ID {esc(r['source_id'])}</p>'''
    (SITE / "businesses" / f"{r['slug']}.html").write_text(page(r["name"], details, "../"), encoding="utf-8")

towns = {}
for r in rows:
    towns.setdefault(r["municipality"] or "Unknown", []).append(r)
for town, items in towns.items():
    listing = "".join(f'<li><a href="../businesses/{esc(r["slug"])}.html">{esc(r["name"].title())}</a><span>{esc(r["status"].title())} · {esc(r["address"].title())}</span></li>' for r in items)
    active_count = sum(r["status"] == "open" for r in items)
    unknown_count = sum(r["status"] == "unknown" for r in items)
    body = f'<p class="crumb"><a href="../index.html">Directory</a></p><h1>{esc(town.title())}</h1><p>{active_count} open, {len(items)-active_count-unknown_count} likely closed, and {unknown_count} unknown establishments, based on dated evidence.</p><ul class="directory">{listing}</ul>'
    (SITE / "towns" / f"{slug(town)}.html").write_text(page(town.title(), body, "../"), encoding="utf-8")

town_links = "".join(f'<li><a href="towns/{slug(t)}.html">{esc(t.title())}</a><strong>{len(v)}</strong></li>' for t, v in sorted(towns.items()))
open_count = sum(r["status"] == "open" for r in rows)
unknown_count = sum(r["status"] == "unknown" for r in rows)
closed_count = len(rows) - open_count - unknown_count
home = f'''<section class="hero"><p class="eyebrow">Albany County, New York</p><h1>Which local food businesses are still open?</h1><p>A transparent directory with <strong>{open_count} open</strong>, <strong>{closed_count} likely closed</strong>, and <strong>{unknown_count} unknown</strong> food-service establishments, with dated evidence for every status.</p></section><section class="search"><h2>Find an establishment</h2><div class="search-controls"><input id="q" type="search" placeholder="Name, address, or town" aria-label="Search businesses"><select id="status" aria-label="Filter by status"><option value="all">All statuses</option><option value="open">Open</option><option value="likely closed">Likely closed</option><option value="unknown">Unknown</option></select></div><p id="search-note">Enter at least two characters.</p><ul id="results" class="directory"></ul></section><h2>Browse by municipality</h2><ul class="towns">{town_links}</ul><p class="downloads"><a href="open-food-businesses.csv">Download open businesses CSV</a> · <a href="all-food-business-statuses.csv">Download all statuses CSV</a></p><section class="notice"><h2>What this release covers</h2><p>Food-service businesses only—not yet every small business in the county. Statuses begin with state health inspection feeds, with business-owned websites and current state liquor licenses used to expose conflicts. The 50-record accuracy audit is in progress.</p></section><script src="search.js" defer></script>'''
(SITE / "index.html").write_text(page("Open food businesses in Albany County", home), encoding="utf-8")
applied_overrides = sum(bool(r.get("override_url")) for r in rows)
method = f'''<h1>Methodology</h1><p>Open in Albany is built by Moxie, an AI agent. This release uses New York State Department of Health active and inactive food-service inspection datasets, filtered to Albany County and matched by NYS Health Operation ID.</p><h2>Status rules</h2><p><strong>Open:</strong> present in the official active inspection-history feed on the retrieval date, or confirmed at the same name and address by a current business-owned website. This does not guarantee today's hours.</p><p><strong>Likely closed:</strong> present in the official inactive feed, absent from active, and not contradicted by checked current evidence. This is historical closure evidence, not an independent same-day check.</p><p><strong>Unknown:</strong> conflicting evidence—for this release, an inactive health operation with an exact name-and-address match in the current active liquor-license feed. No open-or-closed claim is made.</p><h2>Identity reconciliation</h2><p>The {len(active_by_id):,} active and 4,996 inactive operation IDs had zero ID overlap. Because operation IDs can change, {active_collapsed} repeated active and {inactive_collapsed} repeated inactive IDs were collapsed into their most recently inspected exact normalized name-and-address identity, {active_reconciled} more inactive IDs were reconciled by exact identity, and {manual_reconciled} reviewed rename was reconciled at an exact address. {applied_overrides} additional inactive-ID conflicts are overridden by dated direct web evidence. {liquor_conflicts} conflicts with current active liquor licenses are labelled unknown pending direct checks.</p><h2>Limits</h2><p>Inspection and licensing information are snapshots. NYSDOH did not collect inspection data to create restaurant grades, and this site does not grade establishments. Any analysis or interpretation here is Moxie's, not NYSDOH's or NYSLA's. This release covers food service only. A reproducible 50-record accuracy audit is in progress.</p><h2>Corrections and removal</h2><p>Email <a href="mailto:moxie@veee.land">moxie@veee.land</a>. Requests are handled within one day and removals are kept out of later refreshes.</p><p><a href="https://health.data.ny.gov/d/2hcc-shji">Official active health dataset</a> · <a href="https://health.data.ny.gov/d/aaxz-j6pj">Official inactive health dataset</a> · <a href="https://data.ny.gov/d/9s3h-dpkz">Official active liquor-license dataset</a></p>'''
(SITE / "methodology.html").write_text(page("Methodology", method), encoding="utf-8")

with (SITE / "open-food-businesses.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["name", "address", "city", "zip", "municipality", "category", "status", "status_as_of", "latest_inspection", "permit_expiration", "source_url"])
    for r in (x for x in rows if x["status"] == "open"):
        source_url = r.get("override_url") or "https://health.data.ny.gov/d/2hcc-shji"
        w.writerow([r["name"], r["address"], r["city"], r["zip"], r["municipality"], r["category"], "open", AS_OF, r["inspection_date"], r["permit_expiration"], source_url])

with (SITE / "all-food-business-statuses.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["name", "address", "city", "zip", "municipality", "category", "status", "status_as_of", "latest_inspection", "source_url"])
    for r in rows:
        source_url = r.get("override_url") or ("https://health.data.ny.gov/d/2hcc-shji" if r["status"] == "open" else "https://health.data.ny.gov/d/aaxz-j6pj")
        w.writerow([r["name"], r["address"], r["city"], r["zip"], r["municipality"], r["category"], r["status"], AS_OF, r["inspection_date"], source_url])

search_rows = [{"n": r["name"], "a": r["address"], "m": r["municipality"], "s": r["status"], "u": f"businesses/{r['slug']}.html"} for r in rows]
(SITE / "search-data.json").write_text(json.dumps(search_rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
(SITE / "search.js").write_text('''(()=>{const q=document.querySelector("#q"),status=document.querySelector("#status"),out=document.querySelector("#results"),note=document.querySelector("#search-note");let data;const esc=s=>{const d=document.createElement("div");d.textContent=s;return d.innerHTML};async function run(){const term=q.value.trim().toLocaleLowerCase();if(term.length<2){out.innerHTML="";note.textContent="Enter at least two characters.";return}if(!data){note.textContent="Loading directory…";data=await fetch("search-data.json").then(r=>r.json())}const words=term.split(/\\s+/),wanted=status.value;const hits=data.filter(x=>(wanted==="all"||x.s===wanted)&&words.every(w=>(x.n+" "+x.a+" "+x.m).toLocaleLowerCase().includes(w))).slice(0,50);out.innerHTML=hits.map(x=>`<li><a href="${encodeURI(x.u)}">${esc(x.n.replace(/\\b\\w/g,c=>c.toUpperCase()))}</a><span>${esc(x.s.replace(/\\b\\w/g,c=>c.toUpperCase()))} · ${esc(x.a.replace(/\\b\\w/g,c=>c.toUpperCase()))}</span></li>`).join("");note.textContent=hits.length===50?"Showing the first 50 matches.":`${hits.length} match${hits.length===1?"":"es"}.`}q.addEventListener("input",run);status.addEventListener("change",run)})();''', encoding="utf-8")

(SITE / "style.css").write_text('''*{box-sizing:border-box}body{margin:0;background:#f7f4ed;color:#18302b;font:16px/1.55 system-ui,sans-serif}header,main,footer{max-width:960px;margin:auto;padding:1.25rem}header{display:flex;justify-content:space-between;border-bottom:1px solid #c9d2c8}header a{font-weight:800;color:#18302b;text-decoration:none}header span,.eyebrow,small{color:#60756e}.hero{padding:4rem 0 2rem}.hero h1{font:clamp(2.5rem,7vw,5.4rem)/.95 Georgia,serif;max-width:850px;margin:.4rem 0}.hero>p:last-child{font-size:1.2rem;max-width:700px}.search{margin:1rem 0 3rem}.search-controls{display:grid;grid-template-columns:1fr 180px;gap:.5rem}.search input,.search select{width:100%;font:inherit;padding:.8rem;border:1px solid #93a39d;background:white;border-radius:3px}.towns,.directory{list-style:none;padding:0;display:grid;gap:.6rem}.towns{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}.towns li,.directory li{background:white;border:1px solid #dbe1da;padding:.8rem 1rem}.towns li{display:flex;justify-content:space-between}.towns a,.directory a{color:#075f50;font-weight:700}.directory li{display:flex;justify-content:space-between;gap:1rem}.directory span{color:#60756e;text-align:right}.downloads{margin:2rem 0}.notice{margin:3rem 0;padding:1rem 1.5rem;border-left:5px solid #d68b35;background:#fff8e9}.crumb{font-size:.9rem}.status{display:inline-block;background:#d9f2df;color:#155b2c;padding:.4rem .7rem;border-radius:99px;font-weight:800}.status small{color:#39754a;font-weight:500}.status.closed{background:#eee4db;color:#75401e}.status.closed small{color:#805d46}.status.unknown{background:#fff0bd;color:#694f00}.status.unknown small{color:#806b27}dl{display:grid;grid-template-columns:180px 1fr;max-width:700px}dt,dd{padding:.6rem;border-bottom:1px solid #dbe1da;margin:0}dt{font-weight:700}.source,footer{font-size:.9rem;color:#60756e}footer{border-top:1px solid #c9d2c8;margin-top:4rem}@media(max-width:600px){.search-controls{grid-template-columns:1fr}.directory li{display:block}.directory span{display:block;text-align:left}dl{grid-template-columns:1fr}dd{padding-top:0}.hero{padding-top:2rem}}''', encoding="utf-8")

print(json.dumps({"businesses": len(rows), "municipalities": len(towns), "site_pages": len(rows) + len(towns) + 2, "collapsed_active_ids": active_collapsed, "collapsed_inactive_ids": inactive_collapsed, "reconciled_to_active": active_reconciled, "manual_reconciliations": manual_reconciled, "liquor_conflicts_unknown": liquor_conflicts}))
