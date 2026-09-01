"""Render a self-contained, human-friendly availability dashboard."""

import argparse
import html
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

GROUPS = {
    "Mieszkania": {"Mieszkanie"},
    "Parkowanie": {"Hala garażowa", "Miejsce postojowe"},
    "Komórki lokatorskie": {"Komórka"},
}
GONE_RE = re.compile(r"\[GONE\]\*\*\s+(Mieszkanie|Hala garażowa|Komórka|Miejsce postojowe)\s")


def status_kind(status: str) -> str:
    text = status.casefold()
    if "wolne" in text:
        return "available"
    if "rezerw" in text:
        return "reserved"
    if "sprzed" in text:
        return "sold"
    return "unavailable"


def group_name(offer: dict) -> str:
    for name, categories in GROUPS.items():
        if offer["category"] in categories:
            return name
    return offer["category"]


def offer_card(offer: dict) -> str:
    kind = status_kind(offer["status"])
    details = " · ".join(
        item
        for item in (offer.get("area_m2") and f"{offer['area_m2']} m²", offer.get("rooms") and f"{offer['rooms']} pokoje")
        if item
    )
    location = " · ".join(item for item in (offer.get("staircase") and f"klatka {offer['staircase']}", offer.get("floor")) if item)
    return f'''<a class="flat-card {kind}" href="{html.escape(offer['url'], quote=True)}" target="_blank" rel="noreferrer">
      <span class="dot"></span><span><strong>{html.escape(offer['category'])} {html.escape(offer['unit'])}</strong><small>{html.escape(location or details or 'Otwórz ofertę')}</small></span>
      <span class="card-price">{html.escape(offer.get('price') or '')}</span></a>'''


def event_card(event: dict) -> str:
    event_type = event["event"]
    title = {
        "new_listing": "NOWA DOSTĘPNA OFERTA" if status_kind(event.get("status", "")) == "available" else "NOWA OFERTA",
        "status_change": "ZMIANA STATUSU",
        "price_change": "ZMIANA CENY",
        "removed_from_listing": "USUNIĘTO Z OFERTY",
    }.get(event_type, event_type.replace("_", " ").upper())
    if event_type == "status_change":
        summary = f"{event.get('old_status')} → {event.get('new_status')}"
    elif event_type == "price_change":
        summary = f"{event.get('old_price') or '—'} → {event.get('new_price') or '—'}"
    elif event_type == "removed_from_listing":
        summary = "Nie jest już widoczne w ofercie dewelopera"
    else:
        summary = event.get("status", "")
    return f'''<a class="change-card" href="{html.escape(event['url'], quote=True)}" target="_blank" rel="noreferrer">
      <span class="event-label">{html.escape(title)}</span><strong>{html.escape(event['category'])} {html.escape(event['unit'])}</strong>
      <span>{html.escape(event['category'])} · {html.escape(summary)}</span><small>{html.escape(event.get('price') or '')} &nbsp; Otwórz ofertę →</small></a>'''


def changelog(history: list[dict]) -> str:
    cards = []
    dates = []
    for event in reversed(history):
        timestamp = event.get("ts", "")
        label = timestamp[:10] if timestamp else "—"
        if len(label) == 10 and label not in dates:
            dates.append(label)
        cards.append(f'<div class="changelog-item" data-ts="{html.escape(timestamp, quote=True)}"><time>{html.escape(label)}</time>{event_card(event)}</div>')
    body = "".join(cards) or '<p class="empty">Brak zapisanych zmian.</p>'
    options = ['<option value="all">wszystkie dni</option>']
    for day in dates:
        options.append(f'<option value="{html.escape(day, quote=True)}">{html.escape(day)}</option>')
    return f'''<details><summary>Historia zmian ({len(history)} zdarzeń)</summary><label class="range-label">Pokaż zmiany z dnia: <select id="history-day">{"".join(options)}</select></label><div id="changelog">{body}</div></details>'''


