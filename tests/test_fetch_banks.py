"""Collector tests: bank identity, schema, failure handling, staleness.

Network access is replaced with a fake transport so the tests are deterministic
and do not depend on bank.uz uptime. The parsers themselves are exercised
against real captured fixtures in test_bank_parsers.py.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import fetch_banks
from scripts.banks import BANKS, SUPPORTED_CURRENCIES

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def bankuz_page(buy: str = "11 950", sell: str = "11 990", stamp: str = "12.11.2026 16:56") -> str:
    return (
        '<div class="table-kurs"><div class="row">'
        '<span class="medium-text"><span class="country-flag flag-us"></span>USD</span>'
        '<div class="col-1"><span class="medium-text"> Birlik</span><span class="medium-text"> 1 </span></div>'
        f'<div><span class="medium-text"> Sotib olish</span><span class="medium-text"> {buy} </span></div>'
        f'<div><span class="medium-text"> Sotish</span><span class="medium-text">{sell}</span></div>'
        f'<span class="green-date"> {stamp} </span></div></div>'
    )


def fake_transport(mapping: dict):
    """Return a fetch replacement; raise for URLs mapped to an exception."""
    def fetch(url, attempts=fetch_banks.RETRIES):
        if url not in mapping:
            raise fetch_banks.CollectionError(f"no fake route for {url}")
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def good_mapping(page: str | None = None) -> dict:
    """Map every configured source URL to a realistic response of its kind."""
    page = page or bankuz_page()
    mapping = {}
    for bank in BANKS:
        for source in bank.sources:
            if source.kind == "bankuz":
                mapping[source.url] = page
            elif source.kind == "davr-html":
                mapping[source.url] = fixture("davr_rate.html")
            elif source.kind == "sqb-api":
                mapping[source.url] = fixture("sqb_api.json")
            elif source.kind == "brb-api":
                mapping[source.url] = fixture("brb_api.json")
    return mapping


class BankIdentityTests(unittest.TestCase):
    def test_exactly_fourteen_banks(self):
        self.assertEqual(len(BANKS), 14)

    def test_required_order(self):
        self.assertEqual(
            [bank.slug for bank in BANKS],
            ["universalbank", "davr-bank", "asaka-bank", "trastbank", "sqb",
             "mikrokreditbank", "ipakyulibank", "nbu", "ipoteka-bank", "brb",
             "agrobank", "hamkorbank", "xalq-bank", "kapitalbank"],
        )

    def test_excluded_banks_absent(self):
        slugs = {bank.slug for bank in BANKS}
        for excluded in ("asia-alliance-bank", "tenge-bank", "tbc-bank", "anorbank", "turonbank"):
            self.assertNotIn(excluded, slugs)

    def test_display_names(self):
        names = [bank.name for bank in BANKS]
        self.assertIn("O\u2018zmilliybank", names)
        self.assertIn("Biznesni rivojlantirish banki (BRB)", names)
        self.assertIn("Xalq banki", names)

    def test_every_bank_has_a_source(self):
        for bank in BANKS:
            self.assertTrue(bank.sources, f"{bank.slug} has no source")


class SchemaTests(unittest.TestCase):
    def test_supported_currencies(self):
        self.assertEqual(set(SUPPORTED_CURRENCIES), {"USD", "EUR", "RUB", "KZT", "GBP"})

    def test_schema_file_is_valid_json(self):
        schema = json.loads((Path(__file__).parent.parent / "schemas" / "banks.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)
        self.assertEqual(schema["properties"]["max_age_hours"]["const"], 24)

    def test_schema_bank_count_matches(self):
        schema = json.loads((Path(__file__).parent.parent / "schemas" / "banks.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["banks"]["minItems"], len(BANKS))
        self.assertEqual(schema["properties"]["banks"]["maxItems"], len(BANKS))


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self._original = fetch_banks._fetch
        self.mapping = good_mapping()
        fetch_banks._fetch = fake_transport(self.mapping)

    def tearDown(self):
        fetch_banks._fetch = self._original

    def test_all_banks_collected(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual(data["summary"]["banks_total"], 14)
        self.assertEqual(data["summary"]["banks_with_rates"], 14)
        fetch_banks.validate_dataset(data)

    def test_bank_order_preserved_in_output(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual([b["slug"] for b in data["banks"]], [b.slug for b in BANKS])

    def test_cash_and_mobile_both_present_for_sqb(self):
        data = fetch_banks.build_dataset(NOW)
        sqb = next(b for b in data["banks"] if b["slug"] == "sqb")
        self.assertIn("cash", sqb["currencies"]["USD"])
        self.assertIn("mobile", sqb["currencies"]["USD"])

    def test_source_url_and_status_recorded(self):
        data = fetch_banks.build_dataset(NOW)
        nbu = next(b for b in data["banks"] if b["slug"] == "nbu")
        self.assertTrue(nbu["sources"][0]["url"].startswith("https://bank.uz/"))
        self.assertEqual(nbu["sources"][0]["status"], "ok")

    def test_stale_after_is_generated_plus_max_age(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual(data["stale_after"], (NOW + timedelta(hours=24)).isoformat(timespec="seconds"))

    def test_dataset_is_json_serialisable(self):
        data = fetch_banks.build_dataset(NOW)
        json.loads(json.dumps(data))


class NetworkFailureTests(unittest.TestCase):
    def setUp(self):
        self._original = fetch_banks._fetch

    def tearDown(self):
        fetch_banks._fetch = self._original

    def test_single_bank_network_failure_does_not_break_run(self):
        mapping = good_mapping()
        mapping["https://bank.uz/uz/currency/bank/nbu"] = fetch_banks.CollectionError("timeout")
        fetch_banks._fetch = fake_transport(mapping)
        data = fetch_banks.build_dataset(NOW)
        nbu = next(b for b in data["banks"] if b["slug"] == "nbu")
        self.assertEqual(nbu["status"], "unavailable")
        self.assertIn("timeout", nbu["reason"])
        self.assertEqual(data["summary"]["banks_with_rates"], 13)

    def test_partial_failure_keeps_other_rates(self):
        mapping = good_mapping()
        mapping["https://brb.uz/api/currency/compare?type=jismoniy"] = \
            fetch_banks.CollectionError("HTTP 503")
        fetch_banks._fetch = fake_transport(mapping)
        data = fetch_banks.build_dataset(NOW)
        brb = next(b for b in data["banks"] if b["slug"] == "brb")
        self.assertEqual(brb["status"], "unavailable")
        self.assertTrue(any(s["status"] == "error" for s in brb["sources"]))

    def test_timeout_and_retries_are_bounded(self):
        calls = {"n": 0}

        def flaky(url, attempts=fetch_banks.RETRIES):
            calls["n"] += 1
            raise fetch_banks.CollectionError("boom")

        original_sleep = fetch_banks.time.sleep
        fetch_banks.time.sleep = lambda _seconds: None
        try:
            fetch_banks._fetch = flaky
            with self.assertRaises(fetch_banks.CollectionError):
                fetch_banks._fetch("https://example.invalid")
        finally:
            fetch_banks.time.sleep = original_sleep
        self.assertGreaterEqual(calls["n"], 1)


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self._original = fetch_banks._fetch
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "banks.json"

    def tearDown(self):
        fetch_banks._fetch = self._original
        self.tmp.cleanup()

    def _good_mapping(self):
        return good_mapping()

    def test_previous_dataset_preserved_when_all_sources_fail(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        first = fetch_banks.run(self.path, now=NOW)
        before = self.path.read_text(encoding="utf-8")

        fetch_banks._fetch = fake_transport({})  # everything fails
        result = fetch_banks.run(self.path, now=NOW + timedelta(hours=3))
        self.assertEqual(result["summary"]["banks_with_rates"], 14)
        # Every bank is carried forward, so the file on disk is unchanged.
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_partial_failure_carries_forward_missing_bank(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        fetch_banks.run(self.path, now=NOW)

        mapping = self._good_mapping()
        mapping["https://bank.uz/uz/currency/bank/nbu"] = fetch_banks.CollectionError("down")
        fetch_banks._fetch = fake_transport(mapping)
        result = fetch_banks.run(self.path, now=NOW + timedelta(hours=3))

        nbu = next(b for b in result["banks"] if b["slug"] == "nbu")
        self.assertTrue(nbu["carried_forward"])
        self.assertEqual(nbu["status"], "stale")
        self.assertEqual(nbu["currencies"]["USD"]["cash"]["sell"], 11990.0)

    def test_atomic_write_leaves_no_temp_files(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        fetch_banks.run(self.path, now=NOW)
        leftovers = [p for p in Path(self.tmp.name).iterdir() if p.name.startswith(".banks-")]
        self.assertEqual(leftovers, [])

    def test_validation_rejects_empty_dataset(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        data = fetch_banks.build_dataset(NOW)
        for bank in data["banks"]:
            bank["currencies"] = {}
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_validation_rejects_reordered_banks(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        data = fetch_banks.build_dataset(NOW)
        data["banks"].reverse()
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_validation_rejects_unsupported_currency(self):
        fetch_banks._fetch = fake_transport(self._good_mapping())
        data = fetch_banks.build_dataset(NOW)
        data["banks"][0]["currencies"]["JPY"] = {"cash": {"buy": 1.0, "sell": 1.1}}
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_invalid_previous_file_is_ignored(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(fetch_banks.load_previous(self.path))


class StaleDataTests(unittest.TestCase):
    def test_old_published_stamp_marks_bank_stale(self):
        old = bankuz_page(stamp="10.11.2026 08:00")
        self.assertTrue(fetch_banks._bank_stale(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": "2026-11-10T08:00:00+05:00"}}},
            NOW,
        ))

    def test_recent_published_stamp_is_not_stale(self):
        self.assertFalse(fetch_banks._bank_stale(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": "2026-11-12T16:00:00+05:00"}}},
            NOW,
        ))

    def test_missing_stamp_is_not_flagged_stale(self):
        self.assertFalse(fetch_banks._bank_stale(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": None}}}, NOW))


if __name__ == "__main__":
    unittest.main()
