"""Unit tests for flat-sniffer components."""

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock

from flat_sniffer import diff_registries
from price_history import (
    PricePoint,
    UnitPriceProfile,
    build_price_history,
    format_amount,
    parse_area_num,
    parse_price_num,
)
from render_dashboard import (
    build_weekly_changes_html,
    event_badge,
    event_row_html,
    plural_events,
    status_kind,
)
from scan_sold import candidates


class TestParsersAndFormatters(unittest.TestCase):
    def test_parse_price_num(self):
        self.assertEqual(parse_price_num("610 944 zł"), 610944)
        self.assertEqual(parse_price_num("12 500,00 zł"), 1250000)  # digits only
        self.assertEqual(parse_price_num("37 500 zł"), 37500)
        self.assertIsNone(parse_price_num(None))
        self.assertIsNone(parse_price_num(""))
        self.assertIsNone(parse_price_num("cena ukryta"))

    def test_parse_area_num(self):
        self.assertEqual(parse_area_num("39,57"), 39.57)
        self.assertEqual(parse_area_num("74.25"), 74.25)
        self.assertIsNone(parse_area_num(None))
        self.assertIsNone(parse_area_num(""))
        self.assertIsNone(parse_area_num("0"))
        self.assertIsNone(parse_area_num("-5.2"))

    def test_format_amount(self):
        self.assertEqual(format_amount(14850), "14 850")
        self.assertEqual(format_amount(-14850), "-14 850")
        self.assertEqual(format_amount(0), "0")
        self.assertEqual(format_amount(None), "")

    def test_status_helpers(self):
        self.assertEqual(status_kind("Wolne"), "available")
        self.assertEqual(status_kind("Rezerwacja"), "reserved")
        self.assertEqual(status_kind("Sprzedane"), "sold")
        self.assertEqual(status_kind("Inne"), "unavailable")

    def test_plural_events(self):
        self.assertEqual(plural_events(1), "1 zdarzenie")
        self.assertEqual(plural_events(2), "2 zdarzenia")
        self.assertEqual(plural_events(4), "4 zdarzenia")
        self.assertEqual(plural_events(5), "5 zdarzeń")
        self.assertEqual(plural_events(11), "11 zdarzeń")
        self.assertEqual(plural_events(12), "12 zdarzeń")
        self.assertEqual(plural_events(14), "14 zdarzeń")
        self.assertEqual(plural_events(22), "22 zdarzenia")
        self.assertEqual(plural_events(25), "25 zdarzeń")

    def test_event_badge(self):
        self.assertEqual(event_badge("new_listing", "Wolne"), ("badge-new", "Nowa oferta"))
        self.assertEqual(event_badge("new_listing", "Rezerwacja"), ("badge-new", "Nowa pozycja"))
        self.assertEqual(event_badge("status_change"), ("badge-status", "Zmiana statusu"))
        self.assertEqual(event_badge("price_change"), ("badge-price", "Zmiana ceny"))
        self.assertEqual(event_badge("removed_from_listing", is_sold=False), ("badge-removed", "Zniknęło z oferty"))
        self.assertEqual(event_badge("removed_from_listing", is_sold=True), ("badge-sold", "Sprzedane"))

    def test_event_row_html_sold_and_removed(self):
        event_flat = {
            "event": "removed_from_listing",
            "category": "Mieszkanie",
            "unit": "34_27",
            "last_status": "Rezerwacja",
            "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-LM-34_27",
        }
        html_flat = event_row_html(event_flat)
        self.assertIn("badge-sold", html_flat)
        self.assertIn("Sprzedane", html_flat)
        self.assertIn("Rezerwacja", html_flat)
        self.assertIn("diff-arrow", html_flat)
        self.assertNotIn("prawdopodobnie", html_flat)
        self.assertNotIn("Zniknęło z oferty", html_flat)

        event_other = {
            "event": "removed_from_listing",
            "category": "Komórka",
            "unit": "KL17",
            "last_status": "Wolne",
            "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-KL17",
        }
        html_other = event_row_html(event_other)
        self.assertIn("badge-removed", html_other)
        self.assertIn("Zniknęło z oferty", html_other)
        self.assertIn("Usunięto z oferty (było: Wolne)", html_other)
        self.assertNotIn("prawdopodobnie sprzedane", html_other)

        html_other_sold = event_row_html(
            event_other,
            sold_urls={"https://swietegomichala.pl/pl/mieszkanie/SM2-KL17"},
        )
        self.assertIn("badge-sold", html_other_sold)
        self.assertIn("Sprzedane", html_other_sold)


