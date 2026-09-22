#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Price history projection for flats and parking spaces.

Projects immutable events from history.log into per-unit price time series,
computing numeric deltas (PLN, %, PLN/m2), tracking price changes over time,
and distinguishing real price adjustments from reservation masking.

Usage:
    uv run price_history.py              # summarize all price adjustments
    uv run price_history.py 36_6         # inspect history for a specific unit
    uv run price_history.py --json       # dump full per-unit history as JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HISTORY_PATH = SCRIPT_DIR / "history.log"
REGISTRY_PATH = SCRIPT_DIR / "registry.json"


def parse_price_num(price_str: str | None) -> int | None:
    """Extract numeric integer price in PLN from a string (e.g. '610 944 zł' -> 610944)."""
    if not price_str:
        return None
    digits = "".join(ch for ch in str(price_str) if ch.isdigit())
    return int(digits) if digits else None


def parse_area_num(area_str: str | None) -> float | None:
    """Extract numeric area in m2 from a string (e.g. '39,57' -> 39.57)."""
    if not area_str:
        return None
    cleaned = str(area_str).replace(",", ".").strip()
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def format_price_pln(val: int | None) -> str:
    if val is None:
        return "brak ceny"
    return f"{val:,} zł".replace(",", " ")


def format_amount(val: int | None) -> str:
    if val is None:
        return ""
    return f"{val:,}".replace(",", " ")


@dataclass
class PricePoint:
    date: str  # YYYY-MM-DD
    timestamp: str  # ISO-8601
    price: str | None
    price_num: int | None
    price_per_m2: int | None = None
    status: str | None = None
    event: str = ""


@dataclass
class PriceChange:
    date: str  # YYYY-MM-DD
    timestamp: str
    old_price: str | None
    new_price: str | None
    old_price_num: int | None
    new_price_num: int | None
    delta_amount: int | None
    delta_pct: float | None
    change_type: str  # "adjustment", "masked", "unmasked", "adjustment_after_masked"
    status: str | None = None


