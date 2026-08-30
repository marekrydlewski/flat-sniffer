# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Find publicly accessible offers marked ``Sprzedane`` but omitted from search."""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx

from flat_sniffer import USER_AGENT

STATUS_RE = re.compile(r'text-(?:success|danger|warning)[^"]*text-uppercase">\s*([^<]+?)\s*<', re.DOTALL)
TITLE_RE = re.compile(r"<h2[^>]*>(?P<title>.*?)</h2>", re.DOTALL)
PRICE_RE = re.compile(r'<h4 class="mb-0 text-black">([^<]+)</h4>')
TRAILING_NUMBER_RE = re.compile(r"^(?P<stem>.*?)(?P<number>\d+)$")


def candidates(registry: dict) -> set[str]:
    """Generate gaps in known numbered offer series, never probing outside them."""
    by_stem: dict[tuple[str, str], list[str]] = {}
    for offer in registry.values():
        match = TRAILING_NUMBER_RE.match(offer["url"])
        if not match:
            continue
        key = (offer["category"], match.group("stem"))
        by_stem.setdefault(key, []).append(match.group("number"))

    result = set()
    for (_, stem), raw_numbers in by_stem.items():
        known = {int(number) for number in raw_numbers}
        padded = any(number.startswith("0") for number in raw_numbers)
        width = max(map(len, raw_numbers))
        for number in range(min(known), max(known) + 1):
            if number not in known:
                suffix = f"{number:0{width}d}" if padded else str(number)
                result.add(f"{stem}{suffix}")
    return result


def fetch_sold(url: str) -> dict | None:
    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    status = STATUS_RE.search(response.text)
    title = TITLE_RE.search(response.text)
    if not status or not title or status.group(1).strip().casefold() != "sprzedane":
        return None
    title_parts = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\s{2,}", title.group("title").strip())]
    if len(title_parts) < 2:
        return None
    price = PRICE_RE.search(response.text)
    return {
        "category": title_parts[0],
        "unit": title_parts[-1],
        "status": "Sprzedane",
        "price": price.group(1).strip() if price else None,
        "url": url,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--out", default="sold_registry.json")
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    previous_path = Path(args.out)
    previous = (
        {offer["url"]: offer for offer in json.loads(previous_path.read_text(encoding="utf-8"))}
        if previous_path.exists()
        else {}
    )
    found = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_sold, url) for url in candidates(registry)]
        for future in as_completed(futures):
            if offer := future.result():
                offer["detected_at"] = previous.get(offer["url"], {}).get(
                    "detected_at", datetime.now(UTC).isoformat()
                )
                found.append(offer)
    found.sort(key=lambda o: (o["category"], o["unit"]))
    Path(args.out).write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Found {len(found)} sold offer(s).")


if __name__ == "__main__":
    main()
