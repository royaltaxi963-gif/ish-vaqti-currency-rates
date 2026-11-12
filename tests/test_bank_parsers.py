"""Parser tests: bank identity, currencies, buy/sell, cash/mobile, layout drift.

Each parser is exercised against a sanitised real response captured from the
bank's official source (see ``docs/official-sources.md``).
"""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.bank_parsers import (
    LayoutError,
    parse_agrobank,
    parse_brb,
    parse_davr,
    parse_hamkorbank,
    parse_ipakyuli,
    parse_ipoteka,
    parse_mkbank_json,
    parse_source,
    parse_sqb,
    parse_trastbank,
    parse_universalbank,
    parse_xalq,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def payload(name: str):
    return json.loads(fixture(name))


class UniversalbankTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_universalbank(payload("universalbank_api.json"), NOW)

    def test_usd_buy_and_sell(self):
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11940.0)
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12020.0)

    def test_rub_sell_without_buy(self):
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 145.0)
        self.assertIsNone(self.rates["RUB"]["cash"]["buy"])

    def test_published_date_from_rate_date(self):
        self.assertTrue(self.rates["USD"]["cash"]["published_at"].startswith("2026-11-12"))

    def test_numeric_code_mapped_to_alpha(self):
        self.assertIn("GBP", self.rates)
        self.assertNotIn("826", self.rates)

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_universalbank({"nope": 1})


class TrastbankTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_trastbank(fixture("trastbank.html"), NOW)

    def test_usd_buy_sell(self):
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11920.0)
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12020.0)

    def test_rub_collected(self):
        self.assertEqual(self.rates["RUB"]["cash"]["buy"], 90.0)
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 150.0)

    def test_mb_reference_column_not_used(self):
        # 11964.27 is the CBU reference rate printed as "MB kursi"; it must not
        # become a buy or sell value.
        self.assertNotIn(11964.27, (self.rates["USD"]["cash"]["buy"],
                                    self.rates["USD"]["cash"]["sell"]))

    def test_published_timestamp(self):
        self.assertEqual(self.rates["USD"]["cash"]["published_at"],
                         "2026-11-12T09:00:00+05:00")

    def test_layout_change_raises(self):
        with self.assertRaises(LayoutError):
            parse_trastbank("<html><body>no table</body></html>", NOW)


class IpakYuliTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_ipakyuli(fixture("ipakyuli.html"), NOW)

    def test_cash_and_mobile_separated(self):
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11910.0)
        self.assertEqual(self.rates["USD"]["mobile"]["buy"], 11915.0)

    def test_rub_present(self):
        self.assertEqual(self.rates["RUB"]["cash"]["buy"], 80.0)
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 146.0)

    def test_values_scaled_by_100(self):
        # Raw feed value for USD cash is 1191000.
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12010.0)

    def test_published_from_last_updated(self):
        self.assertTrue(self.rates["USD"]["cash"]["published_at"].startswith("2026-11-13T00:30"))

    def test_layout_change_raises(self):
        with self.assertRaises(LayoutError):
            parse_ipakyuli("<html><body>no data</body></html>", NOW)


class IpotekaTests(unittest.TestCase):
    def test_usd_page(self):
        rates = parse_ipoteka(fixture("ipoteka_usd.html"), "USD", NOW)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11915.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12030.0)

    def test_eur_page(self):
        rates = parse_ipoteka(fixture("ipoteka_eur.html"), "EUR", NOW)
        self.assertEqual(rates["EUR"]["cash"]["buy"], 12650.0)
        self.assertEqual(rates["EUR"]["cash"]["sell"], 13700.0)

    def test_published_timestamp(self):
        rates = parse_ipoteka(fixture("ipoteka_usd.html"), "USD", NOW)
        self.assertEqual(rates["USD"]["cash"]["published_at"],
                         "2026-11-13T00:36:03+05:00")

    def test_missing_currency_raises(self):
        with self.assertRaises(LayoutError):
            parse_ipoteka(fixture("ipoteka_usd.html"), "RUB", NOW)


class AgrobankTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_agrobank(payload("agrobank_api.json"))

    def test_office_is_cash(self):
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11920.0)
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12010.0)

    def test_atm_is_mobile(self):
        self.assertEqual(self.rates["USD"]["mobile"]["buy"], 11500.0)

    def test_rub_buy_zero_dropped(self):
        self.assertIsNone(self.rates["RUB"]["cash"]["buy"])
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 180.0)

    def test_eur_mobile_zero_sale_dropped(self):
        self.assertIsNone(self.rates["EUR"]["mobile"]["sell"])

    def test_published_timestamp(self):
        self.assertEqual(self.rates["USD"]["cash"]["published_at"],
                         "2026-11-12T09:21:52+05:00")

    def test_unsuccessful_response_raises(self):
        with self.assertRaises(LayoutError):
            parse_agrobank({"success": False})


class HamkorbankTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_hamkorbank(payload("hamkorbank_api.json"))

    def test_cash_standard_row_selected(self):
        # Two destination_code=2 USD rows exist; the begin_sum_i==0 one wins.
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11920.0)
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12030.0)

    def test_mobile_from_destination_7(self):
        self.assertEqual(self.rates["USD"]["mobile"]["buy"], 11930.0)
        self.assertEqual(self.rates["USD"]["mobile"]["sell"], 12020.0)

    def test_rub_collected(self):
        self.assertEqual(self.rates["RUB"]["cash"]["buy"], 101.0)
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 145.0)

    def test_gold_ignored(self):
        self.assertNotIn("XAU", self.rates)

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_hamkorbank({"data": None})


