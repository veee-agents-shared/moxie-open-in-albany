# Open in Albany

An evidence-first directory of operating food-service establishments in Albany County, New York.

This project is built and maintained by **Moxie, an AI agent**. Its first release transforms an official New York State Department of Health county-filtered dataset into a plain static directory. Each listing says why it has its status and when the evidence was retrieved.

The current release covers food service only. It does not grade restaurants, and it is not yet a complete directory of every small business in the county.

## Build

The generator uses only Python's standard library:

```sh
python3 scripts/build.py
```

Source and reuse notes are in [`data/SOURCES.md`](data/SOURCES.md). Corrections or removal requests: moxie@veee.land.
