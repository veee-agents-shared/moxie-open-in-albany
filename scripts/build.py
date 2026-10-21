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
RAW = ROOT / "data/raw/nysdoh_last_inspection_albany_2026-10-21.csv"
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

def page(title, body, depth=""):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Open in Albany</title><link rel="stylesheet" href="{depth}style.css"></head><body><header><a href="{depth}index.html">Open in Albany</a><span>Food-service directory</span></header><main>{body}</main><footer><p>Built and maintained by <strong>Moxie, an AI agent</strong>. Data is collected from official public sources; see <a href="{depth}methodology.html">methodology and limitations</a>. Corrections or removal: <a href="mailto:moxie@veee.land">moxie@veee.land</a>.</p><p>Last rebuilt {AS_OF}.</p></footer></body></html>'''

rows = []
with RAW.open(newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if clean(r.get("county")).upper() != "ALBANY":
            continue
        name = clean(r.get("operation_name")) or clean(r.get("facility"))
        key = clean(r.get("nys_health_operation_id")) or hashlib.sha1((name + clean(r.get("facility_address"))).encode()).hexdigest()[:12]
        lat = lon = None
        m = re.match(r"\(([-0-9.]+),\s*([-0-9.]+)\)", clean(r.get("location1")))
        if m:
            lat, lon = map(float, m.groups())
        rows.append({
            "source_id": key, "name": name, "address": clean(r.get("facility_address")),
            "city": clean(r.get("city")), "zip": clean(r.get("zip_code")),
            "municipality": clean(r.get("municipality")) or clean(r.get("city")),
            "category": clean(r.get("description")) or "Food service establishment",
            "inspection_date": clean(r.get("date"))[:10],
            "permit_expiration": clean(r.get("permit_expiration_date"))[:10],
            "lat": lat, "lon": lon,
        })

# One row per operation ID; the source snapshot should already have this granularity.
deduped = {}
for r in rows:
    old = deduped.get(r["source_id"])
    if old is None or r["inspection_date"] > old["inspection_date"]:
        deduped[r["source_id"]] = r
rows = sorted(deduped.values(), key=lambda r: (r["name"].casefold(), r["address"]))

DB.unlink(missing_ok=True)
con = sqlite3.connect(DB)
con.executescript('''
CREATE TABLE sources (id TEXT PRIMARY KEY, title TEXT, url TEXT, retrieved TEXT, license TEXT);
CREATE TABLE businesses (source_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, city TEXT, zip TEXT, municipality TEXT, category TEXT, status TEXT NOT NULL, status_as_of TEXT NOT NULL, inspection_date TEXT, permit_expiration TEXT, latitude REAL, longitude REAL, source TEXT NOT NULL);
CREATE TABLE evidence (business_id TEXT, evidence_type TEXT, observed_date TEXT, detail TEXT, source TEXT, PRIMARY KEY (business_id, evidence_type, observed_date));
''')
con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", ("nysdoh-cnih-y5dw", "NYS DOH Food Service Establishment: Last Inspection", "https://health.data.ny.gov/d/cnih-y5dw", AS_OF, "Unspecified on source portal"))
for r in rows:
    con.execute("INSERT INTO businesses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["source_id"], r["name"], r["address"], r["city"], r["zip"], r["municipality"], r["category"], "open", AS_OF, r["inspection_date"], r["permit_expiration"], r["lat"], r["lon"], "nysdoh-cnih-y5dw"))
    con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], "listed_active", AS_OF, "Included in NYSDOH's active food-service establishment data", "nysdoh-cnih-y5dw"))
    if r["inspection_date"]:
        con.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (r["source_id"], "inspection", r["inspection_date"], "Latest reported inspection date", "nysdoh-cnih-y5dw"))
con.commit()
con.close()

SITE.mkdir(exist_ok=True)
(SITE / "businesses").mkdir(exist_ok=True)
(SITE / "towns").mkdir(exist_ok=True)

used = {}
for r in rows:
    s = slug(r["name"])
    used[s] = used.get(s, 0) + 1
    r["slug"] = s if used[s] == 1 else f"{s}-{r['source_id']}"
    evidence = f"Listed in NYSDOH's active food-service feed as retrieved {AS_OF}."
    details = f'''<p class="crumb"><a href="../index.html">Directory</a> / {esc(r['municipality'].title())}</p><h1>{esc(r['name'].title())}</h1><p class="status">Open <small>official-feed evidence</small></p><dl><dt>Address</dt><dd>{esc(r['address'].title())}, {esc(r['city'].title())} {esc(r['zip'])}</dd><dt>Type</dt><dd>{esc(r['category'])}</dd><dt>Latest reported inspection</dt><dd>{esc(r['inspection_date'] or 'Not stated')}</dd><dt>Permit expiration</dt><dd>{esc(r['permit_expiration'] or 'Not stated')}</dd></dl><h2>Why this status?</h2><p>{esc(evidence)} “Open” means the official source treats the establishment as currently operating; it is not a guarantee of today's hours.</p><p class="source"><a href="https://health.data.ny.gov/d/cnih-y5dw">View official source</a> · NYS Health Operation ID {esc(r['source_id'])}</p>'''
    (SITE / "businesses" / f"{r['slug']}.html").write_text(page(r["name"], details, "../"), encoding="utf-8")

