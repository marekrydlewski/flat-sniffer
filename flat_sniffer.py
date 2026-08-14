#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""
Monitors flat / parking / storage / garage availability on
https://swietegomichala.pl (Konimpex-Invest "Swietego Michala" investment).

Uses the site's own search page (wyszukiwarka-mieszkan), which renders full
listings (status, price, unit number...) server-side per category.

Usage (via uv, auto-installs deps from the inline script metadata above):
    uv run flat_sniffer.py            # fetch, diff against registry.json, print changes, save
    uv run flat_sniffer.py --json     # also print the full diff as JSON
    uv run flat_sniffer.py --quiet    # only print if there are changes
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "https://swietegomichala.pl/pl/wyszukiwarka-mieszkan"
CATEGORIES = {
    1: "Mieszkanie",
    4: "Hala garazowa",
    5: "Komorka",
    6: "Miejsce postojowe",
}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = SCRIPT_DIR / "registry.json"
HISTORY_PATH = SCRIPT_DIR / "history.log"

# Matches: class="... border-<color> " href="<url>" data-id="<id>" data-pdf="<crm-url>"
HEAD_RE = re.compile(
    r'class="[^"]*border-(?P<color>[a-z]+)\s*"\s*'
    r'href="(?P<href>[^"]+)"\s*'
    r'data-id="(?P<id>\d+)"\s*'
    r'data-pdf="(?P<pdf>[^"]*)"',
    re.DOTALL,
)

# Matches: <status text> </div> <category></div> <unit></div>
STATUS_RE = re.compile(
    r'text-uppercase">\s*(?P<status>[^<]+?)\s*</div>\s*'
    r'<div class="h4 fs-20 m-0 text-dark">(?P<category>[^<]+)</div>\s*'
    r'<div class="h4 fs-20 text-primary">(?P<unit>[^<]+)</div>',
    re.DOTALL,
)

PRICE_RE = re.compile(r'<h4 class="mb-0 text-black">([^<]+)</h4>')
PRICE_M2_RE = re.compile(r'<div class="fs-16 mb-1">([^<]+)</div>')
AREA_RE = re.compile(r"Powierzchnia\s*</div>\s*<div[^>]*>\s*([\d,]+)\s*m<sup>2</sup>", re.DOTALL)
ROOMS_RE = re.compile(r"Pokoje\s*</div>\s*<div[^>]*>\s*(\d+)\s*</div>", re.DOTALL)
DODATKOWE_RE = re.compile(r"Dodatkowe\s*</div>\s*(?P<body>.*?)</div>\s*</div>\s*</div>", re.DOTALL)
EXTRA_ITEM_RE = re.compile(r'<div class="h4 fs-20 m-0 text-dark">\s*([^<]+?)\s*</div>')

# Fields that may legitimately be absent from a listing chunk (unlike HEAD_RE/STATUS_RE,
# whose absence means the chunk failed to parse) - each just needs its stripped match
# group or None.
OPTIONAL_FIELD_RES = {
    "price": PRICE_RE,
    "price_per_m2": PRICE_M2_RE,
    "area_m2": AREA_RE,
    "rooms": ROOMS_RE,
}


FETCH_ATTEMPTS = 3


