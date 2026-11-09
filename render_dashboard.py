"""Render a self-contained, modern, mobile-friendly real-estate availability dashboard."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flat_sniffer import enrich_offer_metadata
from price_history import build_price_history, format_amount, parse_area_num, parse_price_num

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

GROUPS = {
    "Mieszkania": {"Mieszkanie"},
    "Parkowanie": {"Hala garażowa", "Miejsce postojowe"},
    "Komórki lokatorskie": {"Komórka"},
}


def status_kind(status: str) -> str:
    text = (status or "").casefold()
    if "wolne" in text:
        return "available"
    if "rezerw" in text:
        return "reserved"
    if "sprzed" in text:
        return "sold"
    return "unavailable"


def group_name(category: str) -> str:
    for name, categories in GROUPS.items():
        if category in categories:
            return name
    return category


def plural_events(count: int) -> str:
    if count == 1:
        return "1 zdarzenie"
    if 10 < count % 100 < 15:
        return f"{count} zdarzeń"
    if count % 10 in (2, 3, 4):
        return f"{count} zdarzenia"
    return f"{count} zdarzeń"


def event_badge(event_type: str, status: str = "", is_sold: bool = False) -> tuple[str, str]:
    if event_type == "new_listing":
        is_free = status_kind(status) == "available"
        return ("badge-new", "Nowa oferta" if is_free else "Nowa pozycja")
    if event_type == "status_change":
        return ("badge-status", "Zmiana statusu")
    if event_type == "price_change":
        return ("badge-price", "Zmiana ceny")
    if event_type == "removed_from_listing":
        if is_sold:
            return ("badge-sold", "Sprzedane")
        return ("badge-removed", "Zniknęło z oferty")
    return ("badge-neutral", event_type.replace("_", " ").title())


def event_row_html(
    event: dict,
    sold_keys: set[tuple[str, str]] | None = None,
    sold_urls: set[str] | None = None,
) -> str:
    event_type = event.get("event", "")
    cat = event.get("category", "")
    unit = event.get("unit", "")
    url = event.get("url", "#")

    is_sold = False
    if event_type == "removed_from_listing":
        is_sold = bool(
            (sold_urls and url and url != "#" and url in sold_urls)
            or (sold_keys and (cat, unit) in sold_keys)
            or cat == "Mieszkanie"
        )

    badge_cls, badge_text = event_badge(event_type, event.get("status", ""), is_sold=is_sold)

    if event_type == "status_change":
        old_s = event.get("old_status", "")
        new_s = event.get("new_status", "")
        summary = (
            f'<span class="diff-old">{html.escape(old_s)}</span> '
            f'<span class="diff-arrow">→</span> '
            f'<strong class="diff-new">{html.escape(new_s)}</strong>'
        )
    elif event_type == "price_change":
        old_p = event.get("old_price")
        new_p = event.get("new_price")
        if old_p and new_p:
            old_num = parse_price_num(old_p)
            new_num = parse_price_num(new_p)
            delta_badge = ""
            if old_num and new_num:
                delta = new_num - old_num
                sign = "+" if delta > 0 else ""
                delta_cls = "delta-drop" if delta < 0 else "delta-rise"
                pct = round((delta / old_num) * 100, 1)
                delta_badge = f' <span class="{delta_cls}">{sign}{format_amount(delta)} zł ({sign}{pct}%)</span>'
            summary = (
                f'<span class="diff-old">{html.escape(old_p)}</span> '
                f'<span class="diff-arrow">→</span> '
                f'<strong class="diff-new">{html.escape(new_p)}</strong>{delta_badge}'
            )
        elif old_p and not new_p:
            summary = f'<span class="text-muted">Cena ukryta (ostatnio: {html.escape(old_p)})</span>'
        else:
            summary = '<span class="diff-new">Aktualizacja ceny</span>'
    elif event_type == "removed_from_listing":
        last_st = event.get("last_status")
        last_info = f" (było: {last_st})" if last_st else ""
        if is_sold:
            if last_st and last_st.casefold() != "sprzedane":
                summary = (
                    f'<span class="diff-old">{html.escape(last_st)}</span> '
                    f'<span class="diff-arrow">→</span> '
                    f'<strong class="diff-new text-danger">Sprzedane</strong>'
                )
            else:
                summary = '<strong class="diff-new text-danger">Sprzedane</strong>'
        else:
            summary = f'<span class="text-danger">Usunięto z oferty{html.escape(last_info)}</span>'
    elif event_type == "new_listing":
        st = event.get("status", "Wolne")
        summary = f'<span class="text-green">Pojawiło się w ofercie: {html.escape(st)}</span>'
    else:
        summary = html.escape(str(event.get("note") or event_type))

    link_html = (
        f'<a class="event-link-btn" href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer" title="Zobacz na stronie dewelopera">Karta ↗</a>'
        if url and url != "#"
        else ""
    )

    return f"""<div class="week-event-row" data-cat="{html.escape(cat)}">
      <div class="event-left">
        <span class="event-badge {badge_cls}">{html.escape(badge_text)}</span>
        <strong class="event-unit-name">{html.escape(cat)} {html.escape(unit)}</strong>
        <span class="event-diff">{summary}</span>
      </div>
      <div class="event-right">
        {link_html}
      </div>
    </div>"""


def build_weekly_changes_html(
    history: list[dict],
    weeks_count: int = 12,
    sold_keys: set[tuple[str, str]] | None = None,
    sold_urls: set[str] | None = None,
) -> str:
    """Build clean weekly accordion change log for Block 2."""
    weeks: dict[str, list[dict]] = defaultdict(list)
    for e in history:
        ts = e.get("ts") or e.get("detected_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            pass
        else:
            y, w, _ = dt.isocalendar()
            weeks[f"{y}-W{w:02d}"].append(e)

    sorted_week_keys = sorted(weeks.keys(), reverse=True)
    if not sorted_week_keys:
        return '<div class="empty-state">Brak zarejestrowanych zmian w historii.</div>'

    cards = []
    for idx, w_key in enumerate(sorted_week_keys[:weeks_count]):
        events = weeks[w_key]
        year_str, w_num_str = w_key.split("-W")
        w_year = int(year_str)
        w_num = int(w_num_str)

        first_day_of_year = datetime(w_year, 1, 4, tzinfo=UTC).date()
        monday = first_day_of_year + timedelta(weeks=w_num - 1)
        monday = monday - timedelta(days=monday.weekday())
        sunday = monday + timedelta(days=6)
        dates_label = f"{monday:%d.%m} – {sunday:%d.%m.%Y}"

        flats_events = [e for e in events if e.get("category") == "Mieszkanie"]
        has_flats = len(flats_events) > 0

        flats_sold = sum(1 for e in flats_events if e.get("event") == "removed_from_listing")
        flats_res = sum(
            1
            for e in flats_events
            if e.get("event") == "status_change" and "rezerw" in (e.get("new_status") or "").casefold()
        )
        flats_free = sum(
            1
            for e in flats_events
            if e.get("event") == "status_change" and "wolne" in (e.get("new_status") or "").casefold()
        )
        flats_drops = sum(
            1
            for e in flats_events
            if e.get("event") == "price_change"
            and parse_price_num(e.get("old_price"))
            and parse_price_num(e.get("new_price"))
            and (parse_price_num(e.get("new_price")) or 0) < (parse_price_num(e.get("old_price")) or 0)
        )

        chips = []
        if flats_sold:
            chips.append(f'<span class="week-chip chip-sold">−{flats_sold} sprzedane</span>')
        if flats_res:
            chips.append(f'<span class="week-chip chip-res">+{flats_res} rezerwacja</span>')
        if flats_free:
            chips.append(f'<span class="week-chip chip-free">+{flats_free} powrót do wolnych</span>')
        if flats_drops:
            chips.append(f'<span class="week-chip chip-drop">🔥 {flats_drops} obniżka cen</span>')

        other_count = len(events) - len(flats_events)
        if other_count > 0:
            chips.append(f'<span class="week-chip chip-other">+{other_count} inne lokale</span>')

        if not chips:
            chips.append(f'<span class="week-chip chip-neutral">{len(events)} zmian ogółem</span>')

        open_attr = " open" if idx == 0 else ""
        events_rows_html = "".join(
            event_row_html(e, sold_keys=sold_keys, sold_urls=sold_urls) for e in reversed(events)
        )

        cards.append(
            f"""<details class="week-card"{open_attr} data-week="{w_key}" data-has-flats="{"true" if has_flats else "false"}">
          <summary class="week-summary">
            <div class="week-summary-left">
              <span class="week-badge">T{w_num}</span>
              <div class="week-info">
                <strong class="week-title">Tydzień {w_num} ({w_year})</strong>
                <span class="week-dates">{dates_label}</span>
              </div>
            </div>
            <div class="week-summary-right">
              <div class="week-chips">{"".join(chips)}</div>
              <span class="week-chevron" aria-hidden="true">▾</span>
            </div>
          </summary>
          <div class="week-events-list">
            {events_rows_html}
          </div>
        </details>"""
        )

    return "".join(cards)


def render_template(template: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def normalize_offers(
    registry: dict,
    sold: list[dict],
    history: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize registry and sold listings, decorating with price delta and status metrics."""
    offers = sorted(registry.values(), key=lambda o: (o.get("category", ""), o.get("unit", "")))

    active_keys = {(o.get("category", ""), o.get("unit", "")) for o in offers}
    active_urls = {o.get("url") for o in offers if o.get("url") and o.get("url") != "#"}

    normalized_sold = []
    for item in sold:
        key = (item.get("category", ""), item.get("unit", ""))
        url = item.get("url")
        if key in active_keys or (url and url in active_urls):
            continue
        s = dict(item)
        s["status"] = "Sprzedane"
        s["status_kind"] = "sold"
        s["group"] = group_name(s.get("category", ""))
        enrich_offer_metadata(s)
        normalized_sold.append(s)

    for o in offers:
        o["status_kind"] = status_kind(o.get("status", ""))
        o["group"] = group_name(o.get("category", ""))
        enrich_offer_metadata(o)

    all_offers = offers + normalized_sold

    area_lookup = {
        (o.get("category", ""), o.get("unit", "")): area
        for o in all_offers
        if (area := parse_area_num(o.get("area_m2"))) is not None
    }
    price_profiles = build_price_history(history, area_lookup)

    for o in all_offers:
        key = (o.get("category", ""), o.get("unit", ""))
        p = price_profiles.get(key)
        if p:
            o["has_price_drop"] = p.has_price_drop
            o["has_price_rise"] = p.has_price_rise
            o["total_delta_amount"] = p.total_delta_amount
            o["total_delta_pct"] = p.total_delta_pct
            o["initial_price"] = p.initial_price
            o["last_known_price"] = p.last_known_price
            o["price_per_m2"] = p.current_price_per_m2 or p.last_known_price_per_m2
            o["history_tooltip"] = p.history_tooltip

    return offers, normalized_sold, all_offers