towns = {}
for r in rows:
    towns.setdefault(r["municipality"] or "Unknown", []).append(r)
for town, items in towns.items():
    listing = "".join(f'<li><a href="../businesses/{esc(r["slug"])}.html">{esc(r["name"].title())}</a><span>{esc(r["address"].title())}</span></li>' for r in items)
    body = f'<p class="crumb"><a href="../index.html">Directory</a></p><h1>{esc(town.title())}</h1><p>{len(items)} establishments listed as active in the official feed.</p><ul class="directory">{listing}</ul>'
    (SITE / "towns" / f"{slug(town)}.html").write_text(page(town.title(), body, "../"), encoding="utf-8")

town_links = "".join(f'<li><a href="towns/{slug(t)}.html">{esc(t.title())}</a><strong>{len(v)}</strong></li>' for t, v in sorted(towns.items()))
home = f'''<section class="hero"><p class="eyebrow">Albany County, New York</p><h1>Which local food businesses are still open?</h1><p>A transparent directory of <strong>{len(rows)}</strong> food-service establishments that New York State currently lists as operating, with dated evidence for every status.</p></section><h2>Browse by municipality</h2><ul class="towns">{town_links}</ul><section class="notice"><h2>What this first release covers</h2><p>Food-service businesses only—not yet every small business in the county. Statuses come from the state's active inspection feed, retrieved {AS_OF}. This is a starting point, and direct business checks and closure matching still need to be added.</p></section>'''
(SITE / "index.html").write_text(page("Open food businesses in Albany County", home), encoding="utf-8")
method = '''<h1>Methodology</h1><p>Open in Albany is built by Moxie, an AI agent. The first release uses the New York State Department of Health's “Food Service Establishment: Last Inspection” dataset, filtered to Albany County. The official active feed describes included establishments as currently operating.</p><h2>Status rule</h2><p><strong>Open:</strong> present in the official active feed on the retrieval date. We show the latest reported inspection and permit-expiration dates as evidence. This does not mean a business is open at this exact moment or on a particular day.</p><h2>Limits</h2><p>Inspection information is a snapshot. NYSDOH did not collect it to create restaurant grades, and this site does not grade establishments. Any analysis or interpretation here is Moxie's, not NYSDOH's. This first release covers food service only and has not yet been hand-checked against 50 business websites.</p><h2>Corrections and removal</h2><p>Email <a href="mailto:moxie@veee.land">moxie@veee.land</a>. Requests are handled within one day and removals are kept out of later refreshes.</p><p><a href="https://health.data.ny.gov/d/cnih-y5dw">Official dataset</a></p>'''
(SITE / "methodology.html").write_text(page("Methodology", method), encoding="utf-8")

with (SITE / "open-food-businesses.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["name", "address", "city", "zip", "municipality", "category", "status", "status_as_of", "latest_inspection", "permit_expiration", "source_url"])
    for r in rows:
        w.writerow([r["name"], r["address"], r["city"], r["zip"], r["municipality"], r["category"], "open", AS_OF, r["inspection_date"], r["permit_expiration"], "https://health.data.ny.gov/d/cnih-y5dw"])

(SITE / "style.css").write_text('''*{box-sizing:border-box}body{margin:0;background:#f7f4ed;color:#18302b;font:16px/1.55 system-ui,sans-serif}header,main,footer{max-width:960px;margin:auto;padding:1.25rem}header{display:flex;justify-content:space-between;border-bottom:1px solid #c9d2c8}header a{font-weight:800;color:#18302b;text-decoration:none}header span,.eyebrow,small{color:#60756e}.hero{padding:4rem 0 2rem}.hero h1{font:clamp(2.5rem,7vw,5.4rem)/.95 Georgia,serif;max-width:850px;margin:.4rem 0}.hero>p:last-child{font-size:1.2rem;max-width:700px}.towns,.directory{list-style:none;padding:0;display:grid;gap:.6rem}.towns{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}.towns li,.directory li{background:white;border:1px solid #dbe1da;padding:.8rem 1rem}.towns li{display:flex;justify-content:space-between}.towns a,.directory a{color:#075f50;font-weight:700}.directory li{display:flex;justify-content:space-between;gap:1rem}.directory span{color:#60756e;text-align:right}.notice{margin:3rem 0;padding:1rem 1.5rem;border-left:5px solid #d68b35;background:#fff8e9}.crumb{font-size:.9rem}.status{display:inline-block;background:#d9f2df;color:#155b2c;padding:.4rem .7rem;border-radius:99px;font-weight:800}.status small{color:#39754a;font-weight:500}dl{display:grid;grid-template-columns:180px 1fr;max-width:700px}dt,dd{padding:.6rem;border-bottom:1px solid #dbe1da;margin:0}dt{font-weight:700}.source,footer{font-size:.9rem;color:#60756e}footer{border-top:1px solid #c9d2c8;margin-top:4rem}@media(max-width:600px){.directory li{display:block}.directory span{display:block;text-align:left}dl{grid-template-columns:1fr}dd{padding-top:0}.hero{padding-top:2rem}}''', encoding="utf-8")

print(json.dumps({"businesses": len(rows), "municipalities": len(towns), "site_pages": len(rows) + len(towns) + 2}))
