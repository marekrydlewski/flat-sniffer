"""Render a self-contained, modern, mobile-friendly real-estate availability dashboard."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from price_history import build_price_history, format_amount, parse_area_num, parse_price_num

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

GROUPS = {
    "Mieszkania": {"Mieszkanie"},
    "Parkowanie": {"Hala garażowa", "Miejsce postojowe"},
    "Komórki lokatorskie": {"Komórka"},
}
GONE_RE = re.compile(r"\[GONE\]\*\*\s+(Mieszkanie|Hala garażowa|Komórka|Miejsce postojowe)\s")

POLISH_MONTHS = [
    "",
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
]

POLISH_WEEKDAYS = [
    "Poniedziałek",
    "Wtorek",
    "Środa",
    "Czwartek",
    "Piątek",
    "Sobota",
    "Niedziela",
]


def status_kind(status: str) -> str:
    text = (status or "").casefold()
    if "wolne" in text:
        return "available"
    if "rezerw" in text:
        return "reserved"
    if "sprzed" in text:
        return "sold"
    return "unavailable"


def status_label(kind: str) -> str:
    return {
        "available": "Wolne",
        "reserved": "Rezerwacja",
        "sold": "Sprzedane",
        "unavailable": "Niedostępne",
    }.get(kind, kind.title())


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


def history_period(timestamp: str, view: str) -> tuple[str, str, str]:
    """Return (key, title, subtitle) for timeline grouping."""
    try:
        day = datetime.fromisoformat(timestamp).date()
    except (ValueError, TypeError):
        return "unknown", "Data nieznana", ""

    if view == "week":
        year, week, _ = day.isocalendar()
        monday = day - timedelta(days=day.weekday())
        sunday = monday + timedelta(days=6)
        return (
            f"{year}-W{week:02d}",
            f"Tydzień {week} ({year})",
            f"{monday:%d.%m} – {sunday:%d.%m.%Y}",
        )
    if view == "month":
        month_name = POLISH_MONTHS[day.month] if 1 <= day.month <= 12 else f"{day.month:02d}"
        return f"{day:%Y-%m}", f"{month_name} {day.year}", f"{day:%m.%Y}"
    return day.isoformat(), day.strftime("%d.%m.%Y"), POLISH_WEEKDAYS[day.weekday()]


def event_badge(event_type: str, status: str = "") -> tuple[str, str]:
    if event_type == "new_listing":
        is_free = status_kind(status) == "available"
        return ("badge-new", "Nowa oferta" if is_free else "Nowa pozycja")
    if event_type == "status_change":
        return ("badge-status", "Zmiana statusu")
    if event_type == "price_change":
        return ("badge-price", "Zmiana ceny")
    if event_type == "removed_from_listing":
        return ("badge-removed", "Zniknęło z oferty")
    return ("badge-neutral", event_type.replace("_", " ").title())


def offer_card_html(offer: dict) -> str:
    kind = offer.get("status_kind") or status_kind(offer.get("status", ""))
    cat = offer.get("category", "")
    unit = offer.get("unit", "")
    price = offer.get("price") or "Cena niedostępna"
    url = offer.get("url", "#")
    area = offer.get("area_m2")
    rooms = offer.get("rooms")
    floor = offer.get("floor")
    staircase = offer.get("staircase")

    meta_parts = []
    if area:
        meta_parts.append(f"{area} m²")
    if rooms:
        meta_parts.append(f"{rooms} pok.")
    if floor:
        meta_parts.append(str(floor))
    if staircase:
        meta_parts.append(f"kl. {staircase}")
    meta_text = " · ".join(meta_parts) or group_name(cat)

    label = status_label(kind)
    price_content = ""
    has_drop = offer.get("has_price_drop")
    has_rise = offer.get("has_price_rise")

    if has_drop or has_rise:
        delta_amt = offer.get("total_delta_amount")
        delta_pct = offer.get("total_delta_pct")
        init_p = offer.get("initial_price")
        history_tooltip = offer.get("history_tooltip", "")
        if delta_amt is not None and delta_pct is not None:
            pill_cls = "price-drop-pill" if has_drop else "price-rise-pill"
            sign = "↓ -" if has_drop else "↑ +"
            delta_str = format_amount(abs(delta_amt))
            pct_formatted = f"{abs(delta_pct):.1f}%"
            tooltip_attr = f' title="{html.escape(history_tooltip)}"' if history_tooltip else ""
            price_content = f"""<div class="card-price-col">
          <div class="card-price-topline">
            <span class="card-old-price">{html.escape(init_p or "")}</span>
            <span class="{pill_cls}"{tooltip_attr}>{sign}{delta_str} zł ({pct_formatted})</span>
          </div>
          <strong class="card-price">{html.escape(price)}</strong>
        </div>"""

    if not price_content:
        if (not offer.get("price")) and offer.get("last_known_price"):
            last_p = offer["last_known_price"]
            price_content = f"""<div class="card-price-col">
          <strong class="card-price price-muted">Cena ukryta</strong>
          <span class="card-last-known">ostatnio: {html.escape(last_p)}</span>
        </div>"""
        else:
            price_content = f'<strong class="card-price">{html.escape(price)}</strong>'

    is_recent = offer.get("is_recent", False)
    recent_badge = (
        '<span class="badge-recent-change" title="Pozycja zmieniła się w ostatnim sprawdzeniu">✦ Ostatnia zmiana</span>'
        if is_recent
        else ""
    )

    return f"""<a class="flat-card status-border-{kind}" href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer" data-category="{html.escape(cat)}" data-status="{kind}" data-group="{html.escape(group_name(cat))}">
      <div class="card-header">
        <div class="card-title-wrap">
          <span class="status-dot dot-{kind}" aria-hidden="true"></span>
          <span class="card-unit">{html.escape(cat)} {html.escape(unit)}</span>
          {recent_badge}
        </div>
        <div class="card-header-actions">
          <button class="card-copy-btn" type="button" title="Kopiuj link do schowka" onclick="copyOfferLink(event, '{html.escape(url, quote=True)}')">🔗</button>
          <span class="status-pill pill-{kind}">{html.escape(label)}</span>
        </div>
      </div>
      <div class="card-body">
        <span class="card-meta">{html.escape(meta_text)}</span>
        <div class="card-price-row">
          {price_content}
          <span class="card-link-icon" aria-hidden="true">↗</span>
        </div>
      </div>
    </a>"""


def event_card_html(event: dict) -> str:
    event_type = event.get("event", "")
    badge_cls, badge_text = event_badge(event_type, event.get("status", ""))
    cat = event.get("category", "")
    unit = event.get("unit", "")
    url = event.get("url", "#")
    price = event.get("price") or ""

    if event_type == "status_change":
        summary = (
            f'<span class="diff-old">{html.escape(event.get("old_status", ""))}</span> '
            f'<span class="diff-arrow">→</span> '
            f'<strong class="diff-new">{html.escape(event.get("new_status", ""))}</strong>'
        )
    elif event_type == "price_change":
        old_p = event.get("old_price") or "—"
        new_p = event.get("new_price") or "—"
        delta_amount = event.get("delta_amount")
        delta_pct = event.get("delta_pct")
        if delta_amount is None and event.get("old_price") and event.get("new_price"):
            old_num = parse_price_num(event.get("old_price"))
            new_num = parse_price_num(event.get("new_price"))
            if old_num is not None and new_num is not None:
                delta_amount = new_num - old_num
                if old_num > 0:
                    delta_pct = round((delta_amount / old_num) * 100, 2)

        delta_badge = ""
        if delta_amount is not None:
            sign = "+" if delta_amount > 0 else ""
            delta_cls = "event-delta-drop" if delta_amount < 0 else "event-delta-rise"
            delta_badge = (
                f' <span class="{delta_cls}">{sign}{format_amount(delta_amount)} zł ({sign}{delta_pct:.2f}%)</span>'
            )
        summary = (
            f'<span class="diff-old">{html.escape(old_p)}</span> '
            f'<span class="diff-arrow">→</span> '
            f'<strong class="diff-new">{html.escape(new_p)}</strong>{delta_badge}'
        )
    elif event_type == "removed_from_listing":
        last_st = event.get("last_status")
        last_info = f" (było: {last_st})" if last_st else ""
        summary = f'<span class="text-muted">Usunięto ze strony dewelopera{html.escape(last_info)} · prawdopodobnie sprzedane/wycofane</span>'
    else:
        st = event.get("status", "")
        summary = f'<span class="diff-new">{html.escape(st)}</span>' if st else "Nowe ogłoszenie"

    price_html = f'<span class="event-price">{html.escape(price)}</span>' if price else ""

    return f"""<a class="event-item" href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer" data-event-type="{html.escape(event_type)}" data-category="{html.escape(cat)}">
      <div class="event-item-top">
        <span class="event-badge {badge_cls}">{html.escape(badge_text)}</span>
        {price_html}
      </div>
      <div class="event-item-main">
        <strong class="event-unit">{html.escape(cat)} {html.escape(unit)}</strong>
        <div class="event-summary">{summary}</div>
      </div>
      <div class="event-item-arrow">↗</div>
    </a>"""


def build_timeline_html(history: list[dict], view: str) -> str:
    periods: dict[str, dict] = {}
    for event in reversed(history):
        key, title, subtitle = history_period(event.get("ts", ""), view)
        if key not in periods:
            periods[key] = {
                "title": title,
                "subtitle": subtitle,
                "events": [],
                "counts": Counter(),
            }
        periods[key]["events"].append(event)
        periods[key]["counts"][event.get("event", "other")] += 1

    if not periods:
        return '<div class="empty-state">Brak zapisanych zmian w historii.</div>'

    sections = []
    for idx, (key, data) in enumerate(periods.items()):
        events = data["events"]
        counts = data["counts"]
        is_first = idx == 0

        breakdown_pills = []
        if counts["new_listing"]:
            breakdown_pills.append(f'<span class="mini-chip chip-green">+{counts["new_listing"]} nowe</span>')
        if counts["status_change"]:
            breakdown_pills.append(f'<span class="mini-chip chip-amber">~{counts["status_change"]} status</span>')
        if counts["price_change"]:
            breakdown_pills.append(f'<span class="mini-chip chip-indigo">~{counts["price_change"]} cena</span>')
        if counts["removed_from_listing"]:
            breakdown_pills.append(
                f'<span class="mini-chip chip-red">-{counts["removed_from_listing"]} zniknęło</span>'
            )
        breakdown_html = "".join(breakdown_pills)
        events_html = "".join(event_card_html(e) for e in events)
        open_attr = " open" if is_first else ""

        sections.append(
            f"""<details class="timeline-group"{open_attr} data-period-key="{html.escape(key)}">
        <summary class="timeline-summary">
          <div class="timeline-summary-left">
            <span class="timeline-marker"></span>
            <div>
              <div class="timeline-title-row">
                <h3 class="timeline-title">{html.escape(data["title"])}</h3>
                <span class="timeline-count-badge">{plural_events(len(events))}</span>
              </div>
              {f'<span class="timeline-subtitle">{html.escape(data["subtitle"])}</span>' if data["subtitle"] else ""}
            </div>
          </div>
          <div class="timeline-summary-right">
            <div class="timeline-chips">{breakdown_html}</div>
            <span class="accordion-chevron" aria-hidden="true">▾</span>
          </div>
        </summary>
        <div class="timeline-events-list">
          {events_html}
        </div>
      </details>"""
        )

    return "".join(sections)


def trend_card_html(
    group: str,
    total_gone: int,
    sub_label: str,
    range_label: str,
    svg_content: str,
    color_class: str,
) -> str:
    return f"""<article class="trend-card {color_class}">
        <div class="trend-card-head">
          <div>
            <span class="trend-card-category">{html.escape(group)}</span>
            <strong class="trend-card-value">{total_gone}</strong>
            <span class="trend-card-sub">{sub_label}</span>
          </div>
          <span class="trend-card-range">{range_label}</span>
        </div>
        <div class="trend-svg-wrap">
          {svg_content}
        </div>
      </article>"""


def weekly_trend_charts(history: list[dict], weeks_count: int = 8) -> str:
    today = datetime.now(UTC).date()
    current_monday = today - timedelta(days=today.weekday())

    week_counts: dict[str, Counter] = {}
    weeks: list[dict[str, str]] = []
    for i in range(weeks_count - 1, -1, -1):
        m = current_monday - timedelta(weeks=i)
        s = m + timedelta(days=6)
        year, w_num, _ = m.isocalendar()
        k = f"{year}-W{w_num:02d}"
        week_counts[k] = Counter()
        weeks.append(
            {
                "key": k,
                "label": f"T{w_num}",
                "start": f"{m:%d.%m}",
                "end": f"{s:%d.%m}",
                "full_label": f"Tydzień {w_num} ({m:%d.%m} – {s:%d.%m.%Y})",
            }
        )

    for event in history:
        if event.get("event") != "removed_from_listing":
            continue
        try:
            dt = datetime.fromisoformat(event.get("ts", "")).date()
            y, w, _ = dt.isocalendar()
            k = f"{y}-W{w:02d}"
            if k in week_counts:
                grp = group_name(event.get("category", ""))
                week_counts[k][grp] += 1
        except (ValueError, TypeError):
            continue

    charts = []
    width, height = 280, 88
    chart_h = 52
    padding_x = 10
    avail_w = width - 2 * padding_x
    n_weeks = len(weeks)
    col_w = 18
    gap = (avail_w - n_weeks * col_w) / (n_weeks - 1) if n_weeks > 1 else 0
    color_classes = ["trend-chart-apartments", "trend-chart-parking", "trend-chart-storage"]

    for index, group in enumerate(GROUPS):
        values = [week_counts[w["key"]][group] for w in weeks]
        total_gone = sum(values)
        max_val = max(max(values), 1)

        columns_svg = []
        for i, (w, val) in enumerate(zip(weeks, values)):
            x = padding_x + i * (col_w + gap)
            columns_svg.append(
                f'<rect x="{x:.1f}" y="12" width="{col_w}" height="{chart_h}" rx="4" class="col-track">'
                f"<title>{html.escape(w['full_label'])}: {val} zniknięć</title></rect>"
            )
            if val > 0:
                bar_h = max(int((val / max_val) * chart_h), 6)
                bar_y = 12 + chart_h - bar_h
                columns_svg.append(
                    f'<rect x="{x:.1f}" y="{bar_y}" width="{col_w}" height="{bar_h}" rx="4" class="col-fill">'
                    f"<title>{html.escape(w['full_label'])}: {val} zniknięć</title></rect>"
                )
                columns_svg.append(
                    f'<text x="{x + col_w / 2:.1f}" y="{bar_y - 2}" text-anchor="middle" class="col-val">{val}</text>'
                )
            columns_svg.append(
                f'<text x="{x + col_w / 2:.1f}" y="{12 + chart_h + 16}" text-anchor="middle" class="col-label">{html.escape(w["label"])}</text>'
            )

        svg = (
            f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{html.escape(group)}: {total_gone} zniknięć w ostatnich 8 tygodniach">'
            f"{''.join(columns_svg)}</svg>"
        )
        range_label = f"{weeks[0]['label']} – {weeks[-1]['label']} ({weeks[0]['start']} – {weeks[-1]['end']})"
        charts.append(
            trend_card_html(
                group=group,
                total_gone=total_gone,
                sub_label="zniknięć (ostatnie 8 tyg.)",
                range_label=range_label,
                svg_content=svg,
                color_class=color_classes[index % len(color_classes)],
            )
        )

    return "".join(charts)


def issue_trend_charts(issues: list[dict]) -> str:
    today = datetime.now(UTC).date()
    days = [today - timedelta(days=20 - offset) for offset in range(21)]
    counts = {day: Counter() for day in days}

    for issue in issues:
        try:
            day = datetime.fromisoformat(issue["createdAt"]).date()
        except (KeyError, ValueError):
            continue
        if day not in counts:
            continue
        for category in GONE_RE.findall(issue.get("body", "")):
            counts[day][group_name(category)] += 1

    charts = []
    width, height, padding = 280, 84, 10
    color_classes = ["trend-chart-apartments", "trend-chart-parking", "trend-chart-storage"]

    for index, group in enumerate(GROUPS):
        values = [counts[day][group] for day in days]
        total_gone = sum(values)
        maximum = max(max(values), 1)

        points = [
            (
                padding + offset * (width - 2 * padding) / (len(days) - 1),
                height - padding - value * (height - 2 * padding) / maximum,
            )
            for offset, value in enumerate(values)
        ]

        path_line = " ".join(f"{('M' if offset == 0 else 'L')}{x:.1f},{y:.1f}" for offset, (x, y) in enumerate(points))
        area_points = (
            f"M{points[0][0]:.1f},{height - padding} "
            + " ".join(f"L{x:.1f},{y:.1f}" for x, y in points)
            + f" L{points[-1][0]:.1f},{height - padding} Z"
        )

        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="trend-dot"><title>{day.strftime("%d.%m")}: {value} zniknięć</title></circle>'
            for (x, y), day, value in zip(points, days, values)
            if value
        )

        svg = f"""<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="{html.escape(group)}: {total_gone} zniknięć w 21 dni">
            <defs>
              <linearGradient id="grad-{index}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="currentColor" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="currentColor" stop-opacity="0.0"/>
              </linearGradient>
            </defs>
            <path class="trend-baseline" d="M{padding},{height - padding} H{width - padding}"/>
            <path class="trend-area" fill="url(#grad-{index})" d="{area_points}"/>
            <path class="trend-line" d="{path_line}"/>
            {dots}
          </svg>"""

        range_label = f"{days[0].strftime('%d.%m')} – {days[-1].strftime('%d.%m')}"
        charts.append(
            trend_card_html(
                group=group,
                total_gone=total_gone,
                sub_label="zniknięć (21 dni)",
                range_label=range_label,
                svg_content=svg,
                color_class=color_classes[index % len(color_classes)],
            )
        )

    return "".join(charts)


def render_template(template: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def normalize_offers(
    registry: dict,
    sold: list[dict],
    history: list[dict],
    events: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize registry and sold listings, decorating with price delta and status metrics."""
    offers = sorted(registry.values(), key=lambda o: (o.get("category", ""), o.get("unit", "")))

    normalized_sold = []
    for item in sold:
        s = dict(item)
        s["status"] = "Sprzedane"
        s["status_kind"] = "sold"
        s["group"] = group_name(s.get("category", ""))
        normalized_sold.append(s)

    for o in offers:
        o["status_kind"] = status_kind(o.get("status", ""))
        o["group"] = group_name(o.get("category", ""))
        if o.get("area_m2"):
            extras = o.get("extras") or []
            floor_extra = [x for x in extras if "piętro" in x.casefold() or "parter" in x.casefold()]
            if floor_extra and not o.get("floor"):
                o["floor"] = floor_extra[0]

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

    recent_units = set()
    if events:
        for e in events:
            if e.get("unit"):
                recent_units.add((e.get("category", ""), str(e.get("unit", ""))))
    elif history:
        try:
            latest_date = datetime.fromisoformat(history[-1].get("ts", "")).date()
            for e in reversed(history):
                if datetime.fromisoformat(e.get("ts", "")).date() == latest_date:
                    if e.get("unit"):
                        recent_units.add((e.get("category", ""), str(e.get("unit", ""))))
                else:
                    break
        except (ValueError, TypeError):
            pass

    for o in all_offers:
        key = (o.get("category", ""), str(o.get("unit", "")))
        o["is_recent"] = key in recent_units

    return offers, normalized_sold, all_offers


