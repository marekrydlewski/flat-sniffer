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
from datetime import datetime, timezone
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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
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
    re.S,
)

# Matches: <status text> </div> <category></div> <unit></div>
STATUS_RE = re.compile(
    r'text-uppercase">\s*(?P<status>[^<]+?)\s*</div>\s*'
    r'<div class="h4 fs-20 m-0 text-dark">(?P<category>[^<]+)</div>\s*'
    r'<div class="h4 fs-20 text-primary">(?P<unit>[^<]+)</div>',
    re.S,
)

PRICE_RE = re.compile(r'<h4 class="mb-0 text-black">([^<]+)</h4>')
PRICE_M2_RE = re.compile(r'<div class="fs-16 mb-1">([^<]+)</div>')
AREA_RE = re.compile(r'Powierzchnia\s*</div>\s*<div[^>]*>\s*([\d,]+)\s*m<sup>2</sup>', re.S)
ROOMS_RE = re.compile(r'Pokoje\s*</div>\s*<div[^>]*>\s*(\d+)\s*</div>', re.S)
DODATKOWE_RE = re.compile(
    r'Dodatkowe\s*</div>\s*(?P<body>.*?)</div>\s*</div>\s*</div>', re.S
)
EXTRA_ITEM_RE = re.compile(r'<div class="h4 fs-20 m-0 text-dark">\s*([^<]+?)\s*</div>')


def fetch(id_typ: int) -> str:
    url = f"{BASE_URL}?sort=0&limit=500&id_typ=&id_typ={id_typ}"
    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        raise RuntimeError(f"failed to fetch id_typ={id_typ} ({url}): {e}") from e


def parse_offers(html: str) -> list[dict]:
    chunks = re.split(r'(?=<a class="target-row)', html)
    offers = []
    for chunk in chunks:
        if not chunk.startswith('<a class="target-row'):
            continue
        head = HEAD_RE.search(chunk)
        status = STATUS_RE.search(chunk)
        if not head or not status:
            continue

        price_m = PRICE_RE.search(chunk)
        price_m2_m = PRICE_M2_RE.search(chunk)
        area_m = AREA_RE.search(chunk)
        rooms_m = ROOMS_RE.search(chunk)

        extras = []
        dodatkowe_m = DODATKOWE_RE.search(chunk)
        if dodatkowe_m:
            extras = [e.strip() for e in EXTRA_ITEM_RE.findall(dodatkowe_m.group("body"))]

        offers.append(
            {
                "id": head.group("id"),
                "url": head.group("href"),
                "crm_url": head.group("pdf") or None,
                "status": status.group("status").strip(),
                "status_color": head.group("color"),
                "category": status.group("category").strip(),
                "unit": status.group("unit").strip(),
                "price": price_m.group(1).strip() if price_m else None,
                "price_per_m2": price_m2_m.group(1).strip() if price_m2_m else None,
                "area_m2": area_m.group(1).strip() if area_m else None,
                "rooms": rooms_m.group(1).strip() if rooms_m else None,
                "extras": extras,
            }
        )
    return offers


def fetch_all() -> dict[str, dict]:
    registry = {}
    for id_typ, label in CATEGORIES.items():
        html = fetch(id_typ)
        offers = parse_offers(html)
        if len(offers) >= 500:
            print(f"WARNING: category '{label}' returned {len(offers)} offers "
                  f"(possible truncation at limit=500)", file=sys.stderr)
        for o in offers:
            registry[o["id"]] = o
    return registry


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"{REGISTRY_PATH} is corrupted ({e}); refusing to continue without a trustworthy baseline"
            ) from e