def build_compact_offers_json(all_offers: list[dict]) -> list[dict]:
    return [
        {
            "id": str(o.get("id", "")),
            "cat": o.get("category", ""),
            "group": o.get("group", ""),
            "unit": o.get("unit", ""),
            "status": o.get("status", ""),
            "kind": o.get("status_kind", "unavailable"),
            "price": o.get("price") or "",
            "price_num": parse_price_num(o.get("price")),
            "area": o.get("area_m2") or "",
            "area_num": parse_area_num(o.get("area_m2")),
            "rooms": o.get("rooms") or "",
            "floor": o.get("floor") or "",
            "staircase": o.get("staircase") or "",
            "extras": " · ".join(o.get("extras") or []),
            "url": o.get("url", "#"),
            "crm_url": o.get("crm_url") or "",
            "has_drop": bool(o.get("has_price_drop")),
            "has_rise": bool(o.get("has_price_rise")),
            "delta_amt": o.get("total_delta_amount"),
            "delta_pct": o.get("total_delta_pct"),
            "initial_price": o.get("initial_price") or "",
            "last_known_price": o.get("last_known_price") or "",
            "price_per_m2": o.get("price_per_m2"),
            "history_tooltip": o.get("history_tooltip") or "",
        }
        for o in all_offers
    ]


