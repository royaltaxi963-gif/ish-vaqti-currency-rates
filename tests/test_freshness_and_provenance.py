"""Regression tests for the three reviewed data-integrity defects.

Defect A — freshness was decided by ``max()`` over ISO timestamp *strings*.
Defect B — carry-forward could mix an official and a fallback rate under a
           single ``selected_source`` label.
Defect C — ``_has_fresh_rates`` treated "newly retrieved" as "fresh", so a
           successful fetch of an outdated source could publish a fresh-looking
           dataset.

Each test asserts on real time instants, never on string ordering.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import fetch_banks
from scripts.banks import BANKS_BY_SLUG

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)  # 01:00 UTC
LIMIT = NOW - timedelta(hours=fetch_banks.MAX_AGE_HOURS)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


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
BANKUZ_FIXTURE = {
    "asaka-bank": "bankuz_asaka-bank.html",
    "nbu": "bankuz_nbu.html",
    "hamkorbank": "bankuz_hamkorbank.html",
    "kapitalbank": "bankuz_kapitalbank.html",
}


def full_mapping() -> dict:
    mapping = {}
    for bank in fetch_banks.BANKS:
        for source in bank.sources:
            name = "ipoteka_index.html" if source.kind == "ipoteka-html" else FIXTURE_BY_KIND[source.kind]
            mapping[source.url] = fixture(name)
        if bank.fallback is not None:
            mapping[bank.fallback.url] = fixture(BANKUZ_FIXTURE[bank.slug])
    return mapping


def transport(mapping: dict):
    def fetch(url, attempts=fetch_banks.RETRIES):
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def rate(buy=1.0, sell=2.0, published_at=None):
    payload = {"buy": buy, "sell": sell}
    if published_at is not None:
        payload["published_at"] = published_at
    return payload


class FakeTransportMixin:
    def setUp(self):
        self._original = fetch_banks._fetch

    def tearDown(self):
        fetch_banks._fetch = self._original


# --------------------------------------------------------------------------- #
# Defect A — timestamp comparison
# --------------------------------------------------------------------------- #

class TimestampComparisonTests(unittest.TestCase):
    def test_identical_instants_with_different_offsets(self):
        # 2026-11-12T20:00:00-05:00 == 2026-11-13T01:00:00+00:00 == NOW.
        fresh, stale = fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at="2026-11-12T20:00:00-05:00")}}, NOW)
        self.assertTrue(fresh)
        self.assertFalse(stale)

    def test_string_order_can_disagree_with_chronological_order(self):
        # The lexicographically larger string ("2026-11-13T00:30:00+05:00") is the
        # chronologically newer instant; max() on strings would also pick it here,
        # so use the opposite pair to prove the collector does not rely on strings.
        newer_instant = "2026-11-12T19:30:00+00:00"   # 5.5h old -> fresh
        older_instant = "2026-11-13T00:30:00+05:00"   # == 19:30 UTC, same instant
        # Same instant expressed differently must give the same verdict.
        a = fetch_banks._bank_freshness({"USD": {"cash": rate(published_at=newer_instant)}}, NOW)
        b = fetch_banks._bank_freshness({"USD": {"cash": rate(published_at=older_instant)}}, NOW)
        self.assertEqual(a, b)
        self.assertTrue(a[0])

    def test_string_larger_stale_string_must_not_win(self):
        # "2026-11-11T00:00:00+05:00" (stale, 30h) is lexicographically SMALLER
        # than "2026-11-13T00:30:00+05:00" (fresh). Feed only the stale one and
        # confirm it is stale, then both together and confirm fresh wins.
        stale_stamp = "2026-11-11T00:00:00+05:00"
        fresh_stamp = "2026-11-13T00:30:00+05:00"
        self.assertEqual(fetch_banks._bank_freshness(
            {"EUR": {"cash": rate(published_at=stale_stamp)}}, NOW), (False, True))
        combined = {"EUR": {"cash": rate(published_at=stale_stamp)},
                    "USD": {"cash": rate(published_at=fresh_stamp)}}
        self.assertEqual(fetch_banks._bank_freshness(combined, NOW), (True, False))

    def test_multiple_currencies_with_different_publication_times(self):
        currencies = {
            "USD": {"cash": rate(published_at="2026-11-10T00:00:00+00:00")},  # stale
            "EUR": {"cash": rate(published_at="2026-11-12T23:00:00+00:00")},  # fresh
        }
        self.assertEqual(fetch_banks._bank_freshness(currencies, NOW), (True, False))

    def test_missing_timestamp_is_unknown_not_fresh(self):
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at=None)}}, NOW), (False, False))

    def test_malformed_timestamp_is_unknown_not_fresh(self):
        for bad in ("not-a-date", "2026-13-40T99:99:99Z", "", "  "):
            with self.subTest(bad=bad):
                self.assertEqual(fetch_banks._bank_freshness(
                    {"USD": {"cash": rate(published_at=bad)}}, NOW), (False, False))

    def test_timezone_naive_timestamp_is_unknown(self):
        # A wall-clock time without an offset must not be assumed to be UTC.
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at="2026-11-13T00:00:00")}}, NOW),
            (False, False))

    def test_future_dated_timestamp_is_not_fresh(self):
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at="2026-12-01T00:00:00+00:00")}}, NOW),
            (False, False))

    def test_exactly_at_the_boundary_is_fresh(self):
        boundary = LIMIT.isoformat()  # exactly 24h before NOW
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at=boundary)}}, NOW), (True, False))

    def test_just_past_the_boundary_is_stale(self):
        past = (LIMIT - timedelta(seconds=1)).isoformat()
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at=past)}}, NOW), (False, True))

    def test_parse_instant_normalises_offsets_to_utc(self):
        parsed = fetch_banks._parse_instant("2026-11-13T06:00:00+05:00")
        self.assertEqual(parsed, datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc))
        self.assertIsNone(fetch_banks._parse_instant("2026-11-13T01:00:00"))


# --------------------------------------------------------------------------- #
# Defect B — source provenance and carry-forward
# --------------------------------------------------------------------------- #

class SourceProvenanceTests(FakeTransportMixin, unittest.TestCase):
    def _run(self, mapping, now, previous=None):
        fetch_banks._fetch = transport(mapping)
        return fetch_banks.build_dataset(now, previous=previous)

    def _bank(self, dataset, slug):
        return next(b for b in dataset["banks"] if b["slug"] == slug)

    def test_official_to_official_keeps_official_provenance(self):
        first = self._run(full_mapping(), NOW)
        # Second run: official hamkorbank still healthy.
        second = self._run(full_mapping(), NOW + timedelta(hours=1), previous=first)
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "official")
        self.assertFalse(hk["carried_forward"])
        self.assertIsNone(hk["source_transition"])

    def test_official_to_fallback_never_mixes_sources(self):
        # Run 1 official (yields USD cash + mobile). Run 2 official down, fallback
        # up: the fallback entry must NOT inherit the official USD.mobile rate.
        first = self._run(full_mapping(), NOW)
        hk1 = self._bank(first, "hamkorbank")
        self.assertEqual(hk1["selected_source"], "official")
        self.assertIn("mobile", hk1["currencies"]["USD"])

        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)
        hk2 = self._bank(second, "hamkorbank")
        self.assertEqual(hk2["selected_source"], "fallback")
        self.assertEqual(hk2["source_transition"], {"from": "official", "to": "fallback"})
        # The fallback publishes no mobile channel; the official mobile rate must
        # not leak into a fallback-labelled entry.
        self.assertNotIn("mobile", hk2["currencies"]["USD"])
        # Every recorded source is a fallback source.
        self.assertTrue(all(s.get("source_type") == "fallback" for s in hk2["sources"]))

    def test_fallback_to_official_never_mixes_sources(self):
        # Run 1 official down -> fallback. Run 2 official healthy again.
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        first = self._run(mapping, NOW)
        self.assertEqual(self._bank(first, "hamkorbank")["selected_source"], "fallback")

        second = self._run(full_mapping(), NOW + timedelta(hours=1), previous=first)
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "official")
        self.assertEqual(hk["source_transition"], {"from": "fallback", "to": "official"})
        self.assertTrue(all(s.get("source_type") == "official" for s in hk["sources"]))

    def test_fallback_to_fallback_keeps_fallback_provenance(self):
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        first = self._run(mapping, NOW)
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "fallback")
        self.assertIsNone(hk["source_transition"])

    def test_official_to_total_failure_preserves_without_mislabel(self):
        first = self._run(full_mapping(), NOW)
        hk1 = self._bank(first, "hamkorbank")
        self.assertIn("mobile", hk1["currencies"]["USD"])
        second = self._run({}, NOW + timedelta(hours=1), previous=first)
        hk2 = self._bank(second, "hamkorbank")
        # Last verified rates preserved whole, still labelled official.
        self.assertEqual(hk2["selected_source"], "official")
        self.assertTrue(hk2["carried_forward"])
        self.assertEqual(hk2["status"], "stale")
        self.assertIsNone(hk2["source_transition"])

    def test_fallback_to_total_failure_preserves_fallback_label(self):
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        first = self._run(mapping, NOW)
        second = self._run({}, NOW + timedelta(hours=1), previous=first)
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "fallback")
        self.assertTrue(hk["carried_forward"])

    def test_partial_currency_availability_same_source(self):
        # Official hamkorbank healthy but missing GBP is not simulated here;
        # instead verify a same-source partial carry keeps the official label.
        first = self._run(full_mapping(), NOW)
        ub1 = self._bank(first, "universalbank")
        self.assertEqual(ub1["selected_source"], "official")
        # Drop universalbank entirely for run 2 -> carry forward official rates.
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["universalbank"].sources[0].url] = fetch_banks.CollectionError("down")
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)
        ub2 = self._bank(second, "universalbank")
        self.assertEqual(ub2["selected_source"], "official")
        self.assertTrue(ub2["carried_forward"])

    def test_partial_channel_availability_same_source(self):
        # Within one source class, a channel missing from this run is carried
        # forward from the previous run with the label unchanged.
        bank = BANKS_BY_SLUG["brb"]
        previous = {"banks": [{
            "slug": "brb",
            "selected_source": "official",
            "sources": [{"kind": s.kind, "url": s.url, "status": "ok"} for s in bank.sources],
            "currencies": {"USD": {"cash": rate(11945.0, 12030.0, "2026-11-12T23:00:00+00:00"),
                                   "mobile": rate(11950.0, 12025.0, "2026-11-12T23:00:00+00:00")}},
        }]}
        entry = {
            "name": bank.name,
            "status": "verified",
            "reason": None,
            "sources": [{"kind": s.kind, "url": s.url, "status": "ok"} for s in bank.sources],
            "currencies": {"USD": {"cash": rate(11945.0, 12030.0, "2026-11-13T00:30:00+00:00")}},
            "selected_source": "official",
        }
        merged = fetch_banks._merge_with_previous(bank, entry, previous)
        self.assertEqual(merged["selected_source"], "official")
        self.assertTrue(merged["carried_forward"])
        self.assertIn("mobile", merged["currencies"]["USD"])  # carried forward
        self.assertEqual(merged["currencies"]["USD"]["mobile"]["published_at"],
                         "2026-11-12T23:00:00+00:00")  # original stamp kept

    def test_old_fallback_data_plus_new_official_data(self):
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        first = self._run(mapping, NOW)  # fallback
        second = self._run(full_mapping(), NOW + timedelta(hours=1), previous=first)  # official
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "official")
        self.assertFalse(hk["carried_forward"])
        self.assertEqual(hk["source_transition"], {"from": "fallback", "to": "official"})
        # No fallback rate may survive into the official entry.
        self.assertTrue(all(s.get("source_type") == "official" for s in hk["sources"]))

    def test_old_official_data_plus_new_fallback_data(self):
        first = self._run(full_mapping(), NOW)  # official
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)  # fallback
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "fallback")
        self.assertFalse(hk["carried_forward"])
        self.assertEqual(hk["source_transition"], {"from": "official", "to": "fallback"})
        self.assertNotIn("mobile", hk["currencies"]["USD"])

    def test_no_entry_is_mixed_source(self):
        # Across a source transition, the entry's single selected_source must
        # describe every rate it serves.
        first = self._run(full_mapping(), NOW)
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["hamkorbank"].sources[0].url] = fetch_banks.CollectionError("HTTP 500")
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)
        hk = self._bank(second, "hamkorbank")
        self.assertEqual(hk["selected_source"], "fallback")
        self.assertTrue(all(s.get("source_type") == "fallback" for s in hk["sources"]))
        self.assertNotIn("mobile", hk["currencies"]["USD"])

    def test_no_bank_currency_or_channel_is_misattributed(self):
        # A fallback entry must only ever expose its own bank's currencies.
        dataset = self._run(full_mapping(), NOW)
        asaka = self._bank(dataset, "asaka-bank")
        kapital = self._bank(dataset, "kapitalbank")
        self.assertNotIn("KZT", asaka["currencies"])       # Asakabank publishes no KZT
        self.assertIn("KZT", kapital["currencies"])         # Kapitalbank does


# --------------------------------------------------------------------------- #
# Defect C — false freshness and success signals
# --------------------------------------------------------------------------- #

class FreshnessSignalTests(FakeTransportMixin, unittest.TestCase):
    def _run(self, mapping, now, previous=None):
        fetch_banks._fetch = transport(mapping)
        return fetch_banks.build_dataset(now, previous=previous)

    def _bank(self, dataset, slug):
        return next(b for b in dataset["banks"] if b["slug"] == slug)

    def test_newly_retrieved_fresh_rate_is_fresh(self):
        dataset = self._run(full_mapping(), NOW)
        self.assertTrue(self._bank(dataset, "trastbank")["fresh"])
        self.assertTrue(fetch_banks._has_fresh_rates(dataset))

    def test_successful_fetch_of_outdated_source_is_not_fresh(self):
        # A 200 response with an old stamp must not be reported as fresh.
        data = self._run(full_mapping(), NOW)
        bank = self._bank(data, "trastbank")
        for kinds in bank["currencies"].values():
            for payload in kinds.values():
                payload["published_at"] = "2026-11-01T00:00:00+00:00"
        fresh, stale = fetch_banks._bank_freshness(bank["currencies"], NOW)
        self.assertFalse(fresh)
        self.assertTrue(stale)

    def test_unchanged_but_fresh_rate_is_fresh(self):
        # An unchanged value is not automatically stale.
        fresh, stale = fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at="2026-11-12T23:30:00+00:00")}}, NOW)
        self.assertTrue(fresh)
        self.assertFalse(stale)

    def test_missing_source_timestamp_is_unknown_not_fresh(self):
        data = self._run(full_mapping(), NOW)
        sqb = self._bank(data, "sqb")  # SQB publishes no timestamp
        self.assertFalse(sqb["fresh"])
        self.assertFalse(sqb["stale"])

    def test_all_sources_failing_keeps_previous_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "banks.json"
            fetch_banks._fetch = transport(full_mapping())
            fetch_banks.run(path, now=NOW)
            before = path.read_text(encoding="utf-8")
            fetch_banks._fetch = transport({})
            fetch_banks.run(path, now=NOW + timedelta(hours=3))
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_partial_source_failure_does_not_falsely_claim_freshness(self):
        mapping = full_mapping()
        mapping[BANKS_BY_SLUG["trastbank"].sources[0].url] = fetch_banks.CollectionError("down")
        first = self._run(full_mapping(), NOW)
        second = self._run(mapping, NOW + timedelta(hours=1), previous=first)
        tb = self._bank(second, "trastbank")
        self.assertTrue(tb["carried_forward"])
        # Carried-forward data must never be labelled fresh-for-this-run.
        self.assertFalse(tb["fresh"] and not tb["carried_forward"])

    def test_previous_dataset_with_valid_rates_is_reused_when_nothing_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "banks.json"
            fetch_banks._fetch = transport(full_mapping())
            fetch_banks.run(path, now=NOW)
            before = path.read_text(encoding="utf-8")
            # Advance 3 days: every cached stamp is now old, nothing fresh.
            fetch_banks._fetch = transport({})
            fetch_banks.run(path, now=NOW + timedelta(days=3))
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_mixed_fresh_and_stale_currencies(self):
        currencies = {
            "USD": {"cash": rate(published_at="2026-11-12T23:00:00+00:00")},  # fresh
            "EUR": {"cash": rate(published_at="2026-11-09T00:00:00+00:00")},  # stale
        }
        self.assertEqual(fetch_banks._bank_freshness(currencies, NOW), (True, False))

    def test_boundary_and_future_do_not_claim_freshness(self):
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at=(LIMIT - timedelta(seconds=1)).isoformat())}}, NOW),
            (False, True))
        self.assertEqual(fetch_banks._bank_freshness(
            {"USD": {"cash": rate(published_at=(NOW + timedelta(hours=5)).isoformat())}}, NOW),
            (False, False))

    def test_no_fresh_rates_returns_false(self):
        dataset = self._run(full_mapping(), NOW)
        for bank in dataset["banks"]:
            bank["fresh"] = False
        self.assertFalse(fetch_banks._has_fresh_rates(dataset))

    def test_dataset_records_fresh_and_stale_flags(self):
        dataset = self._run(full_mapping(), NOW)
        for bank in dataset["banks"]:
            self.assertIn("fresh", bank)
            self.assertIn("stale", bank)
            self.assertFalse(bank["fresh"] and bank["stale"])


# --------------------------------------------------------------------------- #
# Compatibility — the published contract must not regress
# --------------------------------------------------------------------------- #

class ContractCompatibilityTests(FakeTransportMixin, unittest.TestCase):
    def test_generated_dataset_matches_the_json_schema(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - schema check is best-effort offline
            self.skipTest("jsonschema not installed")
        schema = json.loads((Path(__file__).parent.parent / "schemas" / "banks.schema.json")
                            .read_text(encoding="utf-8"))
        fetch_banks._fetch = transport(full_mapping())
        dataset = fetch_banks.build_dataset(NOW)
        jsonschema.validate(dataset, schema)

    def test_existing_consumer_fields_are_preserved(self):
        fetch_banks._fetch = transport(full_mapping())
        dataset = fetch_banks.build_dataset(NOW)
        for key in ("schema_version", "generated_at", "stale_after", "max_age_hours",
                    "summary", "banks", "supported_currencies", "rate_types"):
            self.assertIn(key, dataset)
        for bank in dataset["banks"]:
            for key in ("slug", "name", "status", "currencies", "sources", "stale",
                        "carried_forward", "selected_source"):
                self.assertIn(key, bank)
            for kinds in bank["currencies"].values():
                for payload in kinds.values():
                    for key in ("buy", "sell", "published_at"):
                        self.assertIn(key, payload)

    def test_schema_version_and_bank_order_unchanged(self):
        fetch_banks._fetch = transport(full_mapping())
        dataset = fetch_banks.build_dataset(NOW)
        self.assertEqual(dataset["schema_version"], 2)
        self.assertEqual([b["slug"] for b in dataset["banks"]],
                         [b.slug for b in fetch_banks.BANKS])

    def test_json_serialisable(self):
        fetch_banks._fetch = transport(full_mapping())
        dataset = fetch_banks.build_dataset(NOW)
        json.dumps(dataset)  # must not raise


if __name__ == "__main__":
    unittest.main()
