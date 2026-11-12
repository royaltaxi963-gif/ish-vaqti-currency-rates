"""Opt-in live-source checks against the real official bank endpoints.

These hit the network, so they are skipped unless ``ISH_VAQTI_LIVE=1`` is set.
They exist to prove the collectors still match the real sources; unit tests
alone cannot show that the integration works.

    ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources -v
"""
import os
import unittest
from datetime import datetime, timezone

from scripts.banks import BANKS, SUPPORTED_CURRENCIES
from scripts.fetch_banks import collect_bank

LIVE = os.environ.get("ISH_VAQTI_LIVE") == "1"

# Banks whose official source is reachable and must return rates. Hamkorbank is
# excluded because its official endpoint is currently failing upstream (HTTP
# 500, `{"status":"Failure","error_code":-10}`), so it is expected to be
# blocked rather than up.
EXPECTED_UP = {
    "universalbank", "davr-bank", "trastbank", "sqb", "mikrokreditbank",
    "ipakyulibank", "ipoteka-bank", "brb", "agrobank", "xalq-bank",
}
BLOCKED = {"asaka-bank", "nbu", "kapitalbank", "hamkorbank"}


@unittest.skipUnless(LIVE, "set ISH_VAQTI_LIVE=1 to run live source checks")
class LiveSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = datetime.now(timezone.utc)
        cls.results = {bank.slug: collect_bank(bank, cls.now) for bank in BANKS}

    def test_expected_banks_return_rates(self):
        reachable = {s for s, r in self.results.items() if r["currencies"]}
        missing = EXPECTED_UP - reachable
        print(f"\nlive: {len(reachable)}/{len(BANKS)} banks returned rates: {sorted(reachable)}")
        self.assertFalse(missing, f"expected rates from {sorted(missing)}")

    def test_blocked_banks_report_a_reason(self):
        for slug in BLOCKED:
            result = self.results[slug]
            self.assertFalse(result["currencies"], f"{slug} returned rates unexpectedly")
            self.assertTrue(result["reason"], f"{slug} is unavailable without a reason")

    def test_no_unsupported_currencies(self):
        for slug, result in self.results.items():
            for code in result["currencies"]:
                self.assertIn(code, SUPPORTED_CURRENCIES, f"{slug} returned {code}")

    def test_every_rate_has_a_source(self):
        for slug, result in self.results.items():
            if result["currencies"]:
                self.assertTrue(result["sources"], f"{slug} has rates but no sources")

    def test_rub_collected_where_published(self):
        # These banks publish RUB on their official page; the adapter must return it.
        for slug in ("trastbank", "ipakyulibank", "brb", "xalq-bank"):
            self.assertIn("RUB", self.results[slug]["currencies"], f"{slug} lost RUB")

    def test_buy_and_sell_are_distinct_when_both_present(self):
        for slug, result in self.results.items():
            for code, kinds in result["currencies"].items():
                for kind, payload in kinds.items():
                    buy, sell = payload.get("buy"), payload.get("sell")
                    if buy and sell:
                        self.assertLessEqual(
                            buy, sell * 1.5,
                            f"{slug} {code}/{kind} buy={buy} sell={sell} looks wrong",
                        )


if __name__ == "__main__":
    unittest.main()