class XalqTests(unittest.TestCase):
    def setUp(self):
        self.rates = parse_xalq(payload("xalq_api.json"), NOW)

    def test_usd_latest_day(self):
        self.assertEqual(self.rates["USD"]["cash"]["buy"], 11910.0)
        self.assertEqual(self.rates["USD"]["cash"]["sell"], 12000.0)

    def test_rub_collected(self):
        self.assertEqual(self.rates["RUB"]["cash"]["buy"], 142.45)
        self.assertEqual(self.rates["RUB"]["cash"]["sell"], 147.1)

    def test_published_is_most_recent_day(self):
        self.assertEqual(self.rates["USD"]["cash"]["published_at"],
                         "2026-11-12T00:00:00+05:00")

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_xalq([], NOW)


class MkbankTests(unittest.TestCase):
    def test_dot_timestamp_parsed(self):
        rates = parse_mkbank_json(payload("mkbank_api.json"), NOW)
        self.assertEqual(rates["USD"]["cash"]["published_at"],
                         "2026-11-12T12:00:00+05:00")

    def test_rub_sell_without_buy(self):
        rates = parse_mkbank_json(payload("mkbank_api.json"), NOW)
        self.assertIsNone(rates["RUB"]["cash"]["buy"])
        self.assertEqual(rates["RUB"]["cash"]["sell"], 155.0)

    def test_app_and_atm_are_mobile(self):
        rates = parse_mkbank_json(payload("mkbank_api.json"), NOW)
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11200.0)

    def test_reference_rate_not_used(self):
        rates = parse_mkbank_json({"data": [
            {"G2": "APP", "G3": "USD", "G4": "11900", "G5": "12000"},
            {"G2": "OTHER", "G3": "RUB", "G4": "145", "G5": "145"}]})
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12000.0)
        self.assertNotIn("RUB", rates)

    def test_unexpected_structure_fails_closed(self):
        with self.assertRaises(LayoutError):
            parse_mkbank_json({"unknown": "layout"})


class SqbTests(unittest.TestCase):
    def setUp(self):
        self.payload = payload("sqb_api.json")

    def test_offline_is_cash_and_scaled(self):
        rates = parse_sqb(self.payload)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11930.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12020.0)

    def test_online_is_mobile_and_not_scaled(self):
        rates = parse_sqb(self.payload)
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11940.0)

    def test_atm_fills_mobile_only_when_absent(self):
        rates = parse_sqb(self.payload)
        self.assertEqual(rates["USD"]["mobile"]["buy"], 11940.0)

    def test_zero_buy_dropped(self):
        rates = parse_sqb(self.payload)
        self.assertIsNone(rates["RUB"]["cash"]["buy"])

    def test_bad_payload_raises(self):
        with self.assertRaises(LayoutError):
            parse_sqb({"data": "nope"})


class BrbTests(unittest.TestCase):
    def setUp(self):
        self.payload = payload("brb_api.json")

    def test_scaled_values(self):
        rates = parse_brb(self.payload)
        self.assertEqual(rates["USD"]["cash"]["buy"], 11945.0)
        self.assertEqual(rates["USD"]["cash"]["sell"], 12030.0)

    def test_mobil_row_is_mobile(self):
        rates = parse_brb(self.payload)
        self.assertEqual(rates["USD"]["mobile"]["sell"], 12010.0)

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
        self.assertNotIn("cash", rates["USD"])

    def test_zero_rows_dropped(self):
        rates = parse_davr(fixture("davr_rate.html"),
                           ("Bank ofislarida valyutalar kursi",), NOW)
        self.assertNotIn("RUB", rates)

    def test_layout_change_raises(self):
        with self.assertRaises(LayoutError):
            parse_davr("<html>nothing</html>", ("Bank ofislarida valyutalar kursi",), NOW)


class DispatchTests(unittest.TestCase):
    def test_json_sources_dispatch(self):
        rates = parse_source("brb-api", fixture("brb_api.json"), "", NOW)
        self.assertIn("USD", rates)

    def test_html_sources_dispatch(self):
        rates = parse_source("trastbank-html", fixture("trastbank.html"), "", NOW)
        self.assertIn("USD", rates)

    def test_unknown_kind_raises(self):
        with self.assertRaises(LayoutError):
            parse_source("mystery", "{}", "", NOW)


class StaleTimestampTests(unittest.TestCase):
    def test_implausible_mkbank_stamp_dropped(self):
        rates = parse_mkbank_json(
            [{"G1": "12.11.2020 12:00:00", "G2": "BANK", "G3": "USD",
              "G4": "11910", "G5": "12020"}], NOW)
        self.assertIsNone(rates["USD"]["cash"]["published_at"])

    def test_implausible_davr_stamp_dropped(self):
        page = fixture("davr_rate.html").replace("12-noyabr, 2026", "12-noyabr, 2019")
        rates = parse_davr(page, ("Bank ofislarida valyutalar kursi",), NOW)
        self.assertIsNone(rates["USD"]["cash"]["published_at"])


if __name__ == "__main__":
    unittest.main()