def build_category_progress_cards(offers: list[dict], normalized_sold: list[dict]) -> str:
    cards = []
    for name in GROUPS:
        cat_offers = [o for o in offers if group_name(o.get("category", "")) == name]
        cat_sold = [s for s in normalized_sold if group_name(s.get("category", "")) == name]
        cat_total = len(cat_offers) + len(cat_sold)
        cat_counts = Counter(o["status_kind"] for o in cat_offers)
        c_avail = cat_counts["available"]
        c_res = cat_counts["reserved"]
        c_sold = len(cat_sold)

        pct_avail = (c_avail / cat_total * 100) if cat_total else 0
        pct_res = (c_res / cat_total * 100) if cat_total else 0
        pct_sold = (c_sold / cat_total * 100) if cat_total else 0

        cards.append(
            f"""<article class="cat-stat-card">
        <div class="cat-stat-header">
          <h3 class="cat-stat-title">{html.escape(name)}</h3>
          <span class="cat-stat-total">{cat_total} pozycji</span>
        </div>
        <div class="cat-progress-bar" role="progressbar" aria-label="{html.escape(name)} podział statusów">
          <span class="progress-segment seg-avail" style="width:{pct_avail:.1f}%" title="Wolne: {c_avail} ({pct_avail:.1f}%)"></span>
          <span class="progress-segment seg-res" style="width:{pct_res:.1f}%" title="Rezerwacje: {c_res} ({pct_res:.1f}%)"></span>
          <span class="progress-segment seg-sold" style="width:{pct_sold:.1f}%" title="Sprzedane: {c_sold} ({pct_sold:.1f}%)"></span>
        </div>
        <div class="cat-stat-grid">
          <div class="cat-stat-item">
            <span class="cat-stat-label"><span class="dot dot-available"></span> Wolne</span>
            <strong class="cat-stat-val">{c_avail}</strong>
          </div>
          <div class="cat-stat-item">
            <span class="cat-stat-label"><span class="dot dot-reserved"></span> Rezerwacja</span>
            <strong class="cat-stat-val">{c_res}</strong>
          </div>
          <div class="cat-stat-item">
            <span class="cat-stat-label"><span class="dot dot-sold"></span> Sprzedane</span>
            <strong class="cat-stat-val">{c_sold}</strong>
          </div>
        </div>
        <div class="cat-stat-footer">
          <button class="cat-stat-btn" type="button" onclick="filterCatalogByGroup('{html.escape(name)}')">
            <span>Przeglądaj w katalogu ({cat_total})</span>
            <span class="btn-arrow" aria-hidden="true">→</span>
          </button>
        </div>
      </article>"""
        )
    return "".join(cards)


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
            "url": o.get("url", "#"),
            "has_drop": bool(o.get("has_price_drop")),
            "has_rise": bool(o.get("has_price_rise")),
            "delta_amt": o.get("total_delta_amount"),
            "delta_pct": o.get("total_delta_pct"),
            "initial_price": o.get("initial_price") or "",
            "last_known_price": o.get("last_known_price") or "",
            "history_tooltip": o.get("history_tooltip") or "",
            "recent": bool(o.get("is_recent")),
        }
        for o in all_offers
    ]


