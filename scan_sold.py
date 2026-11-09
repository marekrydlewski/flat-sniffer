# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Find publicly accessible offers marked ``Sprzedane`` but omitted from search."""

import argparse
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx

from flat_sniffer import USER_AGENT, fetch_offer_price

STATUS_RE = re.compile(r'text-(?:success|danger|warning)[^"]*text-uppercase">\s*([^<]+?)\s*<', re.DOTALL)
TITLE_RE = re.compile(r"<h2[^>]*>(?P<title>.*?)</h2>", re.DOTALL)
PRICE_RE = re.compile(r'<h4 class="mb-0 text-black">([^<]+)</h4>')
ID_RE = re.compile(r'offersPrices\?id=(?P<id>\d+)|data-id="(?P<data_id>\d+)"')
TRAILING_NUMBER_RE = re.compile(r"^(?P<stem>.*?)(?P<number>\d+)$")
AREA_RE = re.compile(r"Powierzchnia</td>\s*<th[^>]*>\s*([\d,]+)\s*m<sup>2</sup>", re.DOTALL)
ROOMS_RE = re.compile(r"Pokoje</td>\s*<th[^>]*>\s*(\d+)", re.DOTALL)
FLOOR_RE = re.compile(r"piętro\s*(-?\d+|parter)", re.DOTALL | re.IGNORECASE)
STAIRCASE_RE = re.compile(r"Klatka\s*(\d+)", re.DOTALL | re.IGNORECASE)


def candidates(registry: dict, previous: dict | None = None) -> set[str]:
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
    if previous:
        result.update(previous.keys())
    result.difference_update(offer["url"] for offer in registry.values())
    return result


def fetch_sold(
    url: str,
    client: httpx.Client | None = None,
    previous_price: str | None = None,
) -> dict | None:
    try:
        if client is not None:
            response = client.get(url, timeout=20, follow_redirects=True)
        else:
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
    price_match = PRICE_RE.search(response.text)
    price = price_match.group(1).strip() if price_match else (previous_price or None)
    price_per_m2 = None

    id_match = ID_RE.search(response.text)
    if id_match and (not price or not price_per_m2):
        offer_id = id_match.group("id") or id_match.group("data_id")
        fetched_p, fetched_pm2 = fetch_offer_price(offer_id, client)
        if not price and fetched_p:
            price = fetched_p
        if fetched_pm2:
            price_per_m2 = fetched_pm2

    area_match = AREA_RE.search(response.text)
    rooms_match = ROOMS_RE.search(response.text)
    floor_match = FLOOR_RE.search(response.text)
    staircase_match = STAIRCASE_RE.search(response.text)

    res = {
        "category": unicodedata.normalize("NFC", title_parts[0]),
        "unit": unicodedata.normalize("NFC", title_parts[-1]),
        "status": "Sprzedane",
        "price": price,
        "url": url,
    }
    if area_match:
        res["area_m2"] = area_match.group(1).strip()
    if rooms_match:
        res["rooms"] = rooms_match.group(1).strip()
    if floor_match:
        res["floor"] = floor_match.group(1).strip()
    if staircase_match:
        res["staircase"] = staircase_match.group(1).strip()
    if price_per_m2:
        res["price_per_m2"] = price_per_m2
    return res


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
    with (
        httpx.Client(headers={"User-Agent": USER_AGENT}) as client,
        ThreadPoolExecutor(max_workers=8) as executor,
    ):
        futures = [
            executor.submit(fetch_sold, url, client, previous.get(url, {}).get("price"))
            for url in candidates(registry, previous)
        ]
        for future in as_completed(futures):
            if offer := future.result():
                prev_info = previous.get(offer["url"], {})
                offer["detected_at"] = prev_info.get("detected_at", datetime.now(UTC).isoformat())
                for field in ("price", "area_m2", "rooms", "floor", "staircase", "price_per_m2"):
                    if not offer.get(field) and prev_info.get(field):
                        offer[field] = prev_info[field]
                found.append(offer)
    found.sort(key=lambda o: (o["category"], o["unit"]))
    out_path = Path(args.out)
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(out_path)
    print(f"Found {len(found)} sold offer(s).")


if __name__ == "__main__":
    main()