class TestPriceHistory(unittest.TestCase):
    def test_relisting_preserves_initial_price(self):
        events = [
            {
                "ts": "2026-08-13T07:36:01.851740+00:00",
                "event": "new_listing",
                "category": "Komórka",
                "unit": "KL19",
                "status": "Wolne",
                "price": "13 000 zł",
            },
            {
                "ts": "2026-10-01T10:00:00+00:00",
                "event": "price_change",
                "category": "Komórka",
                "unit": "KL19",
                "old_price": "13 000 zł",
                "new_price": "15 000 zł",
            },
            {
                "ts": "2026-10-16T10:00:00+00:00",
                "event": "removed_from_listing",
                "category": "Komórka",
                "unit": "KL19",
                "price": "15 000 zł",
            },
            {
                "ts": "2026-10-21T10:00:00+00:00",
                "event": "new_listing",
                "category": "Komórka",
                "unit": "KL19",
                "status": "Rezerwacja",
                "price": None,
            },
        ]
        profiles = build_price_history(events)
        p = profiles[("Komórka", "KL19")]
        self.assertEqual(p.initial_price, "13 000 zł")
        self.assertEqual(p.initial_price_num, 13000)
        self.assertEqual(p.last_known_price, "15 000 zł")
        self.assertEqual(p.last_known_price_num, 15000)

    def test_unmasked_price_sets_initial_price_if_missing(self):
        events = [
            {
                "ts": "2026-08-13T07:36:01+00:00",
                "event": "new_listing",
                "category": "Mieszkanie",
                "unit": "99_1",
                "status": "Rezerwacja",
                "price": None,
            },
            {
                "ts": "2026-09-01T12:00:00+00:00",
                "event": "price_change",
                "category": "Mieszkanie",
                "unit": "99_1",
                "old_price": None,
                "new_price": "500 000 zł",
            },
        ]
        profiles = build_price_history(events)
        p = profiles[("Mieszkanie", "99_1")]
        self.assertEqual(p.initial_price, "500 000 zł")
        self.assertEqual(p.initial_price_num, 500000)
        self.assertEqual(p.current_price, "500 000 zł")

    def test_history_tooltip(self):
        p = UnitPriceProfile(category="Mieszkanie", unit="1_1", initial_price="500 000 zł")
        self.assertEqual(p.history_tooltip, "Cena od początku: 500 000 zł")

        p.timeline.append(
            PricePoint(date="2026-08-01", timestamp="", price="500 000 zł", price_num=500000, event="new_listing")
        )
        p.timeline.append(
            PricePoint(date="2026-08-15", timestamp="", price=None, price_num=None, event="price_change_masked")
        )
        p.timeline.append(
            PricePoint(
                date="2026-09-01",
                timestamp="",
                price="490 000 zł",
                price_num=490000,
                event="price_change_adjustment_after_masked",
            )
        )
        # price_changes list must be non-empty for property to format timeline
        p.price_changes.append(MagicMock())
        self.assertIn("2026-08-01: 500 000 zł", p.history_tooltip)
        self.assertIn("2026-08-15: cena ukryta", p.history_tooltip)
        self.assertIn("2026-09-01: 490 000 zł", p.history_tooltip)