def build_dashboard_context(
    registry: dict,
    events: list[dict],
    sold: list[dict],
    issues: list[dict],
    history: list[dict],
    styles_css: str,
    app_js: str,
) -> dict[str, str]:
    offers, normalized_sold, all_offers = normalize_offers(registry, sold, history, events)

    drops_count = sum(1 for o in all_offers if o.get("has_price_drop"))
    drops_pct_avg = (
        round(
            sum(abs(o.get("total_delta_pct") or 0) for o in all_offers if o.get("has_price_drop")) / drops_count,
            1,
        )
        if drops_count
        else 0.0
    )
    drops_sub = f"średnio -{drops_pct_avg}% taniej" if drops_count else "brak obniżek"

    counts = Counter(o["status_kind"] for o in all_offers)
    total_known = len(all_offers)
    active_count = len(offers)
    avail_count = counts["available"]
    res_count = counts["reserved"]
    sold_count = counts["sold"]

    avail_pct = round((avail_count / total_known) * 100, 1) if total_known else 0
    res_pct = round((res_count / total_known) * 100, 1) if total_known else 0
    sold_pct = round((sold_count / total_known) * 100, 1) if total_known else 0

    if events:
        latest_changes_html = f'<div class="events-grid">{"".join(event_card_html(e) for e in events[:6])}</div>' + (
            f'<div class="latest-more-wrap"><button class="btn btn-secondary btn-sm" onclick="switchTab(\'tab-timeline\')">Zobacz wszystkie zmiany z tej sesji ({len(events)}) →</button></div>'
            if len(events) > 6
            else ""
        )
    else:
        latest_changes_html = '<div class="empty-state-card"><div class="empty-icon">✓</div><div><strong>Brak nowych zmian</strong><p>Wszystkie oferty są zgodne z poprzednim stanem.</p></div></div>'

    compact_offers_json = build_compact_offers_json(all_offers)

    return {
        "styles": styles_css,
        "app_js": app_js,
        "offers_json": json.dumps(compact_offers_json, ensure_ascii=False, allow_nan=False),
        "generated": datetime.now(UTC).strftime("%d.%m.%Y, %H:%M UTC"),
        "events_count": str(len(events)),
        "history_count": str(len(history)),
        "avail_count": str(avail_count),
        "avail_pct": str(avail_pct),
        "res_count": str(res_count),
        "res_pct": str(res_pct),
        "sold_count": str(sold_count),
        "sold_pct": str(sold_pct),
        "drops_count": str(drops_count),
        "drops_sub": drops_sub,
        "total_known": str(total_known),
        "active_count": str(active_count),
        "latest_changes_html": latest_changes_html,
        "categories_html": build_category_progress_cards(offers, normalized_sold),
        "weekly_trends_html": weekly_trend_charts(history, weeks_count=8),
        "daily_trends_html": issue_trend_charts(issues),
        "catalog_cards_html": "".join(offer_card_html(o) for o in all_offers),
        "timeline_weeks_html": build_timeline_html(history, "week"),
        "timeline_months_html": build_timeline_html(history, "month"),
        "timeline_days_html": build_timeline_html(history, "day"),
    }


