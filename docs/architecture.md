# Architecture & Design Details

This document captures the detailed architecture, scraping mechanics, anomaly safeguards, persistence format, and automation pipeline of `flat-sniffer`.

---

## 1. Scraping & Parsing Pipeline

The core scraper lives in `flat_sniffer.py`.

### Target & Endpoint
- Target: `https://swietegomichala.pl/pl/wyszukiwarka-mieszkan` (server-rendered search page).
- Categories (`CATEGORIES`):
  - `1`: Mieszkanie (Apartment)
  - `4`: Hala garażowa (Garage hall)
  - `5`: Komórka (Storage unit)
  - `6`: Miejsce postojowe (Parking space)
- Query parameters: `sort=0&limit=500&id_typ=&id_typ={id_typ}`.
- Transient HTTP failures are retried 3 times with exponential backoff.
- Rationale: The search page was selected over the site's 3D viewer (`wyszukiwarka-3d`) to avoid walking individual building/floor combinations via internal `ajaxGet` endpoints.

### Regex Extraction & Normalization
- Listings are parsed from `<a class="target-row">` blocks via regex without external HTML parsing libraries.
- Primary regexes:
  - `HEAD_RE`: Extracts id, href, and status color.
  - `STATUS_RE`: Extracts status, category, and unit identifier.
  - Optional fields: price, price per m², area, rooms, extra details (`DODATKOWE_RE`).
- **Unicode normalization**: All status, category, and unit strings are normalized via `unicodedata.normalize("NFC", ...)` to prevent cosmetic diacritic recomposition from triggering false diffs.

---

## 2. Safety Gates & Anomaly Detection

To prevent scraping failures (e.g. cloudflare blocks, site redesign, network timeouts) from corrupting the tracked baseline, two safeguards exist:

1. **Parse-Failure & Zero-Chunk Threshold**:
   - Every category has historically contained listings. If zero listing chunks are detected for any category, or if >=10% (`PARSE_FAILURE_RATIO`) fail regex parsing, scraping aborts immediately before diffing.
2. **Count Collapse Check (`sanity_check`)**:
   - If any category's count drops between runs by at least 3 listings (`SANITY_MIN_ABSOLUTE_DROP`) *and* falls to 50% or less of the previous count (`SANITY_MIN_RATIO_DROP`), the run aborts with an exit code of `1`.
   - `--force` flag: Allows manual override when a category has legitimately sold out or been restructured.

---

## 3. Persistence Schema & Event Auditing

- **`registry.json`**: Current active state dictionary keyed by `data-id`.
  - Required fields: `category`, `unit`, `status`, `url`.
  - Atomic write strategy: Data is written to a temporary file (`.json.tmp`) and atomically replaced.
- **`sold_registry.json`**: Offers detected as sold via gap scanning (`scan_sold.py`).
- **`history.log`**: Append-only JSON Lines (JSONL) audit log recording all events:
  - `new_listing`
  - `removed_from_listing`
  - `status_change`
  - `price_change`
- **Sequence invariant**: `registry.json` is persisted before appending to `history.log` to guarantee that a crash leaves an audit gap rather than a corrupt baseline that duplicates events on future runs.

---

## 4. Automation & CI Pipeline

GitHub Actions workflow `.github/workflows/flat-sniffer.yml` orchestrates automation:
1. Runs daily/weekly at 08:00 UTC.
2. Executes `flat_sniffer.py --quiet --events-out events.json`.
3. Runs `scan_sold.py --out sold_registry.json`.
4. Commits updated `registry.json`, `history.log`, and `sold_registry.json`.
5. If changes are detected, renders an issue via `format_issue.py` and opens a GitHub issue.
6. Builds the availability dashboard via `render_dashboard.py` and deploys it to GitHub Pages.
7. Failsafe reporting: On job timeout, cancellation, or failure (`if: failure() || cancelled()`), a diagnostic issue is opened including any pending events detected in `events.json`.