class TestDiffRegistries(unittest.TestCase):
    def test_diff_detects_all_event_types(self):
        old = {
            "1": {"category": "Mieszkanie", "unit": "1", "status": "Wolne", "price": "500 000 zł", "url": "/1"},
            "2": {"category": "Mieszkanie", "unit": "2", "status": "Wolne", "price": "600 000 zł", "url": "/2"},
            "3": {"category": "Hala garażowa", "unit": "3", "status": "Wolne", "price": "40 000 zł", "url": "/3"},
        }
        new = {
            # "1" removed
            "2": {
                "category": "Mieszkanie",
                "unit": "2",
                "status": "Rezerwacja",
                "price": "600 000 zł",
                "url": "/2",
            },  # status change
            "3": {
                "category": "Hala garażowa",
                "unit": "3",
                "status": "Wolne",
                "price": "38 000 zł",
                "url": "/3",
            },  # price drop
            "4": {
                "category": "Komórka",
                "unit": "KL1",
                "status": "Wolne",
                "price": "15 000 zł",
                "url": "/4",
            },  # new listing
        }
        events = diff_registries(old, new)
        events_by_type = {e["event"]: e for e in events}

        self.assertIn("removed_from_listing", events_by_type)
        self.assertEqual(events_by_type["removed_from_listing"]["id"], "1")

        self.assertIn("status_change", events_by_type)
        self.assertEqual(events_by_type["status_change"]["id"], "2")
        self.assertEqual(events_by_type["status_change"]["new_status"], "Rezerwacja")

        self.assertIn("price_change", events_by_type)
        self.assertEqual(events_by_type["price_change"]["id"], "3")
        self.assertEqual(events_by_type["price_change"]["delta_amount"], -2000)
        self.assertEqual(events_by_type["price_change"]["change_type"], "adjustment")

        self.assertIn("new_listing", events_by_type)
        self.assertEqual(events_by_type["new_listing"]["id"], "4")

    def test_text_change_detection(self):
        old = {"1": {"category": "Mieszkanie", "unit": "1", "status": "Wolne", "price": "Zapytaj o cenę", "url": "/1"}}
        new = {"1": {"category": "Mieszkanie", "unit": "1", "status": "Wolne", "price": "Cena w biurze", "url": "/1"}}
        events = diff_registries(old, new)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "price_change")
        self.assertEqual(events[0]["change_type"], "text_change")

    def test_text_change_price_history_projection(self):
        events = [
            {
                "ts": "2026-08-01T10:00:00+00:00",
                "event": "new_listing",
                "category": "Mieszkanie",
                "unit": "1",
                "price": "Zapytaj o cenę",
            },
            {
                "ts": "2026-08-02T10:00:00+00:00",
                "event": "price_change",
                "category": "Mieszkanie",
                "unit": "1",
                "old_price": "Zapytaj o cenę",
                "new_price": "Cena w biurze",
                "change_type": "text_change",
            },
        ]
        profiles = build_price_history(events)
        p = profiles[("Mieszkanie", "1")]
        self.assertEqual(len(p.price_changes), 1)
        self.assertEqual(p.price_changes[0].change_type, "text_change")
        self.assertIsNone(p.price_changes[0].delta_pct)
        self.assertIsNone(p.price_changes[0].delta_amount)


class TestWeeklyChanges(unittest.TestCase):
    def test_build_weekly_changes_html(self):
        now = datetime.now(UTC).isoformat()
        history = [
            {"ts": now, "event": "removed_from_listing", "category": "Mieszkanie", "unit": "1_1"},
            {
                "ts": now,
                "event": "status_change",
                "category": "Mieszkanie",
                "unit": "1_2",
                "old_status": "Wolne",
                "new_status": "Rezerwacja",
            },
        ]
        html_out = build_weekly_changes_html(history, weeks_count=4)
        self.assertIn('<details class="week-card" open', html_out)
        self.assertIn("chip-sold", html_out)
        self.assertIn("chip-res", html_out)
        self.assertIn("Mieszkanie 1_1", html_out)
        self.assertIn("Mieszkanie 1_2", html_out)

    def test_build_weekly_changes_html_empty(self):
        self.assertEqual(
            build_weekly_changes_html([]),
            '<div class="empty-state">Brak zarejestrowanych zmian w historii.</div>',
        )

    def test_event_row_html(self):
        event = {
            "category": "Mieszkanie",
            "unit": "34_1",
            "event": "price_change",
            "old_price": "600 000 zł",
            "new_price": "580 000 zł",
            "url": "https://example.com/34_1",
        }
        row = event_row_html(event)
        self.assertIn("week-event-row", row)
        self.assertIn("Mieszkanie 34_1", row)
        self.assertIn("Zmiana ceny", row)
        self.assertIn("diff-old", row)
        self.assertIn("diff-arrow", row)
        self.assertIn("diff-new", row)
        self.assertIn("delta-drop", row)
        self.assertIn("-20 000 zł (-3.3%)", row)
        self.assertIn("event-link-btn", row)


