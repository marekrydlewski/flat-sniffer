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
    daily_trend_charts,
    plural_events,
    status_kind,
    status_label,
    weekly_trend_charts,
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

        self.assertEqual(status_label("available"), "Wolne")
        self.assertEqual(status_label("reserved"), "Rezerwacja")
        self.assertEqual(status_label("sold"), "Sprzedane")

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


class TestTrendCharts(unittest.TestCase):
    def test_daily_trend_charts_with_history(self):
        now = datetime.now(UTC).isoformat()
        history = [
            {"ts": now, "event": "removed_from_listing", "category": "Mieszkanie", "unit": "1_1"},
            {"ts": now, "event": "removed_from_listing", "category": "Hala garażowa", "unit": "10"},
        ]
        html_out = daily_trend_charts(history)
        self.assertIn("trend-card", html_out)
        self.assertIn("Mieszkania", html_out)

    def test_weekly_trend_charts(self):
        now = datetime.now(UTC).isoformat()
        history = [
            {"ts": now, "event": "removed_from_listing", "category": "Mieszkanie", "unit": "1_1"},
        ]
        html_out = weekly_trend_charts(history, weeks_count=4)
        self.assertIn("trend-card", html_out)
        self.assertIn("col-track", html_out)


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


if __name__ == "__main__":
    unittest.main()
