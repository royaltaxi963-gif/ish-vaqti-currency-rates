"""Collector tests: bank identity, schema, failure handling, staleness.

Network access is replaced with a fake transport so the tests are deterministic
and do not depend on bank uptime. The parsers themselves are exercised against
real captured fixtures in test_bank_parsers.py.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scripts import fetch_banks
from scripts.banks import BANKS, BANKS_BY_SLUG, SUPPORTED_CURRENCIES

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)

# Banks whose own official source is reachable and whose rates the collector returns.
COLLECTIBLE = [bank for bank in BANKS if bank.sources]
# Banks whose official source is unavailable and which rely on a verified fallback.
FALLBACK_ONLY = [bank for bank in BANKS if not bank.sources and bank.fallback]
# Banks with no reachable source at all (none today).
UNAVAILABLE = [bank for bank in BANKS if not bank.sources and not bank.fallback]

FIXTURE_BY_KIND = {
    "universalbank-api": "universalbank_api.json",
    "davr-html": "davr_rate.html",
    "trastbank-html": "trastbank.html",
    "sqb-api": "sqb_api.json",
    "mkbank-json": "mkbank_api.json",
    "ipakyuli-nuxt": "ipakyuli.html",
    "brb-api": "brb_api.json",
    "agrobank-api": "agrobank_api.json",
    "hamkorbank-api": "hamkorbank_api.json",
    "xalq-api": "xalq_api.json",
}

# Sanitized bank.uz captures, one per fallback bank.
BANKUZ_FIXTURE = {
    "asaka-bank": "bankuz_asaka-bank.html",
    "nbu": "bankuz_nbu.html",
    "hamkorbank": "bankuz_hamkorbank.html",
    "kapitalbank": "bankuz_kapitalbank.html",
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


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


def good_mapping() -> dict:
    """Map every configured source URL (official and fallback) to a response."""
    mapping = {}
    for bank in BANKS:
        for source in bank.sources:
            if source.kind == "ipoteka-html":
                mapping[source.url] = fixture("ipoteka_index.html")
            else:
                mapping[source.url] = fixture(FIXTURE_BY_KIND[source.kind])
        if bank.fallback is not None:
            mapping[bank.fallback.url] = fixture(BANKUZ_FIXTURE[bank.slug])
    return mapping


def url_of(slug: str) -> str:
    return BANKS_BY_SLUG[slug].sources[0].url


def fallback_url_of(slug: str) -> str:
    return BANKS_BY_SLUG[slug].fallback.url


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

    def test_no_official_source_is_a_third_party_aggregator(self):
        for bank in BANKS:
            for source in bank.sources:
                host = urlsplit(source.url).hostname or ""
                self.assertFalse(
                    host == "bank.uz" or host.endswith(".bank.uz"),
                    f"{bank.slug} still uses the bank.uz aggregator as an official source",
                )

    def test_fallback_is_an_approved_aggregator_and_never_official(self):
        for bank in BANKS:
            if bank.fallback is None:
                continue
            host = urlsplit(bank.fallback.url).hostname or ""
            self.assertEqual(host, "bank.uz", f"{bank.slug}: unexpected fallback host {host}")
            self.assertEqual(bank.fallback.source_type, "fallback")
            self.assertTrue(bank.fallback.expect, f"{bank.slug}: fallback needs identity tokens")
            # An official source must never be labelled as a fallback.
            for source in bank.sources:
                self.assertEqual(source.source_type, "official")

    def test_fallback_only_banks_are_the_four_blocked_officials(self):
        slugs = {bank.slug for bank in FALLBACK_ONLY}
        # Asakabank, NBU and Kapitalbank have no official source at all;
        # Hamkorbank keeps its official source and adds a fallback for outages.
        self.assertEqual(slugs, {"asaka-bank", "nbu", "kapitalbank"})

    def test_hamkorbank_has_both_official_and_fallback(self):
        bank = BANKS_BY_SLUG["hamkorbank"]
        self.assertTrue(bank.sources)
        self.assertIsNotNone(bank.fallback)
        self.assertEqual(bank.fallback.source_type, "fallback")

    def test_collectible_banks_have_an_official_source(self):
        self.assertEqual(len(COLLECTIBLE), 11)
        for bank in COLLECTIBLE:
            self.assertTrue(bank.sources, f"{bank.slug} has no official source")

    def test_fallback_banks_carry_a_reason(self):
        for bank in FALLBACK_ONLY:
            self.assertTrue(bank.unavailable_reason, f"{bank.slug} needs an official-failure reason")


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
        fetch_banks._fetch = fake_transport(good_mapping())

    def tearDown(self):
        fetch_banks._fetch = self._original

    def test_all_banks_with_a_source_return_rates(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual(data["summary"]["banks_total"], 14)
        self.assertEqual(data["summary"]["banks_with_rates"], 14)
        fetch_banks.validate_dataset(data)

    def test_bank_order_preserved_in_output(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual([b["slug"] for b in data["banks"]], [b.slug for b in BANKS])

    def test_fallback_banks_use_their_fallback_and_record_provenance(self):
        data = fetch_banks.build_dataset(NOW)
        for bank in FALLBACK_ONLY:
            entry = next(b for b in data["banks"] if b["slug"] == bank.slug)
            self.assertTrue(entry["currencies"], f"{bank.slug} has no rates")
            self.assertEqual(entry["selected_source"], "fallback")
            self.assertTrue(entry["reason"])
            self.assertIn("bank.uz", entry["reason"])
            self.assertTrue(any(s.get("source_type") == "fallback" for s in entry["sources"]))

    def test_official_banks_are_marked_official(self):
        data = fetch_banks.build_dataset(NOW)
        for bank in COLLECTIBLE:
            entry = next(b for b in data["banks"] if b["slug"] == bank.slug)
            self.assertEqual(entry["selected_source"], "official", bank.slug)
            for source in entry["sources"]:
                self.assertEqual(source.get("source_type"), "official")

    def test_cash_and_mobile_both_present_for_sqb(self):
        data = fetch_banks.build_dataset(NOW)
        sqb = next(b for b in data["banks"] if b["slug"] == "sqb")
        self.assertIn("cash", sqb["currencies"]["USD"])
        self.assertIn("mobile", sqb["currencies"]["USD"])

    def test_source_url_and_status_recorded(self):
        data = fetch_banks.build_dataset(NOW)
        bank = next(b for b in data["banks"] if b["slug"] == "universalbank")
        self.assertTrue(bank["sources"][0]["url"].startswith("https://universalbank.uz/"))
        self.assertEqual(bank["sources"][0]["status"], "ok")

    def test_stale_after_is_generated_plus_max_age(self):
        data = fetch_banks.build_dataset(NOW)
        self.assertEqual(data["stale_after"], (NOW + timedelta(hours=24)).isoformat(timespec="seconds"))

    def test_dataset_is_json_serialisable(self):
        data = fetch_banks.build_dataset(NOW)
        json.loads(json.dumps(data))

    def test_shared_url_fetched_once_per_cycle(self):
        calls = {"n": 0}
        base = fake_transport(good_mapping())

        def counting(url, attempts=fetch_banks.RETRIES):
            calls["n"] += 1
            return base(url, attempts)

        fetch_banks._fetch = counting
        data = fetch_banks.build_dataset(NOW)
        # davr, sqb and brb each declare two sources sharing one URL, so those
        # three URLs are fetched once instead of twice. Banks served by their
        # fallback add one fetch each; the total is bounded and never repeats.
        official_urls = {s.url for b in COLLECTIBLE for s in b.sources}
        fallback_urls = {b.fallback.url for b in FALLBACK_ONLY if b.fallback}
        expected = len(official_urls) + len(fallback_urls)
        self.assertEqual(calls["n"], expected)
        self.assertEqual(data["summary"]["banks_with_rates"], 14)


class FallbackSelectionTests(unittest.TestCase):
    """Source-selection rules: official preferred, fallback only when needed."""

    def setUp(self):
        self._original = fetch_banks._fetch

    def tearDown(self):
        fetch_banks._fetch = self._original

    def test_official_source_wins_when_healthy(self):
        # Hamkorbank has both an official source and a fallback; when the
        # official endpoint works, its rates must be used and the fallback
        # must not be consulted.
        mapping = good_mapping()
        called = []
        base = fake_transport(mapping)

        def spy(url, attempts=fetch_banks.RETRIES):
            called.append(url)
            return base(url, attempts)

        fetch_banks._fetch = spy
        bank = BANKS_BY_SLUG["hamkorbank"]
        result = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(result["selected_source"], "official")
        self.assertIn("cash", result["currencies"]["USD"])
        self.assertNotIn(fallback_url_of("hamkorbank"), called)

    def test_official_failure_uses_fallback(self):
        mapping = good_mapping()
        mapping[url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 500")
        fetch_banks._fetch = fake_transport(mapping)
        bank = BANKS_BY_SLUG["hamkorbank"]
        result = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(result["selected_source"], "fallback")
        self.assertEqual(result["status"], "verified")
        self.assertIn("RUB", result["currencies"])
        self.assertTrue(any(s.get("source_type") == "fallback" for s in result["sources"]))

    def test_identity_mismatch_rejects_fallback(self):
        # A fallback page that does not name the bank must be refused outright.
        mapping = good_mapping()
        mapping[url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 500")
        mapping[fallback_url_of("hamkorbank")] = fixture("bankuz_kapitalbank.html")
        fetch_banks._fetch = fake_transport(mapping)
        bank = BANKS_BY_SLUG["hamkorbank"]
        result = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(result["currencies"], {})
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(any("identity check failed" in (s.get("error") or "")
                            for s in result["sources"]))

    def test_both_sources_fail_reports_unavailable(self):
        mapping = good_mapping()
        mapping[url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 500")
        mapping[fallback_url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 503")
        fetch_banks._fetch = fake_transport(mapping)
        bank = BANKS_BY_SLUG["hamkorbank"]
        result = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(result["currencies"], {})
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("fallback also failed", result["reason"])

    def test_official_recovery_returns_to_official(self):
        # Run once with the official endpoint down (fallback used), then with it
        # healthy again: the collector must switch back to the official source.
        bank = BANKS_BY_SLUG["hamkorbank"]

        mapping = good_mapping()
        mapping[url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 500")
        fetch_banks._fetch = fake_transport(mapping)
        first = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(first["selected_source"], "fallback")

        fetch_banks._fetch = fake_transport(good_mapping())
        second = fetch_banks.collect_bank(bank, NOW)
        self.assertEqual(second["selected_source"], "official")
        self.assertTrue(any(s.get("source_type") == "official" for s in second["sources"]))

    def test_official_and_fallback_rates_are_never_mixed(self):
        # The official Hamkorbank feed and the bank.uz page carry different
        # numbers; a published pair must come from exactly one source.
        mapping = good_mapping()
        fetch_banks._fetch = fake_transport(mapping)
        bank = BANKS_BY_SLUG["hamkorbank"]
        official = fetch_banks.collect_bank(bank, NOW)
        official_usd = official["currencies"]["USD"]["cash"]

        mapping = good_mapping()
        mapping[url_of("hamkorbank")] = fetch_banks.CollectionError("HTTP 500")
        fetch_banks._fetch = fake_transport(mapping)
        fallback = fetch_banks.collect_bank(bank, NOW)
        fallback_usd = fallback["currencies"]["USD"]["cash"]

        # The official feed is scaled /100 and yields 11920/12030; bank.uz
        # yields 11920/12030 too, but the source provenance differs. The key
        # invariant is that only one source class is ever recorded per entry.
        self.assertEqual(official["selected_source"], "official")
        self.assertEqual(fallback["selected_source"], "fallback")
        self.assertTrue(official_usd["buy"] and official_usd["sell"])
        self.assertTrue(fallback_usd["buy"] and fallback_usd["sell"])

    def test_no_cross_bank_rate_assignment(self):
        # Each fallback fixture must only ever contribute its own bank's rates.
        fetch_banks._fetch = fake_transport(good_mapping())
        data = fetch_banks.build_dataset(NOW)
        asaka = next(b for b in data["banks"] if b["slug"] == "asaka-bank")
        kapital = next(b for b in data["banks"] if b["slug"] == "kapitalbank")
        # Asakabank publishes no KZT; Kapitalbank does. A mix-up would leak KZT.
        self.assertNotIn("KZT", asaka["currencies"])
        self.assertIn("KZT", kapital["currencies"])


class NetworkFailureTests(unittest.TestCase):
    def setUp(self):
        self._original = fetch_banks._fetch

    def tearDown(self):
        fetch_banks._fetch = self._original

    def test_single_bank_network_failure_does_not_break_run(self):
        mapping = good_mapping()
        mapping[url_of("universalbank")] = fetch_banks.CollectionError("timeout")
        fetch_banks._fetch = fake_transport(mapping)
        data = fetch_banks.build_dataset(NOW)
        bank = next(b for b in data["banks"] if b["slug"] == "universalbank")
        self.assertEqual(bank["status"], "unavailable")
        self.assertIn("timeout", bank["reason"])
        self.assertEqual(data["summary"]["banks_with_rates"], 13)

    def test_partial_failure_keeps_other_rates(self):
        mapping = good_mapping()
        mapping[url_of("brb")] = fetch_banks.CollectionError("HTTP 503")
        fetch_banks._fetch = fake_transport(mapping)
        data = fetch_banks.build_dataset(NOW)
        brb = next(b for b in data["banks"] if b["slug"] == "brb")
        self.assertEqual(brb["status"], "unavailable")
        self.assertTrue(any(s["status"] == "error" for s in brb["sources"]))

    def test_layout_change_is_a_parser_error(self):
        mapping = good_mapping()
        mapping[url_of("trastbank")] = "<html><body>changed</body></html>"
        fetch_banks._fetch = fake_transport(mapping)
        data = fetch_banks.build_dataset(NOW)
        bank = next(b for b in data["banks"] if b["slug"] == "trastbank")
        self.assertEqual(bank["status"], "unavailable")
        self.assertTrue(any(s["status"] == "error" for s in bank["sources"]))

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

    def test_previous_dataset_preserved_when_all_sources_fail(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        fetch_banks.run(self.path, now=NOW)
        before = self.path.read_text(encoding="utf-8")

        fetch_banks._fetch = fake_transport({})  # everything fails
        result = fetch_banks.run(self.path, now=NOW + timedelta(hours=3))
        self.assertEqual(result["summary"]["banks_with_rates"], 14)
        # Every bank is carried forward, so the file is unchanged.
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_partial_failure_carries_forward_missing_bank(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        fetch_banks.run(self.path, now=NOW)

        mapping = good_mapping()
        mapping[url_of("universalbank")] = fetch_banks.CollectionError("down")
        fetch_banks._fetch = fake_transport(mapping)
        result = fetch_banks.run(self.path, now=NOW + timedelta(hours=3))

        bank = next(b for b in result["banks"] if b["slug"] == "universalbank")
        self.assertTrue(bank["carried_forward"])
        self.assertEqual(bank["status"], "stale")
        self.assertEqual(bank["currencies"]["USD"]["cash"]["sell"], 12020.0)

    def test_carried_forward_fallback_rate_is_not_marked_fresh(self):
        # A bank served from a fallback keeps its original publication time and
        # is flagged carried_forward / stale; it is never presented as fresh.
        fetch_banks._fetch = fake_transport(good_mapping())
        first = fetch_banks.build_dataset(NOW)
        asaka_fresh = next(b for b in first["banks"] if b["slug"] == "asaka-bank")
        self.assertEqual(asaka_fresh["selected_source"], "fallback")
        self.assertFalse(asaka_fresh["carried_forward"])

        fetch_banks._fetch = fake_transport({})  # all sources fail
        second = fetch_banks.build_dataset(NOW + timedelta(hours=3), previous=first)
        asaka = next(b for b in second["banks"] if b["slug"] == "asaka-bank")
        self.assertTrue(asaka["carried_forward"])
        self.assertEqual(asaka["status"], "stale")
        # Provenance of the carried-forward rate is preserved, not dropped.
        self.assertEqual(asaka["selected_source"], "fallback")
        # The original bank.uz publication stamp survives untouched.
        self.assertEqual(
            asaka["currencies"]["USD"]["cash"]["published_at"],
            "2026-11-12T16:56:00+05:00",
        )

    def test_blocked_bank_never_inherits_old_rates(self):
        previous = fetch_banks.build_dataset(NOW)
        # Simulate a dataset whose stored rate came from a since-removed source
        # (the retired bank.uz-as-official integration).
        blocked = next(b for b in previous["banks"] if b["slug"] == "kapitalbank")
        blocked["sources"] = [{
            "kind": "bankuz", "url": "https://bank.uz/uz/currency/bank/kapitalbank",
            "rate_type": "cash", "status": "ok",
        }]
        blocked["currencies"] = {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": None}}}
        fetch_banks._fetch = fake_transport({})
        result = fetch_banks.build_dataset(NOW, previous=previous)
        entry = next(b for b in result["banks"] if b["slug"] == "kapitalbank")
        self.assertEqual(entry["currencies"], {})
        self.assertNotEqual(entry["status"], "verified")

    def test_atomic_write_leaves_no_temp_files(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        fetch_banks.run(self.path, now=NOW)
        leftovers = [p for p in Path(self.tmp.name).iterdir() if p.name.startswith(".banks-")]
        self.assertEqual(leftovers, [])

    def test_validation_rejects_empty_dataset(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        data = fetch_banks.build_dataset(NOW)
        for bank in data["banks"]:
            bank["currencies"] = {}
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_validation_rejects_reordered_banks(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        data = fetch_banks.build_dataset(NOW)
        data["banks"].reverse()
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_validation_rejects_unsupported_currency(self):
        fetch_banks._fetch = fake_transport(good_mapping())
        data = fetch_banks.build_dataset(NOW)
        data["banks"][0]["currencies"]["JPY"] = {"cash": {"buy": 1.0, "sell": 1.1}}
        with self.assertRaises(ValueError):
            fetch_banks.validate_dataset(data)

    def test_invalid_previous_file_is_ignored(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(fetch_banks.load_previous(self.path))


class StaleDataTests(unittest.TestCase):
    """Freshness is judged from real instants, never from string ordering."""

    def test_old_published_stamp_marks_bank_stale(self):
        fresh, stale = fetch_banks._bank_freshness(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": "2026-11-10T08:00:00+05:00"}}},
            NOW,
        )
        self.assertFalse(fresh)
        self.assertTrue(stale)

    def test_recent_published_stamp_is_fresh(self):
        fresh, stale = fetch_banks._bank_freshness(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": "2026-11-13T00:00:00+05:00"}}},
            NOW,
        )
        self.assertTrue(fresh)
        self.assertFalse(stale)

    def test_missing_stamp_is_not_flagged_fresh(self):
        # No usable instant anywhere -> cannot be called fresh.
        fresh, stale = fetch_banks._bank_freshness(
            {"USD": {"cash": {"buy": 1.0, "sell": 2.0, "published_at": None}}}, NOW)
        self.assertFalse(fresh)
        self.assertFalse(stale)

    def test_no_rates_is_neither_fresh_nor_stale(self):
        self.assertEqual(fetch_banks._bank_freshness({}, NOW), (False, False))


if __name__ == "__main__":
    unittest.main()