class TestCandidatesGapScanning(unittest.TestCase):
    def test_candidates_finds_gaps_and_excludes_active(self):
        registry = {
            "1": {"category": "Mieszkanie", "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-1"},
            "3": {"category": "Mieszkanie", "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-3"},
        }
        res = candidates(registry)
        self.assertIn("https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2", res)
        self.assertNotIn("https://swietegomichala.pl/pl/mieszkanie/SM2-A1-1", res)
        self.assertNotIn("https://swietegomichala.pl/pl/mieszkanie/SM2-A1-3", res)

    def test_candidates_includes_history_removed_urls(self):
        registry = {
            "1": {"category": "Mieszkanie", "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-1"},
        }
        history = [
            {
                "event": "removed_from_listing",
                "category": "Komórka",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-KL14",
            }
        ]
        res = candidates(registry, history=history)
        self.assertIn("https://swietegomichala.pl/pl/mieszkanie/SM2-KL14", res)

    def test_urls_to_probe_skips_complete_previous(self):
        from scan_sold import urls_to_probe

        registry = {
            "1": {"category": "Mieszkanie", "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-1"},
            "3": {"category": "Mieszkanie", "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-3"},
        }
        previous: dict[str, dict[str, str | None]] = {
            "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2": {
                "category": "Mieszkanie",
                "unit": "2",
                "status": "Sprzedane",
                "price": "500 000 zł",
                "area_m2": "40,0",
                "price_per_m2": "12 500 zł / m²",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2",
            }
        }
        to_probe = urls_to_probe(registry, previous)
        self.assertEqual(len(to_probe), 0)

        # refresh_all=True forces probing all candidates
        to_probe_all = urls_to_probe(registry, previous, refresh_all=True)
        self.assertIn("https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2", to_probe_all)

        # If price is missing, it SHOULD be probed
        previous["https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2"]["price"] = None
        to_probe = urls_to_probe(registry, previous)
        self.assertIn("https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2", to_probe)

        # Non-flat (Hala garażowa) with price and no area does not need area/price_per_m2
        previous_garage: dict[str, dict[str, str | None]] = {
            "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2": {
                "category": "Hala garażowa",
                "unit": "2",
                "status": "Sprzedane",
                "price": "40 000 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-2",
            }
        }
        to_probe_garage = urls_to_probe(registry, previous_garage)
        self.assertEqual(len(to_probe_garage), 0)


class TestSoldOfferMetadataParsing(unittest.TestCase):
    def test_metadata_regexes(self):
        from scan_sold import AREA_RE, FLOOR_RE, ROOMS_RE, STAIRCASE_RE

        sample_html = """
        Klatka 34, piętro 2
        <table class="offers-data">
            <tr><td>Powierzchnia</td><th class="text-right">43,02 m<sup>2</sup></th></tr>
            <tr><td>Pokoje</td><th class="text-right">2</th></tr>
        </table>
        """
        area = AREA_RE.search(sample_html)
        rooms = ROOMS_RE.search(sample_html)
        floor = FLOOR_RE.search(sample_html)
        staircase = STAIRCASE_RE.search(sample_html)

        self.assertIsNotNone(area)
        assert area is not None
        self.assertEqual(area.group(1), "43,02")
        self.assertIsNotNone(rooms)
        assert rooms is not None
        self.assertEqual(rooms.group(1), "2")
        self.assertIsNotNone(floor)
        assert floor is not None
        self.assertEqual(floor.group(1), "2")
        self.assertIsNotNone(staircase)
        assert staircase is not None
        self.assertEqual(staircase.group(1), "34")

    def test_metadata_regexes_edge_cases(self):
        from scan_sold import AREA_RE, FLOOR_RE, ROOMS_RE, STAIRCASE_RE

        # Parter, unicode m², and alphanumeric staircase
        html_parter = "Klatka 38A, piętro Parter Powierzchnia </td> <th>52.5 m²</th> Pokoje </td> <th>3</th>"
        area = AREA_RE.search(html_parter)
        rooms = ROOMS_RE.search(html_parter)
        floor = FLOOR_RE.search(html_parter)
        staircase = STAIRCASE_RE.search(html_parter)

        self.assertIsNotNone(area)
        assert area is not None
        self.assertEqual(area.group(1), "52.5")
        self.assertIsNotNone(rooms)
        assert rooms is not None
        self.assertEqual(rooms.group(1), "3")
        self.assertIsNotNone(floor)
        assert floor is not None
        self.assertEqual(floor.group(1).casefold(), "parter")
        self.assertIsNotNone(staircase)
        assert staircase is not None
        self.assertEqual(staircase.group(1), "38A")

        # Underground floor (pietro -1)
        html_underground = "pietro -1"
        floor_neg = FLOOR_RE.search(html_underground)
        self.assertIsNotNone(floor_neg)
        assert floor_neg is not None
        self.assertEqual(floor_neg.group(1), "-1")


