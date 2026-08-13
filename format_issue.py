#!/usr/bin/env python3
"""Formats a flat_sniffer.py --events-out JSON file as a GitHub issue body (Markdown)."""
import json
import sys

LABELS = {
    "status_change": "STATUS",
    "price_change": "PRICE",
    "new_listing": "NEW",
    "removed_from_listing": "GONE",
}


def format_event(e: dict) -> str:
    tag = LABELS.get(e["event"], e["event"])
    if e["event"] == "status_change":
        return f"- **[{tag}]** {e['category']} {e['unit']}: {e['old_status']} -> {e['new_status']} ({e['url']})"
    if e["event"] == "price_change":
        return f"- **[{tag}]** {e['category']} {e['unit']}: {e['old_price']} -> {e['new_price']} ({e['url']})"
    if e["event"] == "new_listing":
        return f"- **[{tag}]** {e['category']} {e['unit']}: {e['status']} @ {e['price']} ({e['url']})"
    if e["event"] == "removed_from_listing":
        return f"- **[{tag}]** {e['category']} {e['unit']}: was {e['last_status']} @ {e['price']} - {e['note']} ({e['url']})"
    return f"- {json.dumps(e, ensure_ascii=False)}"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "events.json"
    with open(path, encoding="utf-8") as f:
        events = json.load(f)
    print(f"**{len(events)} change(s) detected** on swietegomichala.pl\n")
    for e in events:
        print(format_event(e))


if __name__ == "__main__":
    main()
