"""Tests for dataset validation and the static Pages bundle."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import build_site, validate_data

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


class ValidateDataTests(unittest.TestCase):
    def test_published_banks_dataset_is_valid(self):
        data = validate_data.validate_banks(DATA / "banks.json")
        self.assertEqual(data["summary"]["banks_total"], 14)

    def test_published_cbu_dataset_is_valid(self):
        data = validate_data.validate_cbu(DATA / "cbu.json")
        self.assertEqual(data["schema_version"], 1)

    def test_schema_file_describes_version_two(self):
        schema = validate_data.validate_schema_file(ROOT / "schemas" / "banks.schema.json")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)

    def test_missing_file_fails(self):
        with self.assertRaises(SystemExit):
            validate_data.validate_banks(Path("/nonexistent/banks.json"))

    def test_invalid_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "banks.json"
            path.write_text("{oops", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_data.validate_banks(path)

    def test_reordered_banks_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads((DATA / "banks.json").read_text(encoding="utf-8"))
            data["banks"].reverse()
            path = Path(tmp) / "banks.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_data.validate_banks(path)

    def test_zero_rate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads((DATA / "banks.json").read_text(encoding="utf-8"))
            data["banks"][0]["currencies"]["USD"]["cash"]["buy"] = 0
            path = Path(tmp) / "banks.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_data.validate_banks(path)

    def test_missing_source_url_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads((DATA / "banks.json").read_text(encoding="utf-8"))
            data["banks"][0]["sources"][0]["url"] = "http://insecure.example"
            path = Path(tmp) / "banks.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_data.validate_banks(path)


class BuildSiteTests(unittest.TestCase):
    def test_build_produces_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "_site"
            build_site.build(output)
            for name in ("index.html", "app.js", "styles.css", ".nojekyll",
                         "data/banks.json", "data/cbu.json"):
                self.assertTrue((output / name).exists(), f"missing {name}")

    def test_bundled_dataset_matches_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "_site"
            build_site.build(output)
            bundled = json.loads((output / "data" / "banks.json").read_text(encoding="utf-8"))
            source = json.loads((DATA / "banks.json").read_text(encoding="utf-8"))
            self.assertEqual(bundled, source)

    def test_nojekyll_present_for_verbatim_serving(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "_site"
            build_site.build(output)
            self.assertEqual((output / ".nojekyll").read_text(encoding="utf-8"), "")


class SiteClientTests(unittest.TestCase):
    """The client must implement the stale-data contract."""

    def setUp(self):
        self.js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    def test_client_reads_max_age_hours(self):
        self.assertIn("max_age_hours", self.js)

    def test_client_uses_generated_at(self):
        self.assertIn("generated_at", self.js)

    def test_client_renders_all_banks_from_dataset(self):
        self.assertIn("dataset.banks.forEach", self.js)

    def test_client_supports_both_rate_types(self):
        self.assertIn("mobile", (ROOT / "site" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