class TestDashboardP1Improvements(unittest.TestCase):
    def test_build_compact_offers_json_includes_crm_url(self):
        from render_dashboard import build_compact_offers_json

        offers = [
            {
                "id": "102",
                "category": "Mieszkanie",
                "unit": "36_1",
                "status": "Wolne",
                "status_kind": "available",
                "price": "526 281 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A2-LM-36_01",
                "crm_url": "https://crm.konimpex-invest.pl/scripts/ShowProduct.ashx?key=123",
            }
        ]
        compact = build_compact_offers_json(offers)
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["crm_url"], "https://crm.konimpex-invest.pl/scripts/ShowProduct.ashx?key=123")

    def test_normalize_offers_deduplicates_relisted_sold(self):
        from render_dashboard import normalize_offers

        registry = {
            "102": {
                "category": "Mieszkanie",
                "unit": "36_1",
                "status": "Wolne",
                "price": "526 281 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A2-LM-36_01",
            }
        }
        sold = [
            {
                "category": "Mieszkanie",
                "unit": "36_1",
                "status": "Sprzedane",
                "price": "526 281 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A2-LM-36_01",
            },
            {
                "category": "Mieszkanie",
                "unit": "34_99",
                "status": "Sprzedane",
                "price": "600 000 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A1-LM-34_99",
            },
        ]
        history = []
        offers, normalized_sold, all_offers = normalize_offers(registry, sold, history)
        # 36_1 must NOT appear in normalized_sold because it is active in registry
        self.assertEqual(len(offers), 1)
        self.assertEqual(len(normalized_sold), 1)
        self.assertEqual(normalized_sold[0]["unit"], "34_99")
        self.assertEqual(len(all_offers), 2)
        units = [o["unit"] for o in all_offers]
        self.assertEqual(units.count("36_1"), 1)
        self.assertEqual(units.count("34_99"), 1)

    def test_render_without_events(self):
        from render_dashboard import render

        registry = {
            "102": {
                "category": "Mieszkanie",
                "unit": "36_1",
                "status": "Wolne",
                "price": "526 281 zł",
                "url": "https://swietegomichala.pl/pl/mieszkanie/SM2-A2-LM-36_01",
                "crm_url": "https://crm.konimpex-invest.pl/scripts/ShowProduct.ashx?key=123",
            }
        }
        sold = []
        history = []
        output = render(registry, sold, history)
        self.assertIn("<!doctype html>", output)
        self.assertIn("Rzut PDF", output)
        self.assertIn("36_1", output)


class TestDashboardP2Improvements(unittest.TestCase):
    def test_normalize_offers_extracts_staircase_for_flats(self):
        from render_dashboard import normalize_offers

        registry = {
            "1": {
                "category": "Mieszkanie",
                "unit": "34_12",
                "status": "Wolne",
                "url": "/1",
            },
            "2": {
                "category": "Mieszkanie",
                "unit": "38_5",
                "status": "Rezerwacja",
                "staircase": "38",  # already present
                "url": "/2",
            },
            "3": {
                "category": "Komórka",
                "unit": "KL12",
                "status": "Wolne",
                "url": "/3",
            },
        }
        sold = [
            {
                "category": "Mieszkanie",
                "unit": "40_3",
                "status": "Sprzedane",
                "url": "/4",
            }
        ]
        _offers, _normalized_sold, all_offers = normalize_offers(registry, sold, [])
        by_unit = {o["unit"]: o for o in all_offers}
        self.assertEqual(by_unit["34_12"]["staircase"], "34")
        self.assertEqual(by_unit["38_5"]["staircase"], "38")
        self.assertEqual(by_unit["40_3"]["staircase"], "40")
        self.assertIsNone(by_unit["KL12"].get("staircase"))

    def test_build_compact_offers_json_preserves_staircase(self):
        from render_dashboard import build_compact_offers_json

        offers = [
            {
                "id": "1",
                "category": "Mieszkanie",
                "unit": "36_2",
                "staircase": "36",
                "status": "Wolne",
            }
        ]
        compact = build_compact_offers_json(offers)
        self.assertEqual(compact[0]["staircase"], "36")