def fetch(id_typ: int) -> str:
    url = f"{BASE_URL}?sort=0&limit=500&id_typ=&id_typ={id_typ}"
    last_exc = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < FETCH_ATTEMPTS - 1:
                time.sleep(2**attempt)
    raise RuntimeError(
        f"failed to fetch id_typ={id_typ} ({url}) after {FETCH_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def _opt_group(m: re.Match | None, group: int = 1) -> str | None:
    """Returns the stripped match group, or None if the regex didn't match."""
    return m.group(group).strip() if m else None


def _norm(s: str) -> str:
    """Strips and Unicode-NFC-normalizes a string so a cosmetic re-rendering
    difference (e.g. a different composition of a diacritic) between two runs
    can't masquerade as the value having actually changed."""
    return unicodedata.normalize("NFC", s.strip())


def parse_offers(html: str) -> tuple[list[dict], int]:
    """Returns (parsed offers, number of listing chunks that failed to parse)."""
    chunks = re.split(r'(?=<a class="target-row)', html)
    offers = []
    failed = 0
    for chunk in chunks:
        if not chunk.startswith('<a class="target-row'):
            continue
        head = HEAD_RE.search(chunk)
        status = STATUS_RE.search(chunk)
        if not head or not status:
            failed += 1
            continue

        extras = []
        dodatkowe_m = DODATKOWE_RE.search(chunk)
        if dodatkowe_m:
            extras = [e.strip() for e in EXTRA_ITEM_RE.findall(dodatkowe_m.group("body"))]

        offers.append(
            {
                "id": head.group("id"),
                "url": head.group("href"),
                "crm_url": head.group("pdf") or None,
                "status": _norm(status.group("status")),
                "status_color": head.group("color"),
                "category": _norm(status.group("category")),
                "unit": _norm(status.group("unit")),
                **{key: _opt_group(regex.search(chunk)) for key, regex in OPTIONAL_FIELD_RES.items()},
                "extras": extras,
            }
        )
    return offers, failed


PARSE_FAILURE_RATIO = 0.1  # abort if >=10% of a category's listing chunks fail to parse


def fetch_all() -> tuple[dict[str, dict], list[str]]:
    registry = {}
    problems = []
    for id_typ, label in CATEGORIES.items():
        html = fetch(id_typ)
        offers, failed = parse_offers(html)
        total_chunks = len(offers) + failed
        if total_chunks == 0:
            # Every category has always had listings; zero chunks found at all - not
            # just zero parsed - means the page is blocked/empty/restructured, not
            # that the category genuinely has nothing for sale. Catches this even on
            # the very first run, when sanity_check() has no baseline to compare to.
            problems.append(
                f"category '{label}': found 0 listings at all - looks like the page "
                f"is blocked, empty, or completely restructured, not real sales"
            )
        elif failed:
            ratio = failed / total_chunks
            print(
                f"WARNING: category '{label}': {failed}/{total_chunks} listing(s) failed to parse (regex mismatch)",
                file=sys.stderr,
            )
            if ratio >= PARSE_FAILURE_RATIO:
                problems.append(
                    f"category '{label}': {failed}/{total_chunks} listings failed to "
                    f"parse ({ratio:.0%}) - looks like a markup change, not real sales"
                )
        if len(offers) >= 500:
            print(
                f"WARNING: category '{label}' returned {len(offers)} offers (possible truncation at limit=500)",
                file=sys.stderr,
            )
        for o in offers:
            registry[o["id"]] = o
    return registry, problems


REQUIRED_OFFER_KEYS = {"category", "unit", "status", "url"}


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"{REGISTRY_PATH} is corrupted ({e}); refusing to continue without a trustworthy baseline"
            ) from e
    for oid, o in data.items():
        if not isinstance(o, dict) or not REQUIRED_OFFER_KEYS.issubset(o):
            raise RuntimeError(
                f"{REGISTRY_PATH} entry '{oid}' is missing required fields "
                f"({REQUIRED_OFFER_KEYS}); refusing to continue without a trustworthy baseline"
            )
    return data


def save_registry(registry: dict) -> None:
    tmp_path = REGISTRY_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(REGISTRY_PATH)


def append_history(events: list[dict]) -> None:
    HISTORY_PATH.touch(exist_ok=True)
    if not events:
        return
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


SANITY_MIN_ABSOLUTE_DROP = 3  # ignore small categories where a real bulk sale could hit this
SANITY_MIN_RATIO_DROP = 0.5  # and require the drop to be at least this severe, relatively


def sanity_check(old: dict, new: dict) -> list[str]:
    """Returns a list of anomaly descriptions if `new` looks like a broken/blocked
    scrape rather than real data: a category whose listing count collapses (not just
    hits zero) between runs - almost always a site/markup/blocking problem, not a
    sudden wave of real sales."""
    if not old:
        return []
    old_counts = Counter(o["category"] for o in old.values())
    new_counts = Counter(o["category"] for o in new.values())
    problems = []
    for category in sorted(old_counts):
        old_n = old_counts[category]
        new_n = new_counts.get(category, 0)
        dropped = old_n - new_n
        if dropped >= SANITY_MIN_ABSOLUTE_DROP and new_n <= old_n * SANITY_MIN_RATIO_DROP:
            problems.append(
                f"category '{category}': had {old_n} listings, now has {new_n} - "
                f"looks like a scrape failure (blocked, markup change, maintenance "
                f"page), not real sales"
            )
    return problems


