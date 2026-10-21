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
- NYSDOH active historical inspections (`2hcc-shji`) and inactive inspections (`aaxz-j6pj`) for evidence history and closure matching.
- Overture Maps, Foursquare Open Source Places, and OpenStreetMap for broader category coverage after their current licenses and attribution requirements are recorded.