def category_summary(offers: list[dict], sold: list[dict]) -> str:
    cards = []
    for name in GROUPS:
        current = [offer for offer in offers if group_name(offer) == name]
        sold_count = sum(group_name(offer) == name for offer in sold)
        counts = Counter(status_kind(offer["status"]) for offer in current)
        total = counts["available"] + counts["reserved"] + sold_count
        segments = "".join(
            f'<span class="status-{kind}" style="width:{count / total * 100 if total else 0:.1f}%" title="{label}: {count}"></span>'
            for kind, label, count in (
                ("available", "Wolne", counts["available"]),
                ("reserved", "Rezerwacje", counts["reserved"]),
                ("sold", "Sprzedane", sold_count),
            )
            if count
        )
        cards.append(
            f'''<article class="category-card"><h3>{html.escape(name)}</h3>
            <div class="status-bar">{segments}</div><div class="category-numbers"><span><b>{counts['available']}</b>wolne</span><span><b>{counts['reserved']}</b>rezerwacje</span><span><b>{sold_count}</b>sprzedane</span></div><small>{total} znanych pozycji</small></article>'''
        )
    return "".join(cards)


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
            counts[day][group_name({"category": category})] += 1

    charts = []
    width, height, padding = 240, 74, 8
    for index, group in enumerate(GROUPS):
        values = [counts[day][group] for day in days]
        maximum = max(max(values), 1)
        points = [
            (
                padding + offset * (width - 2 * padding) / (len(days) - 1),
                height - padding - value * (height - 2 * padding) / maximum,
            )
            for offset, value in enumerate(values)
        ]
        path = " ".join(f"{('M' if offset == 0 else 'L')}{x:.1f},{y:.1f}" for offset, (x, y) in enumerate(points))
        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5"><title>{day.strftime("%d.%m")}: {value}</title></circle>'
            for (x, y), day, value in zip(points, days, values)
            if value
        )
        charts.append(
            f'''<article class="trend-card trend-card-{index}"><div><h3>{html.escape(group)}</h3><b>{sum(values)}</b> zniknięć</div>
            <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(group)}: {sum(values)} zniknięć w ostatnich 21 dniach"><path class="baseline" d="M{padding},{height - padding} H{width - padding}"/><path class="trend-line" d="{path}"/>{dots}</svg>
            <small>{days[0].strftime("%d.%m")} — {days[-1].strftime("%d.%m")}</small></article>'''
        )
    return '<div class="trend-cards">' + "".join(charts) + "</div>"