def build_dashboard_context(
    registry: dict,
    sold: list[dict],
    history: list[dict],
    styles_css: str,
    app_js: str,
) -> dict[str, str]:
    offers, _normalized_sold, all_offers = normalize_offers(registry, sold, history)

    # Flats specific calculations
    flats = [o for o in all_offers if o.get("category") == "Mieszkanie"]
    flats_active = [o for o in offers if o.get("category") == "Mieszkanie"]
    flats_avail = [o for o in flats_active if o.get("status_kind") == "available"]
    flats_res = [o for o in flats_active if o.get("status_kind") == "reserved"]
    flats_sold = [o for o in flats if o.get("status_kind") == "sold"]

    flats_total = len(flats)
    c_flats_avail = len(flats_avail)
    c_flats_res = len(flats_res)
    c_flats_sold = len(flats_sold)

    flats_avail_pct = round((c_flats_avail / flats_total * 100), 1) if flats_total else 0.0
    flats_res_pct = round((c_flats_res / flats_total * 100), 1) if flats_total else 0.0
    flats_sold_pct = round((c_flats_sold / flats_total * 100), 1) if flats_total else 0.0

    # Pricing metrics for available flats
    avail_prices: list[int] = []
    avail_sqm: list[int] = []
    for o in flats_avail:
        p = parse_price_num(o.get("price"))
        a = parse_area_num(o.get("area_m2"))
        if p is not None:
            avail_prices.append(p)
            if a is not None and a > 0:
                avail_sqm.append(round(p / a))

    flats_min_price = f"{min(avail_prices):,}".replace(",", " ") if avail_prices else "0"
    flats_max_price = f"{max(avail_prices):,}".replace(",", " ") if avail_prices else "0"
    flats_avg_price = f"{round(sum(avail_prices) / len(avail_prices)):,}".replace(",", " ") if avail_prices else "0"

    flats_min_sqm = f"{min(avail_sqm):,}".replace(",", " ") if avail_sqm else "0"
    flats_max_sqm = f"{max(avail_sqm):,}".replace(",", " ") if avail_sqm else "0"
    flats_avg_sqm = f"{round(sum(avail_sqm) / len(avail_sqm)):,}".replace(",", " ") if avail_sqm else "0"

    flats_drops = [o for o in flats if o.get("has_price_drop")]
    flats_drops_count = len(flats_drops)
    if flats_drops:
        avg_drop = round(
            sum(abs(o.get("total_delta_pct") or 0) for o in flats_drops) / flats_drops_count,
            1,
        )
        flats_drops_sub = f"średnio -{avg_drop}% względem ceny pierwotnej"
    else:
        flats_drops_sub = "brak obniżek"

    # Rooms count for available flats
    rooms_avail = Counter(str(o.get("rooms") or "").strip() for o in flats_avail)
    rooms_2 = rooms_avail.get("2", 0)
    rooms_3 = rooms_avail.get("3", 0)
    rooms_4 = rooms_avail.get("4", 0)

    # Active offer counts for category tabs
    flats_active_count = len(flats_active)
    garage_active = [o for o in offers if o.get("category") == "Hala garażowa"]
    garage_active_count = len(garage_active)
    storage_active = [o for o in offers if o.get("category") == "Komórka"]
    storage_active_count = len(storage_active)
    parking_active = [o for o in offers if o.get("category") == "Miejsce postojowe"]
    parking_active_count = len(parking_active)

    compact_offers_json = build_compact_offers_json(all_offers)
    sold_urls = {s["url"] for s in sold if isinstance(s.get("url"), str)}
    sold_keys = {
        (s["category"], s["unit"])
        for s in sold
        if isinstance(s.get("category"), str) and isinstance(s.get("unit"), str)
    }
    weekly_changes_html = build_weekly_changes_html(history, sold_keys=sold_keys, sold_urls=sold_urls)

    return {
        "styles": styles_css,
        "app_js": app_js,
        "offers_json": json.dumps(compact_offers_json, ensure_ascii=False, allow_nan=False),
        "generated": datetime.now(UTC).strftime("%d.%m.%Y, %H:%M UTC"),
        "flats_total": str(flats_total),
        "flats_avail": str(c_flats_avail),
        "flats_res": str(c_flats_res),
        "flats_sold": str(c_flats_sold),
        "flats_avail_pct": str(flats_avail_pct),
        "flats_res_pct": str(flats_res_pct),
        "flats_sold_pct": str(flats_sold_pct),
        "flats_min_price": flats_min_price,
        "flats_max_price": flats_max_price,
        "flats_avg_price": flats_avg_price,
        "flats_min_sqm": flats_min_sqm,
        "flats_max_sqm": flats_max_sqm,
        "flats_avg_sqm": flats_avg_sqm,
        "flats_drops_count": str(flats_drops_count),
        "flats_drops_sub": flats_drops_sub,
        "rooms_2": str(rooms_2),
        "rooms_3": str(rooms_3),
        "rooms_4": str(rooms_4),
        "flats_active_count": str(flats_active_count),
        "garage_active_count": str(garage_active_count),
        "storage_active_count": str(storage_active_count),
        "parking_active_count": str(parking_active_count),
        "weekly_changes_html": weekly_changes_html,
    }


def render(registry: dict, sold: list[dict], history: list[dict]) -> str:
    html_template = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    styles_css = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (TEMPLATES_DIR / "app.js").read_text(encoding="utf-8")

    context = build_dashboard_context(
        registry=registry,
        sold=sold,
        history=history,
        styles_css=styles_css,
        app_js=app_js,
    )
    return render_template(html_template, context)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--sold", default="sold_registry.json")
    parser.add_argument("--history", default="history.log")
    parser.add_argument("--out", default="flat-dashboard.html")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    sold_path = Path(args.sold)
    sold = json.loads(sold_path.read_text(encoding="utf-8")) if sold_path.exists() else []
    history_path = Path(args.history)
    history = (
        [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if history_path.exists()
        else []
    )

    out_content = render(registry, sold, history)
    Path(args.out).write_text(out_content, encoding="utf-8")
    print(f"Rendered dashboard successfully to {args.out}")


if __name__ == "__main__":
    main()
