# flat-sniffer

Monitors flat / parking / storage / garage availability on
[swietegomichala.pl](https://swietegomichala.pl/pl/wyszukiwarka-mieszkan) (a
Poznań real-estate investment) and reports status/price changes.

## What it does

Scrapes the site's search page for all four listing categories (flats,
garage spaces, storage units, parking spots), diffs the results against a
local snapshot (`registry.json`), and reports:

- new listings
- listings that disappeared (likely sold/withdrawn)
- status changes (e.g. Wolne → Rezerwacja)
- price changes

## Usage

Requires [uv](https://docs.astral.sh/uv/) — no manual setup needed, it
resolves the one dependency (`httpx`) automatically.

```bash
uv run flat_sniffer.py            # fetch, diff, print changes, save
uv run flat_sniffer.py --quiet    # only print output if something changed
uv run flat_sniffer.py --json     # also print the full diff as JSON
uv run render_dashboard.py         # create flat-dashboard.html from the snapshot
uv run scan_sold.py                # find sold offers omitted from the search page
```

## Automation

A GitHub Actions workflow (`.github/workflows/flat-sniffer.yml`) runs this
daily (08:00 UTC) and on manual trigger. It commits the updated `registry.json`,
`history.log`, and `sold_registry.json` back to the repo, and builds and deploys
the interactive dashboard to GitHub Pages. If a run fails outright (network error,
corrupted state, or a suspicious/blocked scrape), it opens a "check failed"
issue instead of failing silently.

Each successful run also uploads a self-contained **flat-availability-dashboard**
artifact. It opens on a concise overview of availability and includes the current
inventory of flats, garage spaces, storage rooms, and parking places.

## Files

- `flat_sniffer.py` — scraper + diff engine
- `render_dashboard.py` — renders the human-friendly HTML dashboard
- `scan_sold.py` — discovers sold offers in gaps of the public offer-number series
- `registry.json` — current snapshot of all tracked listings
- `history.log` — append-only log of every change ever detected
