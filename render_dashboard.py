"""Render a self-contained, modern, mobile-friendly real-estate availability dashboard."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from price_history import build_price_history, format_amount, parse_area_num, parse_price_num

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017

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
    """Return (key, title, subtitle)."""
    try:
        dt = datetime.fromisoformat(timestamp)
        day = dt.date()
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
    """Return (css_class, label_text) for an event."""
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
        summary = f'<span class="diff-old">{html.escape(event.get("old_status", ""))}</span> <span class="diff-arrow">→</span> <strong class="diff-new">{html.escape(event.get("new_status", ""))}</strong>'
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
        summary = f'<span class="diff-old">{html.escape(old_p)}</span> <span class="diff-arrow">→</span> <strong class="diff-new">{html.escape(new_p)}</strong>{delta_badge}'
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
        ts = event.get("ts", "")
        try:
            dt = datetime.fromisoformat(ts).date()
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

        charts.append(
            f"""<article class="trend-card {color_classes[index % len(color_classes)]}">
        <div class="trend-card-head">
          <div>
            <span class="trend-card-category">{html.escape(group)}</span>
            <strong class="trend-card-value">{total_gone}</strong>
            <span class="trend-card-sub">zniknięć (ostatnie 8 tyg.)</span>
          </div>
          <span class="trend-card-range">{weeks[0]["label"]} – {weeks[-1]["label"]} ({weeks[0]["start"]} – {weeks[-1]["end"]})</span>
        </div>
        <div class="trend-svg-wrap">
          <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(group)}: {total_gone} zniknięć w ostatnich 8 tygodniach">
            {"".join(columns_svg)}
          </svg>
        </div>
      </article>"""
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

        charts.append(
            f"""<article class="trend-card {color_classes[index % len(color_classes)]}">
        <div class="trend-card-head">
          <div>
            <span class="trend-card-category">{html.escape(group)}</span>
            <strong class="trend-card-value">{total_gone}</strong>
            <span class="trend-card-sub">zniknięć (21 dni)</span>
          </div>
          <span class="trend-card-range">{days[0].strftime("%d.%m")} – {days[-1].strftime("%d.%m")}</span>
        </div>
        <div class="trend-svg-wrap">
          <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="{html.escape(group)}: {total_gone} zniknięć w 21 dni">
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
          </svg>
        </div>
      </article>"""
        )

    return "".join(charts)


def render(registry: dict, events: list[dict], sold: list[dict], issues: list[dict], history: list[dict]) -> str:
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

    recent_units = set()
    if events:
        for e in events:
            if e.get("unit"):
                recent_units.add((e.get("category", ""), str(e.get("unit", ""))))
    elif history:
        latest_ts = history[-1].get("ts", "")
        try:
            latest_date = datetime.fromisoformat(latest_ts).date()
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

    counts = Counter(o["status_kind"] for o in all_offers)
    total_known = len(all_offers)
    active_count = len(offers)
    avail_count = counts["available"]
    res_count = counts["reserved"]
    sold_count = counts["sold"]

    avail_pct = round((avail_count / total_known) * 100, 1) if total_known else 0
    res_pct = round((res_count / total_known) * 100, 1) if total_known else 0
    sold_pct = round((sold_count / total_known) * 100, 1) if total_known else 0

    category_progress_cards = []
    for name in GROUPS:
        cat_offers = [o for o in offers if group_name(o.get("category", "")) == name]
        cat_sold = [s for s in normalized_sold if group_name(s.get("category", "")) == name]
        cat_total = len(cat_offers) + len(cat_sold)
        cat_counts = Counter(o["status_kind"] for o in cat_offers)
        cat_sold_cnt = len(cat_sold)

        c_avail = cat_counts["available"]
        c_res = cat_counts["reserved"]
        c_sold = cat_sold_cnt

        pct_avail = (c_avail / cat_total * 100) if cat_total else 0
        pct_res = (c_res / cat_total * 100) if cat_total else 0
        pct_sold = (c_sold / cat_total * 100) if cat_total else 0

        category_progress_cards.append(
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

    categories_html = "".join(category_progress_cards)
    daily_trends_html = issue_trend_charts(issues)
    weekly_trends_html = weekly_trend_charts(history, weeks_count=8)

    if events:
        latest_changes_html = f'<div class="events-grid">{"".join(event_card_html(e) for e in events[:6])}</div>' + (
            f'<div class="latest-more-wrap"><button class="btn btn-secondary btn-sm" onclick="switchTab(\'tab-timeline\')">Zobacz wszystkie zmiany z tej sesji ({len(events)}) →</button></div>'
            if len(events) > 6
            else ""
        )
    else:
        latest_changes_html = '<div class="empty-state-card"><div class="empty-icon">✓</div><div><strong>Brak nowych zmian</strong><p>Wszystkie oferty są zgodne z poprzednim stanem.</p></div></div>'

    catalog_cards_html = "".join(offer_card_html(o) for o in all_offers)

    timeline_weeks_html = build_timeline_html(history, "week")
    timeline_months_html = build_timeline_html(history, "month")
    timeline_days_html = build_timeline_html(history, "day")

    generated = datetime.now(UTC).strftime("%d.%m.%Y, %H:%M UTC")

    compact_offers_json = []
    for o in all_offers:
        compact_offers_json.append(
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
        )

    return f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>Świętego Michała · Pulpit Dostępności</title>
  <meta name="description" content="Monitor zmian dostępności, rezerwacji i cen mieszkań i lokali w inwestycji Świętego Michała w Poznaniu.">
  <style>
    :root {{
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --bg: #f8fafc;
      --bg-surface: #ffffff;
      --bg-surface-elevated: #ffffff;
      --bg-subtle: #f1f5f9;
      --border: #e2e8f0;
      --border-subtle: #edf2f7;
      --text: #0f172a;
      --text-muted: #64748b;
      --text-subtle: #94a3b8;

      --primary: #2563eb;
      --primary-subtle: #eff6ff;
      --green: #10b981;
      --green-subtle: #ecfdf5;
      --green-border: #a7f3d0;
      --amber: #f59e0b;
      --amber-subtle: #fffbeb;
      --amber-border: #fde68a;
      --red: #ef4444;
      --red-subtle: #fef2f2;
      --red-border: #fecaca;
      --indigo: #6366f1;
      --indigo-subtle: #eef2ff;

      --shadow-sm: 0 1px 2px 0 rgba(0,0,0,0.05);
      --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05);
      --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.04);
      --radius-sm: 8px;
      --radius-md: 12px;
      --radius-lg: 16px;
      --radius-full: 9999px;
    }}

    @media (prefers-color-scheme: dark) {{
      :root:not([data-theme="light"]) {{
        --bg: #090d16;
        --bg-surface: #111827;
        --bg-surface-elevated: #1a2234;
        --bg-subtle: #1f293d;
        --border: #243048;
        --border-subtle: #1c2638;
        --text: #f8fafc;
        --text-muted: #94a3b8;
        --text-subtle: #64748b;

        --primary: #3b82f6;
        --primary-subtle: rgba(59,130,246,0.15);
        --green: #10b981;
        --green-subtle: rgba(16,185,129,0.15);
        --green-border: rgba(16,185,129,0.3);
        --amber: #f59e0b;
        --amber-subtle: rgba(245,158,11,0.15);
        --amber-border: rgba(245,158,11,0.3);
        --red: #f43f5e;
        --red-subtle: rgba(244,63,94,0.15);
        --red-border: rgba(244,63,94,0.3);
        --indigo: #818cf8;
        --indigo-subtle: rgba(129,140,248,0.15);

        --shadow-sm: 0 1px 2px 0 rgba(0,0,0,0.4);
        --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.5);
        --shadow-lg: 0 10px 20px -3px rgba(0,0,0,0.6);
      }}
    }}

    :root[data-theme="dark"] {{
      --bg: #090d16;
      --bg-surface: #111827;
      --bg-surface-elevated: #1a2234;
      --bg-subtle: #1f293d;
      --border: #243048;
      --border-subtle: #1c2638;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-subtle: #64748b;

      --primary: #3b82f6;
      --primary-subtle: rgba(59,130,246,0.15);
      --green: #10b981;
      --green-subtle: rgba(16,185,129,0.15);
      --green-border: rgba(16,185,129,0.3);
      --amber: #f59e0b;
      --amber-subtle: rgba(245,158,11,0.15);
      --amber-border: rgba(245,158,11,0.3);
      --red: #f43f5e;
      --red-subtle: rgba(244,63,94,0.15);
      --red-border: rgba(244,63,94,0.3);
      --indigo: #818cf8;
      --indigo-subtle: rgba(129,140,248,0.15);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    body {{
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: env(safe-area-inset-bottom, 40px);
      -webkit-font-smoothing: antialiased;
    }}

    /* Top Sticky Bar */
    .top-header {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(255, 255, 255, 0.82);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
    }}
    :root[data-theme="dark"] .top-header,
    @media (prefers-color-scheme: dark) {{
      :root:not([data-theme="light"]) .top-header {{
        background: rgba(17, 24, 39, 0.85);
      }}
    }}
    .header-inner {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 12px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }}
    .brand-wrap {{ display: flex; align-items: center; gap: 12px; }}
    .brand-logo {{
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #10b981, #059669);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-weight: 800;
      font-size: 1.15rem;
      box-shadow: 0 2px 6px rgba(16, 185, 129, 0.35);
    }}
    .brand-title {{ font-size: 1.05rem; font-weight: 750; letter-spacing: -0.02em; }}
    .brand-sub {{ font-size: 0.75rem; color: var(--text-muted); display: block; }}
    .header-actions {{ display: flex; align-items: center; gap: 8px; }}

    .btn-icon {{
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      color: var(--text);
      width: 38px;
      height: 38px;
      border-radius: var(--radius-full);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 1rem;
      transition: background 0.15s;
    }}
    .btn-icon:hover {{ background: var(--border); }}
    .ext-link-btn {{
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 14px;
      border-radius: var(--radius-full);
      text-decoration: none;
      font-size: 0.8rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s;
    }}
    .ext-link-btn:hover {{ background: var(--primary); color: white; border-color: var(--primary); }}

    /* Main Container */
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px 20px 48px;
    }}

    /* Hero Banner */
    .hero {{
      margin-bottom: 24px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 14px;
      font-size: 0.82rem;
      color: var(--text-muted);
    }}
    .live-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--green-subtle);
      color: var(--green);
      border: 1px solid var(--green-border);
      padding: 3px 9px;
      border-radius: var(--radius-full);
      font-weight: 700;
      font-size: 0.75rem;
    }}
    .pulse-dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 2px var(--green-border);
    }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .kpi-title {{ font-size: 0.78rem; font-weight: 650; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .kpi-num {{ font-size: 1.8rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1.1; }}
    .kpi-sub {{ font-size: 0.75rem; color: var(--text-muted); }}

    .kpi-avail .kpi-num {{ color: var(--green); }}
    .kpi-res .kpi-num {{ color: var(--amber); }}
    .kpi-sold .kpi-num {{ color: var(--red); }}
    .kpi-total .kpi-num {{ color: var(--primary); }}
    .kpi-drops .kpi-num {{ color: var(--green); }}

    /* Navigation Tabs */
    .nav-tabs {{
      display: flex;
      gap: 8px;
      margin-bottom: 24px;
      background: var(--bg-subtle);
      padding: 5px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .tab-btn {{
      flex: 1;
      min-width: 130px;
      padding: 10px 16px;
      border: 0;
      background: transparent;
      color: var(--text-muted);
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-family: inherit;
      font-size: 0.9rem;
      font-weight: 650;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.15s ease;
      white-space: nowrap;
    }}
    .tab-btn.active {{
      background: var(--bg-surface);
      color: var(--text);
      box-shadow: var(--shadow-sm);
    }}
    .tab-badge {{
      background: var(--bg-subtle);
      color: var(--text-muted);
      padding: 2px 7px;
      border-radius: var(--radius-full);
      font-size: 0.75rem;
      font-weight: 700;
    }}
    .tab-btn.active .tab-badge {{
      background: var(--primary-subtle);
      color: var(--primary);
    }}

    /* Tab Panels */
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; animation: fadeIn 0.18s ease; }}
    @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(3px); }} to {{ opacity: 1; transform: translateY(0); }} }}

    /* Section Headers */
    .section-head {{
      margin: 0 0 16px;
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .section-head h2 {{ font-size: 1.25rem; font-weight: 750; letter-spacing: -0.02em; }}
    .section-head p {{ font-size: 0.85rem; color: var(--text-muted); }}

    /* Category Stat Cards */
    .cat-stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
      margin-bottom: 30px;
    }}
    .cat-stat-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 18px;
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .cat-stat-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 12px;
    }}
    .cat-stat-title {{ font-size: 1.05rem; font-weight: 700; }}
    .cat-stat-total {{ font-size: 0.8rem; color: var(--text-muted); }}

    .cat-progress-bar {{
      display: flex;
      height: 12px;
      border-radius: var(--radius-full);
      background: var(--bg-subtle);
      overflow: hidden;
      margin-bottom: 14px;
    }}
    .progress-segment {{ min-width: 2px; transition: width 0.3s ease; }}
    .seg-avail {{ background: var(--green); }}
    .seg-res {{ background: var(--amber); }}
    .seg-sold {{ background: var(--red); }}

    .cat-stat-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }}
    .cat-stat-item {{
      background: var(--bg-subtle);
      padding: 8px 10px;
      border-radius: var(--radius-sm);
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .cat-stat-label {{ font-size: 0.74rem; color: var(--text-muted); display: flex; align-items: center; gap: 5px; }}
    .cat-stat-val {{ font-size: 1.15rem; font-weight: 800; }}

    .cat-stat-footer {{
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--border-subtle);
    }}
    .cat-stat-btn {{
      width: 100%;
      height: 38px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--text);
      font-family: inherit;
      font-size: 0.82rem;
      font-weight: 650;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.15s ease;
    }}
    .cat-stat-btn:hover {{
      background: var(--primary);
      color: #ffffff;
      border-color: var(--primary);
      box-shadow: var(--shadow-sm);
    }}
    .cat-stat-btn:active {{
      transform: scale(0.99);
    }}
    .cat-stat-btn .btn-arrow {{
      font-size: 0.9rem;
      transition: transform 0.15s ease;
    }}
    .cat-stat-btn:hover .btn-arrow {{
      transform: translateX(3px);
    }}

    .clickable-card {{
      cursor: pointer;
      transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .clickable-card:hover {{
      transform: translateY(-2px);
      border-color: var(--primary);
      box-shadow: var(--shadow-md);
    }}

    /* Trend Cards */
    .trends-wrap {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
      margin-bottom: 32px;
    }}
    .trend-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      box-shadow: var(--shadow-sm);
    }}
    .trend-card-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
    }}
    .trend-card-category {{ font-size: 0.82rem; font-weight: 650; color: var(--text-muted); text-transform: uppercase; display: block; }}
    .trend-card-value {{ font-size: 1.6rem; font-weight: 800; line-height: 1.1; margin-right: 4px; }}
    .trend-card-sub {{ font-size: 0.78rem; color: var(--text-muted); }}
    .trend-card-range {{ font-size: 0.72rem; color: var(--text-subtle); font-weight: 600; background: var(--bg-subtle); padding: 3px 7px; border-radius: var(--radius-full); }}

    .trend-svg-wrap {{ width: 100%; height: 84px; }}
    .trend-svg-wrap svg {{ width: 100%; height: 100%; overflow: visible; }}
    .trend-baseline {{ stroke: var(--border); stroke-dasharray: 3 3; stroke-width: 1; }}
    .trend-line {{ fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }}
    .trend-dot {{ stroke: var(--bg-surface); stroke-width: 2; cursor: pointer; transition: transform 0.15s; }}
    .trend-dot:hover {{ transform: scale(1.3); }}

    .trend-chart-apartments .trend-line {{ stroke: var(--red); }}
    .trend-chart-apartments .trend-dot {{ fill: var(--red); }}
    .trend-chart-apartments {{ color: var(--red); }}

    .trend-chart-parking .trend-line {{ stroke: var(--amber); }}
    .trend-chart-parking .trend-dot {{ fill: var(--amber); }}
    .trend-chart-parking {{ color: var(--amber); }}

    .trend-chart-storage .trend-line {{ stroke: var(--indigo); }}
    .trend-chart-storage .trend-dot {{ fill: var(--indigo); }}
    .trend-chart-storage {{ color: var(--indigo); }}

    /* Weekly Column Chart Elements */
    .trend-toggle-group {{
      display: inline-flex;
      gap: 4px;
      background: var(--bg-subtle);
      padding: 3px;
      border-radius: var(--radius-full);
      border: 1px solid var(--border);
    }}
    .trend-toggle-group .pill-btn {{
      padding: 4px 10px;
      font-size: 0.75rem;
      border: 0;
      background: transparent;
      color: var(--text-muted);
    }}
    .trend-toggle-group .pill-btn.active {{
      background: var(--bg-surface);
      color: var(--text);
      box-shadow: var(--shadow-sm);
    }}

    .col-track {{ fill: var(--bg-subtle); }}
    .col-fill {{ fill: currentColor; cursor: pointer; transition: filter 0.15s ease; }}
    .col-fill:hover {{ filter: brightness(1.25); }}
    .col-val {{ font-size: 10px; font-weight: 800; fill: currentColor; }}
    .col-label {{ font-size: 9.5px; font-weight: 600; fill: var(--text-subtle); }}

    /* Catalog View & Filters */
    .catalog-bar {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
    }}
    .catalog-bar-top {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .search-wrap {{
      flex: 1;
      min-width: 220px;
      position: relative;
    }}
    .search-input {{
      width: 100%;
      height: 42px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 0 38px 0 38px;
      font-family: inherit;
      font-size: 0.95rem;
      color: var(--text);
      outline: none;
      transition: border-color 0.15s, background 0.15s;
    }}
    .search-input::-webkit-search-cancel-button {{
      -webkit-appearance: none;
      display: none;
    }}
    .search-input:focus {{
      border-color: var(--primary);
      background: var(--bg-surface);
    }}
    .search-icon {{
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 0.95rem;
      pointer-events: none;
    }}
    .search-clear-btn {{
      position: absolute;
      right: 12px;
      top: 50%;
      transform: translateY(-50%);
      background: var(--border);
      border: 0;
      color: var(--text-muted);
      width: 22px;
      height: 22px;
      border-radius: 50%;
      font-size: 0.72rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.15s ease;
      padding: 0;
    }}
    .search-clear-btn:hover {{
      background: var(--text-muted);
      color: var(--bg-surface);
    }}

    .active-filters-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      background: var(--bg-subtle);
      border: 1px dashed var(--border);
      border-radius: var(--radius-sm);
      font-size: 0.8rem;
      flex-wrap: wrap;
    }}
    .active-filters-left {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .active-filters-label {{
      font-weight: 700;
      color: var(--text-muted);
    }}
    .active-filter-tags {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .active-filter-chip {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-full);
      padding: 2px 9px;
      font-weight: 650;
      color: var(--text);
      font-size: 0.74rem;
    }}
    .reset-filters-btn {{
      background: transparent;
      border: 0;
      color: var(--primary);
      font-family: inherit;
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: var(--radius-sm);
      transition: background 0.15s;
    }}
    .reset-filters-btn:hover {{
      background: var(--primary-subtle);
      text-decoration: underline;
    }}
    .sort-select {{
      height: 42px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 0 12px;
      font-family: inherit;
      font-size: 0.88rem;
      color: var(--text);
      cursor: pointer;
      outline: none;
    }}

    .filter-pills-row {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .pill-btn {{
      padding: 6px 12px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-full);
      font-family: inherit;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.15s;
    }}
    .pill-btn:hover {{ color: var(--text); background: var(--border); }}
    .pill-btn.active {{
      background: var(--text);
      color: var(--bg);
      border-color: var(--text);
    }}

    /* Inventory Cards Grid */
    .inventory-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
      gap: 12px;
    }}
    .inventory-grid.compact-mode {{
      grid-template-columns: 1fr;
      gap: 8px;
    }}

    .flat-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      text-decoration: none;
      color: inherit;
      display: flex;
      flex-direction: column;
      gap: 10px;
      box-shadow: var(--shadow-sm);
      transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
      position: relative;
    }}
    .flat-card:hover {{
      transform: translateY(-2px);
      box-shadow: var(--shadow-md);
      border-color: var(--primary);
    }}
    .compact-mode .flat-card {{
      flex-direction: row;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
    }}

    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }}
    .card-title-wrap {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .card-unit {{
      font-weight: 750;
      font-size: 0.95rem;
      letter-spacing: -0.01em;
    }}
    .badge-recent-change {{
      font-size: 0.68rem;
      font-weight: 750;
      color: var(--indigo);
      background: var(--indigo-subtle);
      border: 1px solid rgba(99, 102, 241, 0.35);
      padding: 2px 7px;
      border-radius: var(--radius-full);
      display: inline-flex;
      align-items: center;
      gap: 3px;
      white-space: nowrap;
    }}
    .card-header-actions {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .card-copy-btn {{
      width: 28px;
      height: 28px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--text-muted);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 0.8rem;
      transition: all 0.15s ease;
      padding: 0;
    }}
    .card-copy-btn:hover {{
      background: var(--border);
      color: var(--text);
    }}
    .card-copy-btn.copied {{
      background: var(--green-subtle);
      color: var(--green);
      border-color: var(--green-border);
    }}
    .card-body {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .compact-mode .card-body {{
      flex-direction: row;
      align-items: center;
      gap: 16px;
    }}
    .card-meta {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}
    .card-price-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 8px;
    }}
    .card-price-col {{
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }}
    .card-price-topline {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .card-old-price {{
      font-size: 0.76rem;
      color: var(--text-subtle);
      text-decoration: line-through;
      font-weight: 600;
    }}
    .price-drop-pill {{
      font-size: 0.72rem;
      font-weight: 750;
      color: var(--green);
      background: var(--green-subtle);
      border: 1px solid var(--green-border);
      border-radius: var(--radius-full);
      padding: 1px 7px;
      line-height: 1.3;
      white-space: nowrap;
    }}
    .price-rise-pill {{
      font-size: 0.72rem;
      font-weight: 750;
      color: var(--red);
      background: var(--red-subtle);
      border: 1px solid var(--red-border);
      border-radius: var(--radius-full);
      padding: 1px 7px;
      line-height: 1.3;
      white-space: nowrap;
    }}
    .card-last-known {{
      font-size: 0.75rem;
      color: var(--text-muted);
      font-weight: 500;
    }}
    .price-muted {{
      color: var(--text-muted);
      font-size: 0.95rem;
      font-weight: 600;
      font-style: italic;
    }}
    .card-price {{
      font-size: 1.02rem;
      font-weight: 800;
      color: var(--text);
    }}
    .card-link-icon {{
      font-size: 0.85rem;
      color: var(--text-subtle);
      transition: transform 0.15s;
    }}
    .flat-card:hover .card-link-icon {{
      color: var(--primary);
      transform: translate(2px, -2px);
    }}

    /* Dots & Status Pills */
    .status-dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      display: inline-block;
      flex-shrink: 0;
    }}
    .dot-available {{ background: var(--green); }}
    .dot-reserved {{ background: var(--amber); }}
    .dot-sold {{ background: var(--red); }}
    .dot-unavailable {{ background: var(--text-subtle); }}

    .status-pill {{
      font-size: 0.7rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: var(--radius-full);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .pill-available {{ background: var(--green-subtle); color: var(--green); border: 1px solid var(--green-border); }}
    .pill-reserved {{ background: var(--amber-subtle); color: var(--amber); border: 1px solid var(--amber-border); }}
    .pill-sold {{ background: var(--red-subtle); color: var(--red); border: 1px solid var(--red-border); }}
    .pill-unavailable {{ background: var(--bg-subtle); color: var(--text-muted); border: 1px solid var(--border); }}

    /* Timeline & Changelog View */
    .timeline-controls-bar {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      margin-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
      box-shadow: var(--shadow-sm);
    }}
    .grouping-pills {{
      display: inline-flex;
      background: var(--bg-subtle);
      padding: 4px;
      border-radius: var(--radius-full);
      border: 1px solid var(--border);
    }}
    .group-btn {{
      border: 0;
      background: transparent;
      padding: 6px 14px;
      border-radius: var(--radius-full);
      font-family: inherit;
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.15s;
    }}
    .group-btn.active {{
      background: var(--bg-surface);
      color: var(--text);
      box-shadow: var(--shadow-sm);
    }}

    .timeline-filter-pills {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}

    /* Timeline Accordion Periods */
    .timeline-view-panel {{ display: none; }}
    .timeline-view-panel.active {{ display: block; }}

    .timeline-group {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      margin-bottom: 12px;
      overflow: hidden;
      box-shadow: var(--shadow-sm);
      transition: border-color 0.15s;
    }}
    .timeline-group[open] {{
      border-color: var(--primary);
    }}
    .timeline-summary {{
      list-style: none;
      padding: 14px 18px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      user-select: none;
      background: var(--bg-surface);
      transition: background 0.15s;
    }}
    .timeline-summary::-webkit-details-marker {{ display: none; }}
    .timeline-summary:hover {{ background: var(--bg-subtle); }}

    .timeline-summary-left {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .timeline-marker {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-subtle);
    }}
    .timeline-title-row {{
      display: flex;
      align-items: baseline;
      gap: 8px;
    }}
    .timeline-title {{
      font-size: 0.98rem;
      font-weight: 750;
      letter-spacing: -0.01em;
    }}
    .timeline-count-badge {{
      font-size: 0.75rem;
      font-weight: 650;
      color: var(--text-muted);
    }}
    .timeline-subtitle {{
      display: block;
      font-size: 0.78rem;
      color: var(--text-subtle);
    }}

    .timeline-summary-right {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .timeline-chips {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .mini-chip {{
      font-size: 0.72rem;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: var(--radius-full);
    }}
    .chip-green {{ background: var(--green-subtle); color: var(--green); }}
    .chip-amber {{ background: var(--amber-subtle); color: var(--amber); }}
    .chip-indigo {{ background: var(--indigo-subtle); color: var(--indigo); }}
    .chip-red {{ background: var(--red-subtle); color: var(--red); }}

    .accordion-chevron {{
      font-size: 0.85rem;
      color: var(--text-muted);
      transition: transform 0.2s ease;
    }}
    .timeline-group[open] .accordion-chevron {{
      transform: rotate(180deg);
    }}

    .timeline-events-list {{
      padding: 0 16px 14px;
      display: grid;
      gap: 8px;
      border-top: 1px solid var(--border-subtle);
      background: var(--bg);
    }}

    /* Event Item Card */
    .event-item {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 12px 14px;
      text-decoration: none;
      color: inherit;
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: center;
      gap: 14px;
      transition: transform 0.12s, border-color 0.12s;
    }}
    .event-item:hover {{
      transform: translateX(2px);
      border-color: var(--primary);
    }}
    .event-item-top {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 120px;
    }}
    .event-badge {{
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 800;
      padding: 2px 8px;
      border-radius: var(--radius-full);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      width: fit-content;
    }}
    .badge-new {{ background: var(--green-subtle); color: var(--green); border: 1px solid var(--green-border); }}
    .badge-status {{ background: var(--amber-subtle); color: var(--amber); border: 1px solid var(--amber-border); }}
    .badge-price {{ background: var(--indigo-subtle); color: var(--indigo); border: 1px solid rgba(99,102,241,0.3); }}
    .badge-removed {{ background: var(--red-subtle); color: var(--red); border: 1px solid var(--red-border); }}
    .badge-neutral {{ background: var(--bg-subtle); color: var(--text-muted); border: 1px solid var(--border); }}

    .event-price {{ font-size: 0.8rem; font-weight: 700; color: var(--text-muted); }}
    .event-item-main {{ display: flex; flex-direction: column; gap: 3px; }}
    .event-unit {{ font-size: 0.95rem; font-weight: 750; }}
    .event-summary {{ font-size: 0.83rem; color: var(--text-muted); }}
    .diff-old {{ text-decoration: line-through; opacity: 0.7; }}
    .diff-arrow {{ color: var(--text-subtle); margin: 0 3px; }}
    .diff-new {{ color: var(--text); font-weight: 700; }}
    .event-delta-drop {{
      color: var(--green);
      font-weight: 750;
      background: var(--green-subtle);
      padding: 1px 6px;
      border-radius: 4px;
      border: 1px solid var(--green-border);
      font-size: 0.78rem;
      margin-left: 4px;
      display: inline-block;
    }}
    .event-delta-rise {{
      color: var(--red);
      font-weight: 750;
      background: var(--red-subtle);
      padding: 1px 6px;
      border-radius: 4px;
      border: 1px solid var(--red-border);
      font-size: 0.78rem;
      margin-left: 4px;
      display: inline-block;
    }}
    .event-item-arrow {{ color: var(--text-subtle); font-size: 0.95rem; }}

    /* Empty states & generic helpers */
    .empty-state {{
      padding: 36px 20px;
      text-align: center;
      background: var(--bg-surface);
      border: 1px dashed var(--border);
      border-radius: var(--radius-md);
      color: var(--text-muted);
      font-size: 0.95rem;
    }}
    .empty-state-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 20px;
      display: flex;
      align-items: center;
      gap: 16px;
      box-shadow: var(--shadow-sm);
    }}
    .empty-icon {{
      width: 40px;
      height: 40px;
      border-radius: var(--radius-full);
      background: var(--green-subtle);
      color: var(--green);
      font-size: 1.2rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .events-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .latest-more-wrap {{ text-align: center; margin-top: 10px; }}

    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 16px;
      border-radius: var(--radius-full);
      font-family: inherit;
      font-size: 0.88rem;
      font-weight: 650;
      cursor: pointer;
      border: 1px solid transparent;
      text-decoration: none;
      transition: all 0.15s;
    }}
    .btn-secondary {{
      background: var(--bg-surface);
      border-color: var(--border);
      color: var(--text);
    }}
    .btn-secondary:hover {{
      background: var(--bg-subtle);
      border-color: var(--primary);
    }}
    .btn-sm {{ font-size: 0.8rem; padding: 6px 14px; }}

    .pagination-bar {{
      margin-top: 24px;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
    }}
    .catalog-count-note {{
      font-size: 0.82rem;
      color: var(--text-muted);
      text-align: center;
      margin-top: 8px;
    }}

    /* Mobile Responsive Polish */
    @media (max-width: 768px) {{
      main {{ padding: 16px 14px 40px; }}
      .header-inner {{ padding: 10px 14px; }}
      .kpi-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
      .kpi-card {{ padding: 12px 14px; }}
      .kpi-num {{ font-size: 1.5rem; }}
      .cat-stats-grid {{ grid-template-columns: 1fr; }}
      .trends-wrap {{ grid-template-columns: 1fr; }}
      .nav-tabs {{ padding: 3px; }}
      .tab-btn {{ min-width: 100px; padding: 8px 10px; font-size: 0.82rem; }}
      .event-item {{
        grid-template-columns: 1fr auto;
        gap: 8px;
      }}
      .event-item-top {{
        grid-column: 1 / -1;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
      }}
      .timeline-summary {{ padding: 12px 14px; }}
      .timeline-chips {{ display: none; }}
      .catalog-bar-top {{ flex-direction: column; }}
      .inventory-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

  <!-- Top Sticky Bar -->
  <header class="top-header">
    <div class="header-inner">
      <div class="brand-wrap">
        <div class="brand-logo">ŚM</div>
        <div>
          <span class="brand-title">Świętego Michała</span>
          <span class="brand-sub">Poznań · Pulpit Inwestycji</span>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn-icon" id="theme-toggle" aria-label="Przełącz tryb ciemny" title="Przełącz motyw">🌓</button>
        <a class="ext-link-btn" href="https://swietegomichala.pl/pl/wyszukiwarka-mieszkan" target="_blank" rel="noreferrer">
          <span>Strona dewelopera</span> ↗
        </a>
      </div>
    </div>
  </header>

  <main>
    <!-- Hero Info -->
    <section class="hero">
      <div class="hero-meta">
        <span class="live-badge"><span class="pulse-dot"></span> Monitor aktywny</span>
        <span>Ostatnia aktualizacja: <strong>{generated}</strong></span>
        <span>Wykryte zmiany w tej sesji: <strong>{len(events)}</strong></span>
      </div>
    </section>

    <!-- KPI Summary Grid -->
    <section class="kpi-grid" aria-label="Główne wskaźniki">
      <div class="kpi-card kpi-avail clickable-card" role="button" tabindex="0" onclick="filterCatalogByStatus('available')" title="Pokaż wolne lokale w katalogu">
        <span class="kpi-title">Wolne lokale ↗</span>
        <strong class="kpi-num">{avail_count}</strong>
        <span class="kpi-sub">{avail_pct}% całej oferty</span>
      </div>
      <div class="kpi-card kpi-res clickable-card" role="button" tabindex="0" onclick="filterCatalogByStatus('reserved')" title="Pokaż rezerwacje w katalogu">
        <span class="kpi-title">Rezerwacje ↗</span>
        <strong class="kpi-num">{res_count}</strong>
        <span class="kpi-sub">{res_pct}% całej oferty</span>
      </div>
      <div class="kpi-card kpi-sold clickable-card" role="button" tabindex="0" onclick="filterCatalogByStatus('sold')" title="Pokaż sprzedane w katalogu">
        <span class="kpi-title">Sprzedane / Zniknięte ↗</span>
        <strong class="kpi-num">{sold_count}</strong>
        <span class="kpi-sub">{sold_pct}% całej oferty</span>
      </div>
      <div class="kpi-card kpi-drops clickable-card" role="button" tabindex="0" onclick="filterCatalogByPriceDrops()" title="Pokaż obniżki cen w katalogu">
        <span class="kpi-title">Obniżki cen ↗</span>
        <strong class="kpi-num">{drops_count}</strong>
        <span class="kpi-sub">{drops_sub}</span>
      </div>
      <div class="kpi-card kpi-total clickable-card" role="button" tabindex="0" onclick="filterCatalogByStatus('all')" title="Pokaż wszystkie lokale w katalogu">
        <span class="kpi-title">Łącznie znanych ↗</span>
        <strong class="kpi-num">{total_known}</strong>
        <span class="kpi-sub">{active_count} na stronie dewelopera</span>
      </div>
    </section>

    <!-- Primary Navigation Tabs -->
    <nav class="nav-tabs" role="tablist" aria-label="Główne widoki strony">
      <button class="tab-btn active" role="tab" aria-selected="true" aria-controls="tab-overview" data-target="tab-overview" onclick="switchTab('tab-overview')">
        <span>📊 Przegląd & Trendy</span>
      </button>
      <button class="tab-btn" role="tab" aria-selected="false" aria-controls="tab-catalog" data-target="tab-catalog" onclick="switchTab('tab-catalog')">
        <span>🏢 Katalog Ofert</span>
        <span class="tab-badge">{total_known}</span>
      </button>
      <button class="tab-btn" role="tab" aria-selected="false" aria-controls="tab-timeline" data-target="tab-timeline" onclick="switchTab('tab-timeline')">
        <span>⏱️ Oś Czasu</span>
        <span class="tab-badge">{len(history)}</span>
      </button>
    </nav>

    <!-- TAB 1: OVERVIEW -->
    <div id="tab-overview" class="tab-panel active" role="tabpanel">
      <!-- Latest changes preview -->
      <section style="margin-bottom: 28px;">
        <div class="section-head">
          <div>
            <h2>Ostatnie zdarzenia</h2>
            <p>Najnowsze wykryte zmiany dostępności, cen lub statusów.</p>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="switchTab('tab-timeline')">Pełna oś czasu ({len(history)}) →</button>
        </div>
        {latest_changes_html}
      </section>

      <!-- Category progress breakdown -->
      <section style="margin-bottom: 28px;">
        <div class="section-head">
          <div>
            <h2>Kondycja oferty wg kategorii</h2>
            <p>Stosunek lokali wolnych, zarezerwowanych i sprzedanych.</p>
          </div>
        </div>
        <div class="cat-stats-grid">
          {categories_html}
        </div>
      </section>

      <!-- Trends: Disappearances in last 21 days & 8 weeks -->
      <section>
        <div class="section-head">
          <div>
            <h2>Dynamika sprzedaży &amp; zniknięć z oferty</h2>
            <p>Zniknięcie ze strony dewelopera zazwyczaj oznacza sfinalizowaną sprzedaż lub wycofanie oferty.</p>
          </div>
          <div class="trend-toggle-group" role="group" aria-label="Wybierz okres trendów">
            <button class="pill-btn active" data-trend-btn="weeks" onclick="switchTrendView('weeks')">Tygodnie (8 tyg.)</button>
            <button class="pill-btn" data-trend-btn="days" onclick="switchTrendView('days')">Dni (21 dni)</button>
          </div>
        </div>
        <div id="trend-view-weeks" class="trends-wrap">{weekly_trends_html}</div>
        <div id="trend-view-days" class="trends-wrap" style="display:none;">{daily_trends_html}</div>
      </section>
    </div>

    <!-- TAB 2: CATALOG OF OFFERS -->
    <div id="tab-catalog" class="tab-panel" role="tabpanel">
      <div class="catalog-bar">
        <div class="catalog-bar-top">
          <div class="search-wrap">
            <span class="search-icon">🔍</span>
            <input type="search" id="catalog-search" class="search-input" placeholder="Szukaj lokalu (np. 34_1, KL10, parter, 40 m²)..." autocomplete="off" aria-label="Wyszukaj lokal">
            <button id="search-clear-btn" class="search-clear-btn" type="button" aria-label="Wyczyść wyszukiwanie" style="display:none;" title="Wyczyść frazę">✕</button>
          </div>
          <select id="catalog-sort" class="sort-select" aria-label="Sortowanie ofert">
            <option value="default">Sortowanie domyślne</option>
            <option value="drop-desc">🔥 Największa obniżka (zł)</option>
            <option value="drop-pct-desc">🔥 Największa obniżka (%)</option>
            <option value="price-asc">Cena: od najniższej</option>
            <option value="price-desc">Cena: od najwyższej</option>
            <option value="area-desc">Metraż: od największego</option>
            <option value="area-asc">Metraż: od najmniejszego</option>
            <option value="unit-asc">Numer lokalu (A-Z)</option>
          </select>
          <button id="view-mode-toggle" class="btn btn-secondary btn-sm" type="button" title="Przełącz widok siatka/lista">Widok: Kafelki</button>
        </div>

        <div class="filter-pills-row" id="price-filters">
          <span style="font-size:0.75rem; font-weight:700; color:var(--text-muted); margin-right:4px;">Cena:</span>
          <button class="pill-btn active" data-price-filter="all">Wszystkie</button>
          <button class="pill-btn" data-price-filter="drops">🔥 Obniżki cen ({drops_count})</button>
        </div>

        <div class="filter-pills-row" id="category-filters">
          <span style="font-size:0.75rem; font-weight:700; color:var(--text-muted); margin-right:4px;">Kategoria:</span>
          <button class="pill-btn active" data-cat-filter="all">Wszystkie</button>
          <button class="pill-btn" data-cat-filter="Mieszkanie">Mieszkania</button>
          <button class="pill-btn" data-cat-filter="Hala garażowa,Miejsce postojowe">Parkowanie</button>
          <button class="pill-btn" data-cat-filter="Komórka">Komórki</button>
        </div>

        <div class="filter-pills-row" id="status-filters">
          <span style="font-size:0.75rem; font-weight:700; color:var(--text-muted); margin-right:4px;">Status:</span>
          <button class="pill-btn active" data-status-filter="all">Wszystkie</button>
          <button class="pill-btn" data-status-filter="available">Wolne</button>
          <button class="pill-btn" data-status-filter="reserved">Rezerwacje</button>
          <button class="pill-btn" data-status-filter="sold">Sprzedane</button>
        </div>

        <div id="active-filters-bar" class="active-filters-bar" style="display:none;">
          <div class="active-filters-left">
            <span class="active-filters-label">Aktywne filtry (<span id="active-filters-count">0</span>):</span>
            <div id="active-filter-tags" class="active-filter-tags"></div>
          </div>
          <button id="reset-filters-btn" class="reset-filters-btn" type="button">Resetuj filtry ✕</button>
        </div>
      </div>

      <!-- Inventory Grid -->
      <div id="catalog-grid" class="inventory-grid">
        {catalog_cards_html}
      </div>

      <!-- Pagination / Load more -->
      <div class="pagination-bar" id="pagination-wrap">
        <button id="load-more-btn" class="btn btn-secondary" type="button">Pokaż więcej ofert</button>
      </div>
      <p class="catalog-count-note" id="catalog-count-note">Wyświetlono <span id="visible-count">0</span> z <span id="total-count">{total_known}</span> pozycji</p>
    </div>

    <!-- TAB 3: TIMELINE / CHANGELOG -->
    <div id="tab-timeline" class="tab-panel" role="tabpanel">
      <div class="timeline-controls-bar">
        <div>
          <span style="font-size:0.78rem; font-weight:700; color:var(--text-muted); margin-right:6px; display:inline-block;">Grupowanie:</span>
          <div class="grouping-pills" role="group" aria-label="Wybierz sposób grupowania osi czasu">
            <button class="group-btn active" data-timeline-view="week" onclick="switchTimelineGrouping('week')">Tygodnie</button>
            <button class="group-btn" data-timeline-view="month" onclick="switchTimelineGrouping('month')">Miesiące</button>
            <button class="group-btn" data-timeline-view="day" onclick="switchTimelineGrouping('day')">Dni</button>
          </div>
        </div>

        <div class="timeline-filter-pills" id="timeline-event-filters">
          <button class="pill-btn active" data-timeline-type="all">Wszystkie ({len(history)})</button>
          <button class="pill-btn" data-timeline-type="new_listing">Nowe</button>
          <button class="pill-btn" data-timeline-type="status_change">Zmiany statusu</button>
          <button class="pill-btn" data-timeline-type="price_change">Zmiany cen</button>
          <button class="pill-btn" data-timeline-type="removed_from_listing">Zniknięcia</button>
        </div>
      </div>

      <!-- Timeline Views -->
      <div id="timeline-view-week" class="timeline-view-panel active">
        {timeline_weeks_html}
      </div>
      <div id="timeline-view-month" class="timeline-view-panel">
        {timeline_months_html}
      </div>
      <div id="timeline-view-day" class="timeline-view-panel">
        {timeline_days_html}
      </div>
    </div>
  </main>

  <script id="offers-data" type="application/json">
    {json.dumps(compact_offers_json, ensure_ascii=False)}
  </script>

  <script>
    // --- Global Tab Switching ---
    function switchTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(btn => {{
        const isActive = btn.dataset.target === tabId;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive);
      }});
      document.querySelectorAll('.tab-panel').forEach(panel => {{
        panel.classList.toggle('active', panel.id === tabId);
      }});
      window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }}

    function filterCatalogByStatus(statusKey) {{
      switchTab('tab-catalog');
      const btn = Array.from(document.querySelectorAll('#status-filters .pill-btn')).find(b => b.dataset.statusFilter === statusKey);
      if (btn) btn.click();
    }}

    function filterCatalogByPriceDrops() {{
      switchTab('tab-catalog');
      const btn = document.querySelector('#price-filters [data-price-filter="drops"]');
      if (btn) btn.click();
    }}

    function filterCatalogByGroup(groupName) {{
      switchTab('tab-catalog');
      const catBtn = Array.from(document.querySelectorAll('#category-filters .pill-btn')).find(b => {{
        if (groupName === 'Mieszkania') return b.dataset.catFilter === 'Mieszkanie';
        if (groupName === 'Parkowanie') return b.dataset.catFilter.includes('Hala garażowa');
        if (groupName === 'Komórki lokatorskie') return b.dataset.catFilter === 'Komórka';
        return false;
      }});
      if (catBtn) catBtn.click();
    }}

    // --- Trend View Switcher ---
    function switchTrendView(mode) {{
      document.querySelectorAll('.trend-toggle-group .pill-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.trendBtn === mode);
      }});
      const weeksWrap = document.getElementById('trend-view-weeks');
      const daysWrap = document.getElementById('trend-view-days');
      if (weeksWrap && daysWrap) {{
        weeksWrap.style.display = mode === 'weeks' ? '' : 'none';
        daysWrap.style.display = mode === 'days' ? '' : 'none';
      }}
    }}

    // --- Copy Offer Link ---
    function copyOfferLink(event, url) {{
      if (event) {{
        event.preventDefault();
        event.stopPropagation();
      }}
      const btn = event ? event.currentTarget : null;
      if (!url || url === '#' || url === 'None') return;

      const finishCopy = () => {{
        if (btn) {{
          btn.textContent = '✓';
          btn.classList.add('copied');
          btn.title = 'Skopiowano link!';
          setTimeout(() => {{
            btn.textContent = '🔗';
            btn.classList.remove('copied');
            btn.title = 'Kopiuj link do schowka';
          }}, 1800);
        }}
      }};

      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(url).then(finishCopy).catch(() => {{
          fallbackCopy(url);
          finishCopy();
        }});
      }} else {{
        fallbackCopy(url);
        finishCopy();
      }}
    }}

    function fallbackCopy(text) {{
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try {{ document.execCommand('copy'); }} catch(e) {{}}
      document.body.removeChild(ta);
    }}

    // --- Timeline Grouping Switcher ---
    function switchTimelineGrouping(mode) {{
      document.querySelectorAll('.group-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.timelineView === mode);
      }});
      document.querySelectorAll('.timeline-view-panel').forEach(panel => {{
        panel.classList.toggle('active', panel.id === 'timeline-view-' + mode);
      }});
    }}

    // --- Theme Toggle ---
    const themeBtn = document.getElementById('theme-toggle');
    function applyTheme(theme) {{
      document.documentElement.setAttribute('data-theme', theme);
      try {{ localStorage.setItem('theme', theme); }} catch(e) {{}}
      themeBtn.textContent = theme === 'dark' ? '☀️' : '🌓';
    }}
    const savedTheme = (() => {{
      try {{ return localStorage.getItem('theme'); }} catch(e) {{ return null; }}
    }})();
    if (savedTheme) applyTheme(savedTheme);
    themeBtn.addEventListener('click', () => {{
      const current = document.documentElement.getAttribute('data-theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      applyTheme(current === 'dark' ? 'light' : 'dark');
    }});

    // --- Timeline Event Type Filtering ---
    document.querySelectorAll('#timeline-event-filters .pill-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('#timeline-event-filters .pill-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const filterType = btn.dataset.timelineType;

        document.querySelectorAll('.event-item').forEach(item => {{
          if (filterType === 'all' || item.dataset.eventType === filterType) {{
            item.style.display = '';
          }} else {{
            item.style.display = 'none';
          }}
        }});

        // Open timeline groups that have visible items
        document.querySelectorAll('.timeline-group').forEach(group => {{
          const hasVisible = Array.from(group.querySelectorAll('.event-item')).some(i => i.style.display !== 'none');
          if (!hasVisible && filterType !== 'all') {{
            group.style.display = 'none';
          }} else {{
            group.style.display = '';
            if (filterType !== 'all' && hasVisible) group.open = true;
          }}
        }});
      }});
    }});

    // --- Catalog Live Search, Filter & Infinite / Chunking Render ---
    (function() {{
      const rawOffers = JSON.parse(document.getElementById('offers-data').textContent);
      const grid = document.getElementById('catalog-grid');
      const searchInput = document.getElementById('catalog-search');
      const searchClearBtn = document.getElementById('search-clear-btn');
      const sortSelect = document.getElementById('catalog-sort');
      const loadMoreBtn = document.getElementById('load-more-btn');
      const paginationWrap = document.getElementById('pagination-wrap');
      const visibleCountEl = document.getElementById('visible-count');
      const totalCountEl = document.getElementById('total-count');
      const viewModeBtn = document.getElementById('view-mode-toggle');
      const activeFiltersBar = document.getElementById('active-filters-bar');
      const activeFiltersCountEl = document.getElementById('active-filters-count');
      const activeFilterTagsEl = document.getElementById('active-filter-tags');
      const resetFiltersBtn = document.getElementById('reset-filters-btn');

      let currentCat = 'all';
      let currentStatus = 'all';
      let currentPriceFilter = 'all';
      let currentQuery = '';
      let currentSort = 'default';
      let isCompact = false;

      const PAGE_SIZE = 32;
      let displayedCount = PAGE_SIZE;

      viewModeBtn.addEventListener('click', () => {{
        isCompact = !isCompact;
        grid.classList.toggle('compact-mode', isCompact);
        viewModeBtn.textContent = isCompact ? 'Widok: Lista' : 'Widok: Kafelki';
      }});

      function updateActiveFilters() {{
        const chips = [];
        if (currentPriceFilter === 'drops') {{
          chips.push('🔥 Obniżki cen');
        }}
        if (currentCat !== 'all') {{
          const catMap = {{
            'Mieszkanie': 'Mieszkania',
            'Hala garażowa,Miejsce postojowe': 'Parkowanie',
            'Komórka': 'Komórki'
          }};
          chips.push(catMap[currentCat] || currentCat);
        }}
        if (currentStatus !== 'all') {{
          const statusMap = {{
            'available': 'Wolne',
            'reserved': 'Rezerwacja',
            'sold': 'Sprzedane'
          }};
          chips.push(statusMap[currentStatus] || currentStatus);
        }}
        if (currentQuery) {{
          chips.push(`"${{currentQuery}}"`);
        }}

        if (chips.length > 0) {{
          activeFiltersBar.style.display = 'flex';
          activeFiltersCountEl.textContent = chips.length;
          activeFilterTagsEl.innerHTML = chips.map(c => `<span class="active-filter-chip">${{c}}</span>`).join('');
        }} else {{
          activeFiltersBar.style.display = 'none';
        }}

        if (searchClearBtn) {{
          searchClearBtn.style.display = searchInput.value ? 'flex' : 'none';
        }}
      }}

      function filterAndSortOffers() {{
        let list = rawOffers.filter(item => {{
          if (currentPriceFilter === 'drops' && !item.has_drop) {{
            return false;
          }}
          if (currentCat !== 'all') {{
            const allowed = currentCat.split(',');
            if (!allowed.includes(item.cat)) return false;
          }}
          if (currentStatus !== 'all' && item.kind !== currentStatus) {{
            return false;
          }}
          if (currentQuery) {{
            const q = currentQuery.toLowerCase();
            const text = `${{item.cat}} ${{item.unit}} ${{item.group}} ${{item.price}} ${{item.area}} ${{item.rooms}} ${{item.floor}} ${{item.has_drop ? 'obniżka obnizka rabat taniej' : ''}}`.toLowerCase();
            if (!text.includes(q)) return false;
          }}
          return true;
        }});

        if (currentSort === 'drop-desc') {{
          list.sort((a, b) => (a.delta_amt || 0) - (b.delta_amt || 0));
        }} else if (currentSort === 'drop-pct-desc') {{
          list.sort((a, b) => (a.delta_pct || 0) - (b.delta_pct || 0));
        }} else if (currentSort === 'price-asc') {{
          list.sort((a, b) => (a.price_num ?? Infinity) - (b.price_num ?? Infinity));
        }} else if (currentSort === 'price-desc') {{
          list.sort((a, b) => (b.price_num ?? 0) - (a.price_num ?? 0));
        }} else if (currentSort === 'area-desc') {{
          list.sort((a, b) => (b.area_num ?? 0) - (a.area_num ?? 0));
        }} else if (currentSort === 'area-asc') {{
          list.sort((a, b) => (a.area_num ?? Infinity) - (b.area_num ?? Infinity));
        }} else if (currentSort === 'unit-asc') {{
          list.sort((a, b) => (a.cat + a.unit).localeCompare(b.cat + b.unit, undefined, {{ numeric: true }}));
        }}

        return list;
      }}

      function renderCatalog(reset = false) {{
        if (reset) displayedCount = PAGE_SIZE;
        updateActiveFilters();
        const filtered = filterAndSortOffers();
        totalCountEl.textContent = filtered.length;

        const slice = filtered.slice(0, displayedCount);
        visibleCountEl.textContent = slice.length;

        if (slice.length === 0) {{
          grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;">Brak ofert spełniających kryteria.</div>';
          paginationWrap.style.display = 'none';
          return;
        }}

        grid.innerHTML = slice.map(offer => {{
          const metaParts = [];
          if (offer.area) metaParts.push(offer.area + ' m²');
          if (offer.rooms) metaParts.push(offer.rooms + ' pok.');
          if (offer.floor) metaParts.push(offer.floor);
          if (offer.staircase) metaParts.push('kl. ' + offer.staircase);
          const metaText = metaParts.join(' · ') || offer.group;
          const statusLabels = {{ available: 'Wolne', reserved: 'Rezerwacja', sold: 'Sprzedane', unavailable: 'Niedostępne' }};
          const label = statusLabels[offer.kind] || offer.status;

          let priceContent = '';
          if (offer.has_drop || offer.has_rise) {{
            const isDrop = offer.has_drop;
            const deltaStr = Math.abs(offer.delta_amt).toLocaleString('pl-PL');
            const pillCls = isDrop ? 'price-drop-pill' : 'price-rise-pill';
            const sign = isDrop ? '↓ -' : '↑ +';
            const pctStr = Math.abs(offer.delta_pct);
            const tooltipAttr = offer.history_tooltip ? ` title="${{offer.history_tooltip}}"` : '';
            priceContent = `
              <div class="card-price-col">
                <div class="card-price-topline">
                  <span class="card-old-price">${{offer.initial_price}}</span>
                  <span class="${{pillCls}}"${{tooltipAttr}}>${{sign}}${{deltaStr}} zł (${{pctStr}}%)</span>
                </div>
                <strong class="card-price">${{offer.price}}</strong>
              </div>`;
          }} else if (!offer.price && offer.last_known_price) {{
            priceContent = `
              <div class="card-price-col">
                <strong class="card-price price-muted">Cena ukryta</strong>
                <span class="card-last-known">ostatnio: ${{offer.last_known_price}}</span>
              </div>`;
          }} else {{
            priceContent = `<strong class="card-price">${{offer.price || 'Cena niedostępna'}}</strong>`;
          }}

          const recentBadge = offer.recent
            ? '<span class="badge-recent-change" title="Pozycja zmieniła się w ostatnim sprawdzeniu">✦ Ostatnia zmiana</span>'
            : '';
          const copyBtn = `<button class="card-copy-btn" type="button" title="Kopiuj link do schowka" onclick="copyOfferLink(event, '${{offer.url}}')">🔗</button>`;

          return `<a class="flat-card status-border-${{offer.kind}}" href="${{offer.url}}" target="_blank" rel="noreferrer">
            <div class="card-header">
              <div class="card-title-wrap">
                <span class="status-dot dot-${{offer.kind}}" aria-hidden="true"></span>
                <span class="card-unit">${{offer.cat}} ${{offer.unit}}</span>
                ${{recentBadge}}
              </div>
              <div class="card-header-actions">
                ${{copyBtn}}
                <span class="status-pill pill-${{offer.kind}}">${{label}}</span>
              </div>
            </div>
            <div class="card-body">
              <span class="card-meta">${{metaText}}</span>
              <div class="card-price-row">
                ${{priceContent}}
                <span class="card-link-icon" aria-hidden="true">↗</span>
              </div>
            </div>
          </a>`;
        }}).join('');

        paginationWrap.style.display = displayedCount >= filtered.length ? 'none' : 'flex';
      }}

      loadMoreBtn.addEventListener('click', () => {{
        displayedCount += PAGE_SIZE;
        renderCatalog(false);
      }});

      let debounceTimer;
      searchInput.addEventListener('input', e => {{
        if (searchClearBtn) {{
          searchClearBtn.style.display = e.target.value ? 'flex' : 'none';
        }}
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {{
          currentQuery = e.target.value.trim();
          renderCatalog(true);
        }}, 180);
      }});

      if (searchClearBtn) {{
        searchClearBtn.addEventListener('click', () => {{
          searchInput.value = '';
          currentQuery = '';
          searchClearBtn.style.display = 'none';
          renderCatalog(true);
          searchInput.focus();
        }});
      }}

      sortSelect.addEventListener('change', e => {{
        currentSort = e.target.value;
        renderCatalog(true);
      }});

      document.querySelectorAll('#price-filters .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
          document.querySelectorAll('#price-filters .pill-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentPriceFilter = btn.dataset.priceFilter;
          renderCatalog(true);
        }});
      }});

      document.querySelectorAll('#category-filters .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
          document.querySelectorAll('#category-filters .pill-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentCat = btn.dataset.catFilter;
          renderCatalog(true);
        }});
      }});

      document.querySelectorAll('#status-filters .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
          document.querySelectorAll('#status-filters .pill-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentStatus = btn.dataset.statusFilter;
          renderCatalog(true);
        }});
      }});

      if (resetFiltersBtn) {{
        resetFiltersBtn.addEventListener('click', () => {{
          currentPriceFilter = 'all';
          currentCat = 'all';
          currentStatus = 'all';
          currentQuery = '';
          currentSort = 'default';

          document.querySelectorAll('#price-filters .pill-btn').forEach(b => b.classList.toggle('active', b.dataset.priceFilter === 'all'));
          document.querySelectorAll('#category-filters .pill-btn').forEach(b => b.classList.toggle('active', b.dataset.catFilter === 'all'));
          document.querySelectorAll('#status-filters .pill-btn').forEach(b => b.classList.toggle('active', b.dataset.statusFilter === 'all'));
          searchInput.value = '';
          if (searchClearBtn) searchClearBtn.style.display = 'none';
          sortSelect.value = 'default';

          renderCatalog(true);
        }});
      }}

      renderCatalog(true);
    }})();
  </script>
</body>
</html>
"""


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