def save_registry(registry: dict) -> None:
    with REGISTRY_PATH.open("w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2, sort_keys=True)


def append_history(events: list[dict]) -> None:
    HISTORY_PATH.touch(exist_ok=True)
    if not events:
        return
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def sanity_check(old: dict, new: dict) -> list[str]:
    """Returns a list of anomaly descriptions if `new` looks like a broken/blocked
    scrape rather than real data, e.g. a category that had listings before and now
    has none - almost always a site/markup/blocking problem, not real sales."""
    if not old:
        return []
    old_categories = {o["category"] for o in old.values()}
    new_categories = {o["category"] for o in new.values()}
    return [
        f"category '{c}' had listings before, now has 0 - looks like a scrape "
        f"failure (blocked, markup change, maintenance page), not real sales"
        for c in sorted(old_categories - new_categories)
    ]


def diff_registries(old: dict, new: dict) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    events = []

    old_ids = set(old.keys())
    new_ids = set(new.keys())

    for oid in sorted(new_ids - old_ids, key=lambda x: int(x)):
        o = new[oid]
        events.append({
            "ts": now, "event": "new_listing", "id": oid,
            "category": o["category"], "unit": o["unit"],
            "status": o["status"], "price": o.get("price"), "url": o["url"],
        })

    for oid in sorted(old_ids - new_ids, key=lambda x: int(x)):
        o = old[oid]
        events.append({
            "ts": now, "event": "removed_from_listing", "id": oid,
            "category": o["category"], "unit": o["unit"],
            "last_status": o["status"], "price": o.get("price"), "url": o["url"],
            "note": "no longer in search results - likely sold/withdrawn",
        })

    for oid in sorted(old_ids & new_ids, key=lambda x: int(x)):
        o_old, o_new = old[oid], new[oid]
        if o_old["status"] != o_new["status"]:
            events.append({
                "ts": now, "event": "status_change", "id": oid,
                "category": o_new["category"], "unit": o_new["unit"],
                "old_status": o_old["status"], "new_status": o_new["status"],
                "price": o_new["price"], "url": o_new["url"],
            })
        if o_old.get("price") != o_new.get("price"):
            events.append({
                "ts": now, "event": "price_change", "id": oid,
                "category": o_new["category"], "unit": o_new["unit"],
                "old_price": o_old.get("price"), "new_price": o_new.get("price"),
                "url": o_new["url"],
            })

    return events


EVENT_TAGS = {
    "status_change": "STATUS",
    "price_change": "PRICE",
    "new_listing": "NEW",
    "removed_from_listing": "GONE",
}


def _fmt_price(p) -> str:
    return p if p is not None else "price unavailable"


def format_event(e: dict) -> str:
    """Renders a single diff event as a plain-text line. Shared between the console
    report (print_report, below) and format_issue.py so the two outputs can't drift."""
    if e["event"] == "status_change":
        return f"{e['category']} {e['unit']}: {e['old_status']} -> {e['new_status']} ({e['url']})"
    if e["event"] == "price_change":
        return f"{e['category']} {e['unit']}: {_fmt_price(e['old_price'])} -> {_fmt_price(e['new_price'])} ({e['url']})"
    if e["event"] == "new_listing":
        return f"{e['category']} {e['unit']}: {e['status']} @ {_fmt_price(e['price'])} ({e['url']})"
    if e["event"] == "removed_from_listing":
        return f"{e['category']} {e['unit']}: was {e['last_status']} @ {_fmt_price(e['price'])} - {e['note']} ({e['url']})"
    return json.dumps(e, ensure_ascii=False)


def print_report(events: list[dict], new_registry: dict, first_run: bool) -> None:
    counts_by_cat = {}
    for o in new_registry.values():
        key = (o["category"], o["status"])
        counts_by_cat[key] = counts_by_cat.get(key, 0) + 1

    print(f"=== flat-sniffer :: {datetime.now(timezone.utc).isoformat()} ===")
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
    parser.add_argument("--events-out", metavar="PATH", help="write the change-events list as JSON to PATH (for CI consumption)")
    args = parser.parse_args()

    old_registry = load_registry()
    first_run = not old_registry

    new_registry = fetch_all()

    problems = sanity_check(old_registry, new_registry)
    if problems:
        for p in problems:
            print(f"ANOMALY: {p}", file=sys.stderr)
        print(
            "Aborting without touching registry.json/history.log - refusing to "
            "treat a suspicious scrape as ground truth.",
            file=sys.stderr,
        )
        sys.exit(1)

    events = [] if first_run else diff_registries(old_registry, new_registry)

    if not (args.quiet and not events and not first_run):
        print_report(events, new_registry, first_run)

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))

    if args.events_out:
        with open(args.events_out, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

    append_history(events)
    save_registry(new_registry)


if __name__ == "__main__":
    main()
