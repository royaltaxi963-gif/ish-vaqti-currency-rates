"""Parser tests: bank identity, currencies, buy/sell, cash/mobile, layout drift."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.bank_parsers import (
    LayoutError,
    parse_bankuz,
    parse_brb,
    parse_davr,
    parse_source,
    parse_mkbank_json,
    parse_sqb,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class BankUzTests(unittest.TestCase):
    def test_buy_and_sell_separated(self):
        rates = parse_bankuz(fixture("bankuz_asaka.html"), NOW)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11950.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 11990.0)

    def test_rates_are_cash_kind(self):
        rates = parse_bankuz(fixture("bankuz_asaka.html"), NOW)
        self.assertEqual(set(rates["USD"]), {"cash"})

    def test_zero_buy_becomes_null_not_zero(self):
        rates = parse_bankuz(fixture("bankuz_asaka.html"), NOW)
        self.assertIsNone(rates["RUB"]["cash"]["buy"])
        self.assertEqual(rates["RUB"]["cash"]["sell"], 145.0)

    def test_published_timestamp_preserved(self):
        rates = parse_bankuz(fixture("bankuz_asaka.html"), NOW)
        self.assertTrue(rates["USD"]["cash"]["published_at"].startswith("2026-11-12T16:56"))

    def test_layout_change_raises(self):
        with self.assertRaises(LayoutError):
            parse_bankuz("<html><body>no table here</body></html>", NOW)

    def test_unrelated_currency_ignored(self):
        page = fixture("bankuz_asaka.html").replace("flag-us", "flag-jp").replace("USD", "JPY")
        rates = parse_bankuz(page, NOW)
        self.assertNotIn("JPY", rates)
        self.assertIn("RUB", rates)


class SqbTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(fixture("sqb_api.json"))

    def test_offline_is_cash_and_scaled(self):
        rates = parse_sqb(self.payload)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11930.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12020.0)

    def test_online_is_mobile_and_not_scaled(self):
        rates = parse_sqb(self.payload)
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11940.0)
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12010.0)

    def test_atm_fills_mobile_only_when_absent(self):
        rates = parse_sqb(self.payload)
        # online USD is present, so the ATM row must not overwrite it.
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11940.0)

    def test_zero_buy_dropped(self):
        rates = parse_sqb(self.payload)
        self.assertIsNone(rates["RUB"]["cash"]["buy"])

    def test_unsupported_group_ignored(self):
        rates = parse_sqb(self.payload)
        self.assertNotIn("juridic", json.dumps(rates))

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_sqb({"data": "nope"})


class BrbTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(fixture("brb_api.json"))

    def test_scaled_values(self):
        rates = parse_brb(self.payload)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11945.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12030.0)

    def test_mobil_row_is_mobile(self):
        rates = parse_brb(self.payload)
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12010.0)

    def test_unsupported_currency_ignored(self):
        rates = parse_brb(self.payload)
        self.assertNotIn("TJS", rates)

    def test_published_timestamp_preserved(self):
        rates = parse_brb(self.payload)
        self.assertTrue(rates["USD"]["cash"]["published_at"].startswith("2026-11-12T21:38"))

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_brb({"data": None})


class DavrTests(unittest.TestCase):
    def test_cash_table(self):
        rates = parse_davr(fixture("davr_rate.html"),
                           ("Bank ofislarida valyutalar kursi",), NOW)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11910.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12020.0)

    def test_mobile_table_separated(self):
        rates = parse_davr(fixture("davr_rate.html"),
                           ("Mobil ilovada valyutalar kursi",), NOW)
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11920.0)
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12010.0)
        self.assertNotIn("cash", rates["USD"])

    def test_zero_rows_dropped(self):
        rates = parse_davr(fixture("davr_rate.html"),
                           ("Bank ofislarida valyutalar kursi",), NOW)
        self.assertNotIn("RUB", rates)

    def test_missing_section_is_not_an_error(self):
        rates = parse_davr(fixture("davr_rate.html"),
                           ("Bank ofislarida valyutalar kursi", "Nope"), NOW)
        self.assertIn("USD", rates)

    def test_layout_change_raises(self):
        with self.assertRaises(LayoutError):
            parse_davr("<html>nothing</html>", ("Bank ofislarida valyutalar kursi",), NOW)


class MkbankTests(unittest.TestCase):
    def test_rub_sell_without_buy(self):
        rates = parse_mkbank_json([{"G1": "2026-11-12 09:00:00",
                                    "G2": "BANK", "G3": "RUB",
                                    "G4": "", "G5": "155"}])
        self.assertIsNone(rates["RUB"]["cash"]["buy"])
        self.assertEqual(rates["RUB"]["cash"]["sell"], 155.0)

    def test_mobile_separated_and_reference_rate_not_used(self):
        rates = parse_mkbank_json({"data": [
            {"G2": "APP", "G3": "USD", "G4": "11900", "G5": "12000"},
            {"G2": "BANK", "G3": "RUB", "G4": None, "G5": "155"},
            {"G2": "OTHER", "G3": "RUB", "G4": "145", "G5": "145"}]})
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12000.0)
        self.assertEqual(rates["RUB"]["cash"]["sell"], 155.0)

    def test_unexpected_structure_fails_closed(self):
        with self.assertRaises(LayoutError):
            parse_mkbank_json({"unknown": "layout"})


class DispatchTests(unittest.TestCase):
    def test_json_sources_dispatch(self):
        rates = parse_source("brb-api", fixture("brb_api.json"), "", NOW)
        self.assertIn("USD", rates)

    def test_unknown_kind_raises(self):
        with self.assertRaises(LayoutError):
            parse_source("mystery", "{}", "", NOW)


class StaleTimestampTests(unittest.TestCase):
    def test_implausible_bankuz_stamp_dropped(self):
        page = fixture("bankuz_asaka.html").replace("12.11.2026", "12.11.2020")
        rates = parse_bankuz(page, NOW)
        self.assertIsNone(rates["USD"]["cash"]["published_at"])

    def test_implausible_davr_stamp_dropped(self):
        page = fixture("davr_rate.html").replace("12-noyabr, 2026", "12-noyabr, 2019")
        rates = parse_davr(page, ("Bank ofislarida valyutalar kursi",), NOW)
        self.assertIsNone(rates["USD"]["cash"]["published_at"])


if __name__ == "__main__":
    unittest.main()