def render(registry: dict, events: list[dict], sold: list[dict], issues: list[dict], history: list[dict]) -> str:
    offers = sorted(registry.values(), key=lambda o: (o["category"], o["unit"]))
    all_offers = offers + sold
    counts = Counter(status_kind(o["status"]) for o in offers)
    cards = "\n".join(
        f'<section class="group"><h3>{html.escape(name)}</h3><div class="inventory">'
        + "\n".join(offer_card(o) for o in all_offers if group_name(o) == name)
        + "</div></section>"
        for name in GROUPS
    )
    changes = "\n".join(event_card(e) for e in events) or '<p class="empty">Brak zmian od ostatniego sprawdzenia.</p>'
    summaries = category_summary(offers, sold)
    trends = issue_trend_charts(issues)
    full_changelog = changelog(history)
    generated = datetime.now(UTC).strftime("%d.%m.%Y, %H:%M UTC")
    return f'''<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dostępność nieruchomości</title><style>
:root {{ --ink:#202522; --muted:#6a746d; --line:#dde4df; --green:#237a4b; --amber:#b87518; --red:#b34138; --paper:#f7f8f6; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.4 system-ui,-apple-system,sans-serif }}
main {{ max-width:900px; margin:auto; padding:48px 22px 72px }} h1 {{ margin:0; font-size:clamp(2rem,6vw,3.5rem); letter-spacing:-.05em }} .updated {{ color:var(--muted); margin:.4rem 0 2rem }}
.summary {{ display:flex; gap:10px; flex-wrap:wrap; margin:0 0 28px }} .pill {{ background:white; border:1px solid var(--line); border-radius:999px; padding:8px 13px; font-size:.9rem }} .pill b {{ font-size:1.1rem }}
h2 {{ font-size:1.25rem; margin:34px 0 14px }}
.changes {{ display:grid; gap:10px }} .change-card,.flat-card {{ text-decoration:none; color:inherit; background:white; border:1px solid var(--line); border-radius:12px; padding:16px; display:grid; gap:3px; transition:transform .15s,border-color .15s }} .change-card:hover,.flat-card:hover {{ transform:translateY(-1px); border-color:#abb8af }} .event-label {{ color:var(--green); font-size:.72rem; font-weight:750; letter-spacing:.08em }} .change-card span:not(.event-label),small {{ color:var(--muted) }}
.collapsible {{ margin-top:28px; border-top:1px solid var(--line) }} .collapsible summary {{ cursor:pointer; color:var(--ink); font-size:1.25rem; font-weight:700; padding:18px 0; list-style-position:inside }} .collapsible summary:hover {{ color:var(--green) }} .collapsible[open] summary {{ padding-bottom:14px }} .changelog-item {{ display:grid; grid-template-columns:90px 1fr; gap:10px; align-items:start; margin:8px 0 }} .changelog-item time {{ color:var(--muted); font-size:.8rem; padding:16px 0 }} .range-label {{ display:block; color:var(--muted); font-size:.85rem; margin:5px 0 12px }} select {{ border:1px solid var(--line); border-radius:6px; padding:5px; background:white; font:inherit }}
.category-stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px }} .category-card {{ background:white; border:1px solid var(--line); border-radius:12px; padding:15px }} .category-card h3 {{ margin:0 0 12px; font-size:1rem }} .status-bar {{ display:flex; height:12px; overflow:hidden; border-radius:999px; background:#e9eeea; margin:0 0 13px }} .status-bar span {{ min-width:3px }} .status-available {{ background:var(--green) }} .status-reserved {{ background:var(--amber) }} .status-sold {{ background:var(--red) }} .category-numbers {{ display:grid; gap:7px }} .category-numbers span {{ color:var(--muted); font-size:.83rem; display:flex; justify-content:space-between; gap:8px }} .category-numbers b {{ color:var(--ink); font-size:1.15rem }} .category-card small {{ display:block; color:var(--muted); margin-top:10px; font-size:.75rem }}
.trend-cards {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px }} .trend-card {{ padding:14px; background:white; border:1px solid var(--line); border-radius:12px }} .trend-card>div {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px }} .trend-card h3 {{ margin:0; font-size:.95rem }} .trend-card svg {{ display:block; width:100%; height:84px; margin:8px 0 0; overflow:visible }} .trend-card small {{ color:var(--muted); font-size:.75rem }} .baseline {{ stroke:#dfe7e1; stroke-width:1 }} .trend-line {{ fill:none; stroke:var(--red); stroke-width:2.5; stroke-linejoin:round; stroke-linecap:round }} .trend-card circle {{ fill:var(--red); stroke:white; stroke-width:1.5 }} .trend-card-1 .trend-line {{ stroke:#c28724 }} .trend-card-1 circle {{ fill:#c28724 }} .trend-card-2 .trend-line {{ stroke:#7c5ba6 }} .trend-card-2 circle {{ fill:#7c5ba6 }} @media (max-width:650px) {{ .trend-cards {{ grid-template-columns:1fr }} }}
.group {{ margin:0 0 30px }} h3 {{ font-size:1rem; margin:0 0 9px; color:var(--muted) }} .inventory {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px }} .flat-card {{ grid-template-columns:14px 1fr auto; align-items:start }} .flat-card small {{ display:block; margin-top:2px }} .dot {{ width:10px; height:10px; border-radius:50%; margin-top:6px; background:var(--red) }} .available .dot {{ background:var(--green) }} .reserved .dot {{ background:var(--amber) }} .card-price {{ color:var(--muted); font-size:.85rem; text-align:right }} .empty {{ padding:24px; border:1px dashed var(--line); border-radius:12px; color:var(--muted); background:white }}
</style><main><h1>Dostępność nieruchomości</h1><p class="updated">Ostatnia aktualizacja: {generated}</p>
<div class="summary"><span class="pill"><b>{len(events)}</b> zmian</span><span class="pill"><b>{len(offers)}</b> w bieżącej ofercie</span><span class="pill"><b>{counts['available']}</b> wolnych</span><span class="pill"><b>{counts['reserved']}</b> rezerwacji</span><span class="pill"><b>{len(sold)}</b> wykrytych sprzedanych</span></div>
<div class="category-stats">{summaries}</div><p class="updated">Pasek pokazuje udział: <span class="status-available">wolne</span> · <span class="status-reserved">rezerwacje</span> · <span class="status-sold">sprzedane</span>. Sprzedane obejmuje pozycje potwierdzone na stronie dewelopera.</p><section><h2>Od ostatniego sprawdzenia</h2><div class="changes">{changes}</div>{full_changelog}</section><details class="collapsible"><summary>Historia zniknięć z oferty — ostatnie 21 dni</summary>{trends}<p class="updated">Zniknięcie z oferty zwykle oznacza sprzedaż lub wycofanie.</p></details><details class="collapsible"><summary>Pozycje widoczne obecnie na stronie dewelopera</summary>{cards}</details>
</main><script>const day=document.querySelector('#history-day');if(day)day.onchange=()=>{{document.querySelectorAll('.changelog-item').forEach(x=>{{x.hidden=day.value!=='all'&&x.dataset.ts.slice(0,10)!==day.value}})}};</script></html>'''


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
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()] if history_path.exists() else []
    Path(args.out).write_text(render(registry, events, sold, issues, history), encoding="utf-8")


if __name__ == "__main__":
    main()