class TestTemplatesIntegrity(unittest.TestCase):
    def test_app_js_syntax_via_node(self):
        import shutil
        import subprocess
        from pathlib import Path

        node_path = shutil.which("node")
        if not node_path:
            self.skipTest("node is not installed")

        templates_dir = Path(__file__).resolve().parent.parent / "templates"
        res = subprocess.run(
            [node_path, "--check", str(templates_dir / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"app.js syntax error: {res.stderr}")


class TestScanSoldDeduplication(unittest.TestCase):
    def test_active_offer_indices(self):
        from scan_sold import active_offer_indices

        registry = {
            "https://example.com/flat1": {"url": "https://example.com/flat1", "category": "Mieszkanie", "unit": "A.1"},
            "https://example.com/garage1": {"url": "https://example.com/garage1", "category": "Garaż", "unit": "G-01"},
            "https://example.com/incomplete": {"url": "https://example.com/incomplete"},
        }
        urls, keys = active_offer_indices(registry)
        self.assertEqual(
            urls, {"https://example.com/flat1", "https://example.com/garage1", "https://example.com/incomplete"}
        )
        self.assertEqual(keys, {("Mieszkanie", "A.1"), ("Garaż", "G-01")})

    def test_retained_sold_omits_relisted_active(self):
        from scan_sold import active_offer_indices

        registry = {
            "https://example.com/new-flat-url": {
                "url": "https://example.com/new-flat-url",
                "category": "Mieszkanie",
                "unit": "A.1",
                "status": "Dostępne",
            }
        }
        active_urls, active_keys = active_offer_indices(registry)
        previous = {
            "https://example.com/old-sold-url": {
                "url": "https://example.com/old-sold-url",
                "category": "Mieszkanie",
                "unit": "A.1",
                "status": "Sprzedane",
            },
            "https://example.com/still-sold-url": {
                "url": "https://example.com/still-sold-url",
                "category": "Mieszkanie",
                "unit": "B.2",
                "status": "Sprzedane",
            },
        }
        retained = [
            offer
            for url, offer in previous.items()
            if url not in active_urls and (offer.get("category"), offer.get("unit")) not in active_keys
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["unit"], "B.2")


class TestUnifiedDataExtraction(unittest.TestCase):
    def test_derive_staircase(self):
        from flat_sniffer import derive_staircase

        self.assertEqual(derive_staircase("34_12", "Mieszkanie"), "34")
        self.assertEqual(derive_staircase("36_1", "Mieszkanie"), "36")
        self.assertEqual(derive_staircase("38_10"), "38")
        self.assertIsNone(derive_staircase("G-01", "Garaż"))
        self.assertIsNone(derive_staircase("KL1", "Komórka"))
        self.assertIsNone(derive_staircase("single"))
        self.assertIsNone(derive_staircase(None))

    def test_extract_floor(self):
        from flat_sniffer import extract_floor

        self.assertEqual(extract_floor(raw_floor="parter"), "Parter")
        self.assertEqual(extract_floor(raw_floor="PARTER"), "Parter")
        self.assertEqual(extract_floor(raw_floor="3"), "Piętro 3")
        self.assertEqual(extract_floor(raw_floor="Piętro 4"), "Piętro 4")
        self.assertEqual(extract_floor(extras=["Balkon", "Piętro 2"]), "Piętro 2")
        self.assertEqual(extract_floor(extras=["Ogródek", "Parter"]), "Parter")
        self.assertEqual(extract_floor(extras=["parter"]), "Parter")
        self.assertIsNone(extract_floor(extras=["Balkon", "Aneks"]))
        self.assertIsNone(extract_floor())

    def test_enrich_offer_metadata(self):
        from flat_sniffer import enrich_offer_metadata

        flat = {
            "category": "Mieszkanie",
            "unit": "34_05",
            "extras": ["Balkon", "Piętro 1"],
        }
        enrich_offer_metadata(flat)
        self.assertEqual(flat["staircase"], "34")
        self.assertEqual(flat["floor"], "Piętro 1")

        # Does not overwrite existing attributes
        flat2 = {
            "category": "Mieszkanie",
            "unit": "34_05",
            "staircase": "Custom",
            "floor": "Custom Floor",
            "extras": ["Parter"],
        }
        enrich_offer_metadata(flat2)
        self.assertEqual(flat2["staircase"], "Custom")
        self.assertEqual(flat2["floor"], "Custom Floor")

        # Non-flat ignored
        garage = {"category": "Garaż", "unit": "34_G1"}
        enrich_offer_metadata(garage)
        self.assertNotIn("staircase", garage)
        self.assertNotIn("floor", garage)

    def test_scan_sold_extras_and_staircase_derivation(self):
        from unittest.mock import MagicMock

        from scan_sold import fetch_sold

        html = """
        <h2 class="h1">Mieszkanie 36_09</h2>
        <span class="text-danger text-uppercase">Sprzedane</span>
        <h4 class="mb-0 text-black">650 000 zł</h4>
        <table class="offers-data">
            <tr><td>Powierzchnia</td><th class="text-right">50,00 m<sup>2</sup></th></tr>
            <tr><td>Pokoje</td><th class="text-right">2</th></tr>
            <tr><td>Balkon</td><th class="text-right">5,2 m<sup>2</sup></th></tr>
            <tr><td>Ogród</td><th class="text-right">20 m<sup>2</sup></th></tr>
        </table>
        piętro 2
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        offer = fetch_sold("https://example.com/flat", client=mock_client)
        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer["category"], "Mieszkanie")
        self.assertEqual(offer["unit"], "36_09")
        self.assertEqual(offer["staircase"], "36")
        self.assertEqual(offer["floor"], "Piętro 2")
        self.assertEqual(sorted(offer.get("extras", [])), ["Balkon", "Ogród"])


class TestPriceCaching(unittest.TestCase):
    def test_build_price_cache_in_scan_sold(self):
        from scan_sold import build_price_cache

        registry = {
            "1": {
                "url": "https://example.com/1",
                "category": "Mieszkanie",
                "unit": "34_1",
                "price": "500 000 zł",
                "price_per_m2": "10 000 zł/m²",
                "staircase": "34",
                "floor": "Parter",
                "extras": ["Ogródek"],
            }
        }
        history = [
            {
                "url": "https://example.com/2",
                "category": "Mieszkanie",
                "unit": "36_2",
                "price": "600 000 zł",
            },
            {
                "url": "https://example.com/changed",
                "category": "Mieszkanie",
                "unit": "40_5",
                "event": "price_change",
                "old_price": "800 000 zł",
                "new_price": "790 000 zł",
            },
        ]
        previous = {
            "https://example.com/3": {
                "category": "Mieszkanie",
                "unit": "38_3",
                "price": "700 000 zł",
            }
        }

        cache = build_price_cache(registry, previous=previous, history=history)
        self.assertEqual(cache["https://example.com/1"]["price"], "500 000 zł")
        self.assertEqual(cache[("Mieszkanie", "34_1")]["staircase"], "34")
        self.assertEqual(cache["https://example.com/2"]["price"], "600 000 zł")
        self.assertEqual(cache[("Mieszkanie", "36_2")]["price"], "600 000 zł")
        self.assertEqual(cache["https://example.com/changed"]["price"], "790 000 zł")
        self.assertEqual(cache[("Mieszkanie", "40_5")]["price"], "790 000 zł")
        self.assertEqual(cache["https://example.com/3"]["price"], "700 000 zł")

    def test_flat_sniffer_fetch_all_uses_cached_price(self):
        from unittest.mock import patch

        from flat_sniffer import fetch_all

        mock_registry_html = """
        <a class="target-row border-success " href="/pl/mieszkanie/100" data-id="100" data-pdf="">
            <div class="text-uppercase">Rezerwacja</div>
            <div class="h4 fs-20 m-0 text-dark">Mieszkanie</div>
            <div class="h4 fs-20 text-primary">34_15</div>
        </a>
        """
        old_reg = {
            "100": {
                "id": "100",
                "status": "Rezerwacja",
                "price": "550 000 zł",
                "price_per_m2": "12 000 zł/m²",
                "category": "Mieszkanie",
                "unit": "34_15",
                "url": "/offer/100",
            }
        }

        with (
            patch("flat_sniffer.fetch", return_value=mock_registry_html),
            patch("flat_sniffer.fetch_offer_price") as mock_fetch_price,
        ):
            # With price caching: fetch_offer_price should NOT be called
            reg, _ = fetch_all(old_registry=old_reg, refresh_prices=False)
            self.assertEqual(reg["100"]["price"], "550 000 zł")
            self.assertEqual(reg["100"]["price_per_m2"], "12 000 zł/m²")
            mock_fetch_price.assert_not_called()

            # With refresh_prices=True: fetch_offer_price SHOULD be called
            mock_fetch_price.return_value = ("560 000 zł", "12 200 zł/m²")
            reg_refreshed, _ = fetch_all(old_registry=old_reg, refresh_prices=True)
            mock_fetch_price.assert_called_once()
            self.assertEqual(reg_refreshed["100"]["price"], "560 000 zł")


class TestBugFixes(unittest.TestCase):
    def test_extract_floor_underground(self):
        from flat_sniffer import extract_floor

        self.assertEqual(extract_floor("-1"), "Piętro -1")
        self.assertEqual(extract_floor("0"), "Piętro 0")
        self.assertEqual(extract_floor("parter"), "Parter")
        self.assertEqual(extract_floor("1"), "Piętro 1")
        self.assertEqual(extract_floor("Piętro -1"), "Piętro -1")

    def test_build_price_cache_preserves_detected_at(self):
        from scan_sold import build_price_cache

        history = [
            {
                "url": "https://example.com/hist",
                "category": "Mieszkanie",
                "unit": "34_9",
                "price": "500 000 zł",
                "ts": "2026-08-01T10:00:00+00:00",
            }
        ]
        previous = {
            "https://example.com/prev": {
                "category": "Mieszkanie",
                "unit": "34_8",
                "price": "450 000 zł",
                "detected_at": "2026-08-15T12:00:00+00:00",
            }
        }
        cache = build_price_cache(registry={}, previous=previous, history=history)
        # Event ts must NOT be treated as detected_at
        self.assertNotIn("detected_at", cache.get("https://example.com/hist", {}))
        self.assertEqual(cache["https://example.com/prev"]["detected_at"], "2026-08-15T12:00:00+00:00")

    def test_app_js_floor_and_sorting_logic(self):
        import shutil
        import subprocess
        from pathlib import Path

        node_path = shutil.which("node")
        if not node_path:
            self.skipTest("node is not installed")

        script = """
        const fs = require('fs');
        const code = fs.readFileSync(process.argv[1], 'utf-8');
        // Extract parseFloorNum from app.js
        const fnMatch = code.match(/function parseFloorNum\\([\\s\\S]*?\\n  \\}/);
        if (!fnMatch) { console.error('parseFloorNum not found'); process.exit(1); }
        eval(fnMatch[0]);

        if (parseFloorNum('Piętro -1') !== -1) { console.error('P -1 != -1'); process.exit(1); }
        if (parseFloorNum('Parter') !== 0) { console.error('Parter != 0'); process.exit(1); }
        if (parseFloorNum('Piętro 1') !== 1) { console.error('P 1 != 1'); process.exit(1); }
        if (parseFloorNum('Piętro 3') !== 3) { console.error('P 3 != 3'); process.exit(1); }
        if (parseFloorNum(null) !== -999) { console.error('null != -999'); process.exit(1); }
        """
        templates_dir = Path(__file__).resolve().parent.parent / "templates"
        res = subprocess.run(
            [node_path, "-e", script, str(templates_dir / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"Floor parsing validation failed: {res.stderr}")


if __name__ == "__main__":
    unittest.main()