@dataclass
class UnitPriceProfile:
    category: str
    unit: str
    url: str = ""
    area_m2: float | None = None
    initial_price: str | None = None
    initial_price_num: int | None = None
    initial_price_per_m2: int | None = None
    current_price: str | None = None
    current_price_num: int | None = None
    current_price_per_m2: int | None = None
    last_known_price: str | None = None
    last_known_price_num: int | None = None
    last_known_price_per_m2: int | None = None
    current_status: str | None = None
    has_price_drop: bool = False
    has_price_rise: bool = False
    total_delta_amount: int | None = None
    total_delta_pct: float | None = None
    price_changes: list[PriceChange] = field(default_factory=list)
    timeline: list[PricePoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def history_tooltip(self) -> str:
        if self.price_changes:
            pts = [
                f"{pt.date}: {pt.price or 'cena ukryta'}"
                for pt in self.timeline
                if pt.event
                in (
                    "new_listing",
                    "price_change_adjustment",
                    "price_change_masked",
                    "price_change_unmasked",
                )
            ]
            return " | ".join(pts)
        if self.initial_price:
            return f"Cena od początku: {self.initial_price}"
        return ""


def load_area_lookup(registry_path: Path = REGISTRY_PATH) -> dict[tuple[str, str], float]:
    """Build a (category, unit) -> area_m2 lookup from registry.json."""
    if not registry_path.exists():
        return {}
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        res = {}
        for offer in registry.values():
            cat = offer.get("category")
            unit = offer.get("unit")
            area = parse_area_num(offer.get("area_m2"))
            if cat and unit and area:
                res[(cat, unit)] = area
        return res
    except (json.JSONDecodeError, OSError):
        return {}


def build_price_history(
    history_events: list[dict],
    area_lookup: dict[tuple[str, str], float] | None = None,
) -> dict[tuple[str, str], UnitPriceProfile]:
    """Project history events into per-(category, unit) price profiles."""
    if area_lookup is None:
        area_lookup = {}

    profiles: dict[tuple[str, str], UnitPriceProfile] = {}

    # Sort chronologically just in case events are slightly out of order
    sorted_events = sorted(history_events, key=lambda e: e.get("ts", ""))

    for e in sorted_events:
        cat = e.get("category")
        unit = e.get("unit")
        if not cat or not unit:
            continue

        key = (cat, unit)
        ts = e.get("ts", "")
        dt = ts[:10] if len(ts) >= 10 else ""
        event_name = e.get("event", "")

        if key not in profiles:
            area = area_lookup.get(key)
            profiles[key] = UnitPriceProfile(
                category=cat,
                unit=unit,
                url=e.get("url", ""),
                area_m2=area,
            )

        p = profiles[key]
        if e.get("url") and not p.url:
            p.url = e["url"]

        if event_name == "new_listing":
            price_raw = e.get("price")
            price_num = parse_price_num(price_raw)
            status = e.get("status")

            p.initial_price = price_raw
            p.initial_price_num = price_num
            p.current_price = price_raw
            p.current_price_num = price_num
            p.last_known_price = price_raw
            p.last_known_price_num = price_num
            p.current_status = status

            ppm2 = round(price_num / p.area_m2) if price_num and p.area_m2 else None
            p.initial_price_per_m2 = ppm2
            p.current_price_per_m2 = ppm2
            p.last_known_price_per_m2 = ppm2

            p.timeline.append(
                PricePoint(
                    date=dt,
                    timestamp=ts,
                    price=price_raw,
                    price_num=price_num,
                    price_per_m2=ppm2,
                    status=status,
                    event="new_listing",
                )
            )

        elif event_name == "price_change":
            old_raw = e.get("old_price")
            new_raw = e.get("new_price")
            old_num = parse_price_num(old_raw)
            new_num = parse_price_num(new_raw)

            # Establish initial price baseline if new_listing was somehow missing
            if p.initial_price_num is None and old_num is not None:
                p.initial_price = old_raw
                p.initial_price_num = old_num
                if p.area_m2:
                    p.initial_price_per_m2 = round(old_num / p.area_m2)

            change_type = "adjustment"
            delta_amount: int | None = None
            delta_pct: float | None = None

            if old_num is not None and new_num is not None:
                # Real price adjustment
                delta_amount = new_num - old_num
                delta_pct = round((delta_amount / old_num) * 100, 2) if old_num > 0 else None
                change_type = "adjustment"
                p.current_price = new_raw
                p.current_price_num = new_num
                p.last_known_price = new_raw
                p.last_known_price_num = new_num

            elif old_num is not None and new_num is None:
                # Price hidden / masked (e.g. reservation)
                change_type = "masked"
                p.current_price = None
                p.current_price_num = None
                # Keep last_known_price intact!

            elif old_num is None and new_num is not None:
                # Price unmasked (e.g. reservation released)
                if p.last_known_price_num is not None and new_num != p.last_known_price_num:
                    delta_amount = new_num - p.last_known_price_num
                    delta_pct = (
                        round((delta_amount / p.last_known_price_num) * 100, 2) if p.last_known_price_num > 0 else None
                    )
                    change_type = "adjustment_after_masked"
                else:
                    change_type = "unmasked"

                p.current_price = new_raw
                p.current_price_num = new_num
                p.last_known_price = new_raw
                p.last_known_price_num = new_num

            ppm2 = round(new_num / p.area_m2) if new_num and p.area_m2 else None
            if ppm2 is not None:
                p.current_price_per_m2 = ppm2
                p.last_known_price_per_m2 = ppm2
            elif new_num is None:
                p.current_price_per_m2 = None

            p.price_changes.append(
                PriceChange(
                    date=dt,
                    timestamp=ts,
                    old_price=old_raw,
                    new_price=new_raw,
                    old_price_num=old_num,
                    new_price_num=new_num,
                    delta_amount=delta_amount,
                    delta_pct=delta_pct,
                    change_type=change_type,
                    status=p.current_status,
                )
            )

            p.timeline.append(
                PricePoint(
                    date=dt,
                    timestamp=ts,
                    price=new_raw,
                    price_num=new_num,
                    price_per_m2=ppm2,
                    status=p.current_status,
                    event=f"price_change_{change_type}",
                )
            )

        elif event_name == "status_change":
            new_status = e.get("new_status")
            p.current_status = new_status
            if e.get("price"):
                p.current_price = e["price"]
                p.current_price_num = parse_price_num(e["price"])
                p.last_known_price = e["price"]
                p.last_known_price_num = p.current_price_num
            p.timeline.append(
                PricePoint(
                    date=dt,
                    timestamp=ts,
                    price=p.current_price,
                    price_num=p.current_price_num,
                    price_per_m2=p.current_price_per_m2,
                    status=new_status,
                    event="status_change",
                )
            )

        elif event_name == "removed_from_listing":
            p.current_status = "Usunięte / Sprzedane"
            p.timeline.append(
                PricePoint(
                    date=dt,
                    timestamp=ts,
                    price=e.get("price") or p.last_known_price,
                    price_num=parse_price_num(e.get("price")) or p.last_known_price_num,
                    price_per_m2=p.last_known_price_per_m2,
                    status="Usunięte / Sprzedane",
                    event="removed_from_listing",
                )
            )

    # Compute overall delta and flags
    for p in profiles.values():
        eval_price_num = p.current_price_num if p.current_price_num is not None else p.last_known_price_num
        if eval_price_num is not None and p.initial_price_num is not None:
            total_delta = eval_price_num - p.initial_price_num
            p.total_delta_amount = total_delta
            if p.initial_price_num > 0:
                p.total_delta_pct = round((total_delta / p.initial_price_num) * 100, 2)
            p.has_price_drop = total_delta < 0
            p.has_price_rise = total_delta > 0

    return profiles


def load_history(history_path: Path = HISTORY_PATH) -> list[dict]:
    if not history_path.exists():
        return []
    events = []
    with history_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def print_unit_history(profile: UnitPriceProfile) -> None:
    print(f"=== {profile.category} {profile.unit} ===")
    if profile.area_m2:
        print(f"Powierzchnia: {profile.area_m2} m²")
    if profile.url:
        print(f"URL: {profile.url}")
    print(f"Status: {profile.current_status or 'nieznany'}")
    print(f"Cena początkowa: {profile.initial_price or 'brak'} ({profile.initial_price_per_m2 or '—'} zł/m²)")
    print(f"Cena bieżąca:    {profile.current_price or 'ukryta'}")
    if profile.last_known_price != profile.current_price:
        print(f"Ostatnia znana:  {profile.last_known_price or 'brak'} ({profile.last_known_price_per_m2 or '—'} zł/m²)")

    if profile.total_delta_amount is not None and profile.total_delta_amount != 0:
        sign = "+" if profile.total_delta_amount > 0 else ""
        pct_sign = "+" if (profile.total_delta_pct or 0) > 0 else ""
        amt_str = format_amount(profile.total_delta_amount)
        print(f"Łączna zmiana:   {sign}{amt_str} zł ({pct_sign}{profile.total_delta_pct:.2f}%)")

    real_changes = [c for c in profile.price_changes if c.change_type in ("adjustment", "adjustment_after_masked")]
    if real_changes:
        print("\nKorekty cen przez dewelopera:")
        for c in real_changes:
            sign = "+" if (c.delta_amount or 0) > 0 else ""
            pct_sign = "+" if (c.delta_pct or 0) > 0 else ""
            c_amt_str = format_amount(c.delta_amount)
            print(f"  [{c.date}] {c.old_price} -> {c.new_price} ({sign}{c_amt_str} zł, {pct_sign}{c.delta_pct:.2f}%)")

    print("\nPełna oś zdarzeń:")
    for pt in profile.timeline:
        price_str = pt.price if pt.price else "(cena ukryta)"
        ppm2_str = f" [{pt.price_per_m2} zł/m²]" if pt.price_per_m2 else ""
        status_str = f" | {pt.status}" if pt.status else ""
        print(f"  {pt.date} :: {pt.event:<22} :: {price_str}{ppm2_str}{status_str}")


def print_summary(profiles: dict[tuple[str, str], UnitPriceProfile]) -> None:
    drops = [p for p in profiles.values() if p.has_price_drop]
    rises = [p for p in profiles.values() if p.has_price_rise]

    print("=== flat-sniffer :: Raport zmian cen ===")
    print(f"Śledzonych lokali/miejsc: {len(profiles)}")
    print(f"Obniżki cen: {len(drops)}")
    print(f"Podwyżki cen: {len(rises)}")

    if drops:
        print("\n--- Obniżki cen ---")
        drops.sort(key=lambda p: p.total_delta_amount or 0)
        for p in drops:
            sign = "" if (p.total_delta_amount or 0) < 0 else "+"
            pct_str = f"{p.total_delta_pct:+.2f}%" if p.total_delta_pct is not None else ""
            delta_str = f"{sign}{format_amount(p.total_delta_amount)} zł"
            area_str = f"{p.area_m2} m²" if p.area_m2 else "—"
            ppm2_str = f"{p.current_price_per_m2 or p.last_known_price_per_m2 or '—'} zł/m²"
            print(
                f"  {p.category:<16} {p.unit:<8} : {p.initial_price} -> {p.current_price or p.last_known_price} "
                f"({delta_str}, {pct_str}) | {area_str} | {ppm2_str}"
            )

    if rises:
        print("\n--- Podwyżki cen ---")
        for p in rises:
            pct_str = f"{p.total_delta_pct:+.2f}%" if p.total_delta_pct is not None else ""
            delta_str = f"+{format_amount(p.total_delta_amount)} zł"
            print(
                f"  {p.category:<16} {p.unit:<8} : {p.initial_price} -> {p.current_price or p.last_known_price} "
                f"({delta_str}, {pct_str})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Price history projection for flats and parking places")
    parser.add_argument("unit", nargs="?", help="Specific unit identifier to inspect (e.g. 36_6, 38_1)")
    parser.add_argument("--history", default=str(HISTORY_PATH), help="Path to history.log")
    parser.add_argument("--registry", default=str(REGISTRY_PATH), help="Path to registry.json")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    history = load_history(Path(args.history))
    area_lookup = load_area_lookup(Path(args.registry))
    profiles = build_price_history(history, area_lookup)

    if args.json:
        # Convert tuple keys to string "category:unit" for valid JSON
        serialized = {f"{k[0]}:{k[1]}": v.to_dict() for k, v in profiles.items()}
        print(json.dumps(serialized, ensure_ascii=False, indent=2))
        return

    if args.unit:
        target = args.unit.strip().lower()
        matched = [p for p in profiles.values() if p.unit.lower() == target or target in p.unit.lower()]
        if not matched:
            print(f"Nie znaleziono lokalu o numerze '{args.unit}'.", file=sys.stderr)
            sys.exit(1)
        for p in matched:
            print_unit_history(p)
            print()
    else:
        print_summary(profiles)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
