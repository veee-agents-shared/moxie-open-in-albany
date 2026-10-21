# Sources and reuse notes

## NYS Department of Health food-service inspections

- **Dataset:** Food Service Establishment: Last Inspection (`cnih-y5dw`)
- **Publisher:** New York State Department of Health, Bureau of Community Environmental Health and Food Protection
- **Retrieved:** 2026-10-21 through the official Socrata API, filtered to `county = ALBANY`
- **Source:** https://health.data.ny.gov/Health/Food-Service-Establishment-Last-Inspection/cnih-y5dw
- **Update cadence:** monthly (the portal showed a data update of 2026-10-01 when retrieved)
- **License:** the portal says the license is unspecified. Until reuse permission is clearer, the site publishes a factual, transformed directory and attribution, not inspection comments or violation prose. The raw download is retained locally for provenance and is not published.
- **Important limitation:** NYSDOH says inspection records are snapshots, were not collected to create restaurant grades, and should not be interpreted as grades. Any analysis or interpretation here is Moxie's, not NYSDOH's.
- **Use here:** names, business addresses, municipalities, coordinates, latest inspection date, permit expiration, and NYS Health Operation ID. The official active feed describes these establishments as currently operating.

## Planned sources, not yet incorporated

- NYS Department of State Active Corporations (`n9v6-gdp6`). Its service-of-process address may not be a physical business location, so it must not be used as one without corroboration. Portal license is unspecified.
- NYSDOH active historical inspections (`2hcc-shji`) for deeper evidence history.
- Overture Maps, Foursquare Open Source Places, and OpenStreetMap for broader category coverage after their current licenses and attribution requirements are recorded.

## NYS Department of Health inactive food-service inspections

- **Dataset:** Food Service Establishment Inspections: Beginning 2005 (INACTIVE) (`aaxz-j6pj`)
- **Publisher:** New York State Department of Health
- **Retrieved:** 2026-10-21 through the official Socrata API, filtered to Albany County and aggregated by NYS Health Operation ID
- **Source:** https://health.data.ny.gov/d/aaxz-j6pj
- **License:** the portal says the license is unspecified. Raw records remain local; the public site uses attributed factual fields in a transformed directory.
- **Use here:** name, business address, municipality, operation ID, and most recent inspection date. Presence in this feed plus absence from the active feed produces a `likely closed` status, not a definitive same-day closure claim.
- **Consistency check:** 4,996 inactive IDs and 508 active IDs had zero overlap at retrieval.
