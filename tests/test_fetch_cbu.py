import unittest
from scripts.fetch_cbu import parse_rates

class RatesTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"Ccy": code, "Rate": "12500.50", "Nominal": "1", "Date": "12.11.2026"}
                     for code in ("USD", "EUR", "RUB", "KZT", "GBP")]

    def test_complete(self):
        self.assertEqual(len(parse_rates(self.rows, "now")["rates"]), 5)

    def test_nominal(self):
        self.rows[2]["Nominal"] = "100"
        self.assertEqual(parse_rates(self.rows, "now")["rates"]["RUB"]["rate_uzs"], 125.005)

    def test_missing_fails(self):
        with self.assertRaises(ValueError):
            parse_rates(self.rows[:-1], "now")

    def test_zero_fails(self):
        self.rows[0]["Rate"] = "0"
        with self.assertRaises(ValueError):
            parse_rates(self.rows, "now")

if __name__ == "__main__":
    unittest.main()