def diff_registries(old: dict, new: dict) -> list[dict]:
    now = datetime.now(UTC).isoformat()
    events = []

    old_ids = set(old.keys())
    new_ids = set(new.keys())

    for oid in sorted(new_ids - old_ids, key=int):
        o = new[oid]
        events.append(
            {
                "ts": now,
                "event": "new_listing",
                "id": oid,
                "category": o["category"],
                "unit": o["unit"],
                "status": o["status"],
                "price": o.get("price"),
                "url": o["url"],
            }
        )

    for oid in sorted(old_ids - new_ids, key=int):
        o = old[oid]
        events.append(
            {
                "ts": now,
                "event": "removed_from_listing",
                "id": oid,
                "category": o["category"],
                "unit": o["unit"],
                "last_status": o["status"],
                "price": o.get("price"),
                "url": o["url"],
                "note": "no longer in search results - likely sold/withdrawn",
            }
        )

    for oid in sorted(old_ids & new_ids, key=int):
        o_old, o_new = old[oid], new[oid]
        if o_old["status"] != o_new["status"]:
            events.append(
                {
                    "ts": now,
                    "event": "status_change",
                    "id": oid,
                    "category": o_new["category"],
                    "unit": o_new["unit"],
                    "old_status": o_old["status"],
                    "new_status": o_new["status"],
                    "price": o_new["price"],
                    "url": o_new["url"],
                }
            )
        if o_old.get("price") != o_new.get("price"):
            events.append(
                {
                    "ts": now,
                    "event": "price_change",
                    "id": oid,
                    "category": o_new["category"],
                    "unit": o_new["unit"],
                    "old_price": o_old.get("price"),
                    "new_price": o_new.get("price"),
                    "url": o_new["url"],
                }
            )

    return events


EVENT_TAGS = {
    "status_change": "STATUS",
    "price_change": "PRICE",
    "new_listing": "NEW",
    "removed_from_listing": "GONE",
}


def _fmt_price(p) -> str:
    return p if p is not None else "price unavailable"


_EVENT_FORMATTERS = {
    "status_change": lambda e: f"{e['category']} {e['unit']}: {e['old_status']} -> {e['new_status']} ({e['url']})",
    "price_change": lambda e: (
        f"{e['category']} {e['unit']}: {_fmt_price(e['old_price'])} -> {_fmt_price(e['new_price'])} ({e['url']})"
    ),
    "new_listing": lambda e: f"{e['category']} {e['unit']}: {e['status']} @ {_fmt_price(e['price'])} ({e['url']})",
    "removed_from_listing": lambda e: (
        f"{e['category']} {e['unit']}: was {e['last_status']} @ {_fmt_price(e['price'])} - {e['note']} ({e['url']})"
    ),
}


def format_event(e: dict) -> str:
    """Renders a single diff event as a plain-text line. Shared between the console
    report (print_report, below) and format_issue.py so the two outputs can't drift."""
    formatter = _EVENT_FORMATTERS.get(e["event"])
    return formatter(e) if formatter else json.dumps(e, ensure_ascii=False)


def print_report(events: list[dict], new_registry: dict, first_run: bool) -> None:
    counts_by_cat = Counter((o["category"], o["status"]) for o in new_registry.values())

    print(f"=== flat-sniffer :: {datetime.now(UTC).isoformat()} ===")
    print(f"Total listings tracked: {len(new_registry)}")
    for (cat, status), n in sorted(counts_by_cat.items()):
        print(f"  {cat:<20} {status:<15} {n}")

    if first_run:
        print("\nFirst run - baseline saved, nothing to compare against yet.")
        return

    if not events:
        print("\nNo changes since last run.")
        return

    print(f"\n{len(events)} change(s) since last run:")
    for e in events:
        tag = EVENT_TAGS.get(e["event"], e["event"])
        print(f"  [{tag}] {format_event(e)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="also print the diff as JSON")
    parser.add_argument("--quiet", action="store_true", help="only print output if something changed")
    parser.add_argument(
        "--events-out",
        metavar="PATH",
        help="write the change-events list as JSON to PATH (for CI consumption)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "persist the scrape even if an anomaly is detected - the recovery path for a "
            "category that has genuinely gone to 0 (discontinued) or collapsed for real, "
            "once you've manually verified it's not a scrape failure"
        ),
    )
    args = parser.parse_args()

    old_registry = load_registry()
    first_run = not old_registry

    new_registry, parse_problems = fetch_all()

    problems = parse_problems + sanity_check(old_registry, new_registry)
    if problems and not args.force:
        for p in problems:
            print(f"ANOMALY: {p}", file=sys.stderr)
        print(
            "Aborting without touching registry.json/history.log - refusing to "
            "treat a suspicious scrape as ground truth. If you've verified this is "
            "real (not a scrape failure), re-run with --force.",
            file=sys.stderr,
        )
        sys.exit(1)
    elif problems:
        for p in problems:
            print(f"ANOMALY (proceeding anyway, --force given): {p}", file=sys.stderr)

    events = [] if first_run else diff_registries(old_registry, new_registry)

    if not args.quiet or events or first_run:
        print_report(events, new_registry, first_run)

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))

    if args.events_out:
        with open(args.events_out, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

    save_registry(new_registry)
    append_history(events)


if __name__ == "__main__":
    main()
