#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Formats a flat_sniffer.py --events-out JSON file as a GitHub issue body (Markdown).

Declares the same dependency as flat_sniffer.py (via `uv run format_issue.py`)
since importing it transitively imports httpx.
"""

import json
import sys

from flat_sniffer import EVENT_TAGS, format_event


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "events.json"
    with open(path, encoding="utf-8") as f:
        events = json.load(f)
    print(f"**{len(events)} change(s) detected** on swietegomichala.pl\n")
    for e in events:
        tag = EVENT_TAGS.get(e["event"], e["event"])
        print(f"- **[{tag}]** {format_event(e)}")


if __name__ == "__main__":
    main()