def render(registry: dict, events: list[dict], sold: list[dict], issues: list[dict], history: list[dict]) -> str:
    html_template = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    styles_css = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (TEMPLATES_DIR / "app.js").read_text(encoding="utf-8")

    context = build_dashboard_context(
        registry=registry,
        events=events,
        sold=sold,
        issues=issues,
        history=history,
        styles_css=styles_css,
        app_js=app_js,
    )
    return render_template(html_template, context)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--events", default="events.json")
    parser.add_argument("--sold", default="sold_registry.json")
    parser.add_argument("--issue-history", default="issue-history.json")
    parser.add_argument("--history", default="history.log")
    parser.add_argument("--out", default="flat-dashboard.html")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    events_path = Path(args.events)
    events = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else []
    sold_path = Path(args.sold)
    sold = json.loads(sold_path.read_text(encoding="utf-8")) if sold_path.exists() else []
    issue_path = Path(args.issue_history)
    issues = json.loads(issue_path.read_text(encoding="utf-8")) if issue_path.exists() else []
    history_path = Path(args.history)
    history = (
        [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if history_path.exists()
        else []
    )

    out_content = render(registry, events, sold, issues, history)
    Path(args.out).write_text(out_content, encoding="utf-8")
    print(f"Rendered dashboard successfully to {args.out}")


if __name__ == "__main__":
    main()
