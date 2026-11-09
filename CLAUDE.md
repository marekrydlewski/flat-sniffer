# CLAUDE.md

Essential project context and engineering standards for Claude and AI coding agents working on `flat-sniffer`.
For autonomous execution workflows (worktree protocol, subagent code reviews, browser testing, PR creation), refer to [`AGENTS.md`](AGENTS.md).

## Overview

A scraper and dashboard that monitors real-estate availability and pricing on `swietegomichala.pl`, diffs against local JSON registries, and compiles an interactive single-page dashboard.
Architecture details: [`docs/architecture.md`](docs/architecture.md).

## Essential Commands

The project uses [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just).

```bash
# Quality & testing
just check        # Runs ruff check, ruff format --check, ty check, and unittests
just test         # Runs Python test suite only
just fmt          # Ruff autoformat
just typecheck    # Type checking with ty

# Execution & compilation
just dashboard    # Rebuilds flat-dashboard.html
uv run flat_sniffer.py     # Scrapes active listings, updates registry.json
uv run scan_sold.py        # Probes numbering gaps for sold listings
uv run price_history.py    # Summarizes price adjustments

# Worktree management
just wt-new <name>         # Create isolated worktree from origin/main
just wt-clean              # Prune metadata for deleted worktrees
```

## Repository Structure

- `flat_sniffer.py` — Core scraping, regex parsing, anomaly safety checks, diff engine.
- `render_dashboard.py` — Dashboard builder assembling self-contained HTML.
- `templates/` — Dashboard assets (`dashboard.html`, `styles.css`, `app.js`).
- `price_history.py` — Price projection time series and delta calculations.
- `scan_sold.py` — Probes numbering gaps for sold items omitted from search.
- `registry.json` / `sold_registry.json` — Tracked listing registries.
- `history.log` — Append-only JSONL audit log of all detected changes.
- `docs/` — Deep-dive architectural documentation.

## Agent Guidelines & Engineering Standards

1. **Lean Comments**: Keep comments minimal and focused on *why* (non-obvious rationale, edge cases) rather than *what*. Avoid noisy or restated comments.
2. **Do Not Over-Engineer**: Prefer simple, idiomatic Python code and standard library primitives. Keep dependencies minimal (`httpx` only).
3. **Stand-Alone Executability**: Python scripts should declare PEP 723 inline metadata (`# /// script`) where applicable so they remain runnable via `uv run script.py`.
4. **Data Integrity & Invariants**:
   - Never change the schema of `registry.json` or `sold_registry.json` without updating diffing, formatting, and dashboard rendering.
   - Writes to registries must remain atomic (write to temporary file then rename).
   - Never commit corrupt baseline data; preserve safety gates and anomaly detection.
5. **Dashboard Architecture**:
   - Maintain static dashboard assets in `templates/` (`styles.css`, `app.js`, `dashboard.html`).
   - The compiled dashboard must remain a **100% self-contained single HTML file** with inlined styles and scripts.
   - Avoid inline `style="..."` attributes in HTML; use centralized CSS utility classes.
6. **Code Quality**: Always ensure `just check` passes cleanly before concluding changes.
