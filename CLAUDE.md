# CLAUDE.md

Guidance for Claude and AI coding agents working on `flat-sniffer`.

## Overview

A scraper and dashboard that monitors real-estate availability (flats, parking, storage, garages) on `swietegomichala.pl`, tracks status and price changes against a local JSON registry, and publishes an interactive single-page dashboard.

Detailed technical architecture and safety-gate mechanics are documented in [`docs/architecture.md`](file:///Users/marek/Projects/flat-sniffer/docs/architecture.md).

## Essential Commands

The project uses [uv](https://docs.astral.sh/uv/) for execution and tooling.

```bash
# Core execution
uv run flat_sniffer.py                              # Fetch, diff, print changes, save
uv run flat_sniffer.py --quiet                       # Run quietly (used by CI)
uv run flat_sniffer.py --events-out events.json       # Export diff to JSON
uv run format_issue.py events.json                    # Render diff as GitHub issue markdown
uv run render_dashboard.py                            # Build flat-dashboard.html
uv run scan_sold.py                                  # Scan for sold listings in numbering gaps
uv run price_history.py                              # Summarize price adjustments

# Quality & linting (via justfile)
just check        # Runs ruff check, ruff format --check, and ty check
just lint         # Ruff linter
just fmt          # Ruff autoformat
just typecheck    # Type checking with ty
```

## Repository Structure

- `flat_sniffer.py` — Core scraping, regex parsing, anomaly safety checks, diff engine.
- `render_dashboard.py` — Dashboard builder assembling self-contained HTML.
- `templates/` — Dashboard assets (`dashboard.html`, `styles.css`, `app.js`).
- `price_history.py` — Price projection time series and delta calculations.
- `scan_sold.py` — Probes numbering gaps for sold items omitted from search.
- `format_issue.py` — Formats change diffs for GitHub issues.
- `registry.json` / `sold_registry.json` — Tracked listing registries.
- `history.log` — Append-only JSONL audit log of all detected changes.
- `docs/` — Deep-dive architectural documentation.

## Agent Guidelines & Engineering Standards

1. **Lean Comments**: Keep comments minimal and focused on *why* (non-obvious rationale, edge cases) rather than *what*. Avoid noisy or restated comments.
2. **Do Not Over-Engineer**: Prefer simple, idiomatic Python code and standard library primitives. Keep dependencies minimal (`httpx` only).
3. **Stand-Alone Executability**: Python scripts should declare PEP 723 inline metadata (`# /// script`) where applicable so they remain runnable via `uv run script.py`.
4. **Data Integrity & Invariants**:
   - Never change the schema of `registry.json` without updating diffing, formatting, and dashboard rendering.
   - Writes to `registry.json` must remain atomic (write to temp file then rename).
   - Never commit corrupt baseline data; preserve safety gates and anomaly detection.
5. **Dashboard Architecture**:
   - Maintain static dashboard assets in `templates/` (`styles.css`, `app.js`, `dashboard.html`).
   - The compiled dashboard must remain a **100% self-contained single HTML file** with inlined styles and scripts.
   - Avoid inline `style="..."` attributes in HTML; use centralized CSS utility classes.
6. **Code Quality**: Always ensure `just check` passes cleanly before concluding changes.
