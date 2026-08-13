# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A scraper that monitors flat / parking / storage / garage listing availability on
`swietegomichala.pl` (a Polish real-estate developer's site), diffs the results
against a local JSON registry, and reports status/price changes. Runs weekly via
GitHub Actions, which also commits the updated registry back to this repo and
opens a GitHub issue when something changes.

## Commands

This is a single-file Python tool using [uv](https://docs.astral.sh/uv/) with
PEP 723 inline script metadata (dependency: `httpx`) — no `pyproject.toml`,
no manual venv setup. `uv run` resolves and caches the dependency automatically.

```bash
uv run flat_sniffer.py                              # fetch, diff, print changes, save
uv run flat_sniffer.py --quiet                       # only print if something changed (used by CI)
uv run flat_sniffer.py --json                        # also print the full diff as JSON
uv run flat_sniffer.py --events-out events.json       # write the diff to a JSON file (used by CI)
uv run format_issue.py events.json                    # render an events.json file as a GitHub issue body
```

There is no test suite, linter, or type checker configured in this repo.

## Architecture

**`flat_sniffer.py`** does everything: fetch, parse, diff, persist.

- `fetch()` / `fetch_all()` — hits `wyszukiwarka-mieszkan` (the site's server-rendered
  search page) once per listing category (`CATEGORIES`: Mieszkanie/flat, Hala
  garażowa/garage, Komórka/storage, Miejsce postojowe/parking) with `limit=500`,
  which is high enough to get every listing for that category in one request —
  no pagination needed. This search page was chosen deliberately over the site's
  "3D viewer" (`wyszukiwarka-3d`), which requires walking every floor/building
  combination through an internal `ajaxGet` endpoint for the same data.
- `parse_offers()` extracts each listing via a handful of module-level regexes
  (`HEAD_RE`, `STATUS_RE`, `PRICE_RE`, etc.) matched against `<a class="target-row">`
  blocks — there's no HTML parser involved, so **if the site's markup changes,
  these regexes are the first thing to check** (they're commented with the exact
  markup shape they expect).
- **`registry.json`** is the persisted state: a dict keyed by the site's own
  `data-id`, one entry per listing (status, price, area, floor/extras, etc.).
  It's a *tracked, committed* file — local runs and the CI workflow both read
  and overwrite it directly, so don't restructure its schema without updating
  both `diff_registries()` and `format_event()`.
- `diff_registries(old, new)` compares two registry snapshots and produces
  `new_listing` / `removed_from_listing` / `status_change` / `price_change`
  events. A listing disappearing from the search results is reported as
  `removed_from_listing` with a "likely sold/withdrawn" note — the tool has no
  way to distinguish a real sale from a site glitch, which is why the next
  point exists.
- `sanity_check(old, new)` is a safety gate that runs *before* anything is
  diffed or saved: if an entire category that previously had listings comes
  back empty (site blocked the scraper, markup broke parsing, maintenance
  page), the whole run aborts (`sys.exit(1)`) without touching
  `registry.json`/`history.log`. This exists specifically to stop a degraded
  scrape from being misread as a mass sell-off and permanently corrupting the
  baseline — don't bypass it without preserving that guarantee.
- `format_event()` / `EVENT_TAGS` render a single event as text and are shared
  between `print_report()` (console) and `format_issue.py` (GitHub issue
  Markdown) — keep them shared rather than reintroducing a second copy.
- `history.log` is an append-only JSONL audit log of every event ever detected
  (not written on the very first run, which only establishes the baseline).

**`.github/workflows/flat-sniffer.yml`** runs weekly (Mon 08:00 UTC) or on
manual dispatch: run the script → if `events.json` is non-empty, open a GitHub
issue via `format_issue.py` → commit `registry.json`/`history.log` back to the
repo → on any step failure, open a separate "check failed" issue instead of
failing silently. A `concurrency` group prevents overlapping scheduled/manual
runs from racing on the git push.
