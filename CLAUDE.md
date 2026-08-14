# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A scraper that monitors flat / parking / storage / garage listing availability on
`swietegomichala.pl` (a Polish real-estate developer's site), diffs the results
against a local JSON registry, and reports status/price changes. Runs weekly via
GitHub Actions, which also commits the updated registry back to this repo and
opens a GitHub issue when something changes.

## Commands

`flat_sniffer.py` / `format_issue.py` are self-contained scripts using
[uv](https://docs.astral.sh/uv/) with PEP 723 inline script metadata
(dependency: `httpx`) — `uv run` resolves and caches that dependency
automatically, standalone, regardless of the project setup below.

```bash
uv run flat_sniffer.py                              # fetch, diff, print changes, save
uv run flat_sniffer.py --quiet                       # only print if something changed (used by CI)
uv run flat_sniffer.py --json                        # also print the full diff as JSON
uv run flat_sniffer.py --events-out events.json       # write the diff to a JSON file (used by CI)
uv run format_issue.py events.json                    # render an events.json file as a GitHub issue body
```

`pyproject.toml` exists for dev tooling (`ruff`, `ty` via uv dependency-groups),
not for running the scripts. There is no test suite. Lint/format/typecheck via
`just`:

```bash
just lint        # ruff check
just fmt         # ruff format
just fmt-check   # ruff format --check
just typecheck   # ty check
just check       # all of the above
```

## Architecture

**`flat_sniffer.py`** does everything: fetch, parse, diff, persist.

- `fetch()` / `fetch_all()` — hits `wyszukiwarka-mieszkan` (the site's server-rendered
  search page) once per listing category (`CATEGORIES`: Mieszkanie/flat, Hala
  garażowa/garage, Komórka/storage, Miejsce postojowe/parking) with `limit=500`.
  That's comfortably above current listing counts (low hundreds at most), but it's
  not a hard guarantee — `fetch_all()` prints a stderr WARNING if a category ever
  hits the 500 cap, since the code doesn't actually implement pagination past that
  point. `fetch()` retries transient HTTP failures 3x with backoff before giving up.
  This search page was chosen deliberately over the site's "3D viewer"
  (`wyszukiwarka-3d`), which requires walking every floor/building combination
  through an internal `ajaxGet` endpoint for the same data.
- `parse_offers()` extracts each listing via a handful of module-level regexes
  (`HEAD_RE`, `STATUS_RE`, `PRICE_RE`, etc.) matched against `<a class="target-row">`
  blocks — there's no HTML parser involved, so **if the site's markup changes,
  these regexes are the first thing to check**. It also counts how many chunks
  failed to match and returns that count alongside the parsed offers; `fetch_all()`
  turns that into a stderr WARNING and, above `PARSE_FAILURE_RATIO` (10%) or when a
  category returns *zero* chunks at all (parsed or failed — the strongest signal
  something's blocked/broken, since every category has always had listings), an
  aborting anomaly in its own right, independent of `sanity_check()` below — this is
  what catches a fully-blocked scrape even on the very first run, when there's no
  prior baseline for `sanity_check()` to compare against. Category names are
  Unicode-NFC-normalized at parse time so cosmetic re-rendering differences can't
  masquerade as a category disappearing.
- **`registry.json`** is the persisted state: a dict keyed by the site's own
  `data-id`, one entry per listing (status, price, area, floor/extras, etc.).
  It's a *tracked, committed* file — local runs and the CI workflow both read
  and overwrite it directly, so don't restructure its schema without updating
  both `diff_registries()` and `format_event()`. `load_registry()` validates JSON
  syntax and that every entry has `REQUIRED_OFFER_KEYS` (`category`/`unit`/`status`/
  `url` — deliberately not `price`, which is allowed to be missing/`None`) before
  trusting it as a baseline; `save_registry()` writes atomically (temp file + rename).
- `diff_registries(old, new)` compares two registry snapshots and produces
  `new_listing` / `removed_from_listing` / `status_change` / `price_change`
  events. A listing disappearing from the search results is reported as
  `removed_from_listing` with a "likely sold/withdrawn" note — the tool has no
  way to distinguish a real sale from a site glitch, which is why the next
  point exists.
- `sanity_check(old, new)` is a safety gate that runs *before* anything is
  diffed or saved: if any category's listing count collapses between runs — a
  drop of at least 3 listings *and* down to 50% or less of the old count
  (`SANITY_MIN_ABSOLUTE_DROP` / `SANITY_MIN_RATIO_DROP`; this also covers a
  category going fully to zero) — the whole run aborts (`sys.exit(1)`) without
  touching `registry.json`/`history.log`. Combined with `fetch_all()`'s
  parse-failure/zero-chunks checks above, this exists to stop a degraded scrape
  (partial or total) from being misread as a mass sell-off and permanently
  corrupting the baseline — don't bypass it without preserving that guarantee.
- `format_event()` / `EVENT_TAGS` render a single event as text and are shared
  between `print_report()` (console) and `format_issue.py` (GitHub issue
  Markdown) — keep them shared rather than reintroducing a second copy.
- `history.log` is an append-only JSONL audit log of every event ever detected
  (not written on the very first run, which only establishes the baseline).
  `main()` writes `registry.json` before appending to `history.log`, so a crash
  between the two leaves an audit-log gap rather than a stale registry that would
  cause the next run to re-report and duplicate already-seen events.

**`.github/workflows/flat-sniffer.yml`** runs weekly (Mon 08:00 UTC) or on
manual dispatch, with a 10-minute job timeout: run the script → commit
`registry.json`/`history.log` back to the repo → if `events.json` is non-empty,
open a GitHub issue via `format_issue.py` → on failure *or cancellation* (the
"Notify on failure" step uses `if: failure() || cancelled()`, since GitHub
Actions does NOT set `failure()` true for a job killed by `timeout-minutes` —
only `cancelled()` catches that), open a separate "check failed" issue instead
of failing silently. If `events.json` still has content at that point (e.g. the
commit succeeded but issue-creation itself failed), the failure issue renders
and includes that diff too, so a real detected change can't be silently lost
just because the *notification* step failed after the *persistence* step
succeeded. The commit happens *before* the issue is opened specifically so a
failed commit can't leave an issue posted without the state it describes
actually being persisted. A `concurrency` group prevents overlapping
scheduled/manual runs from racing on the git push.
