# Progress checkpoint

Durable state for resuming this work. Update after each verified increment.

## Status: implementation complete, awaiting review

Last verified: 2026-11-12 (Asia/Tashkent evening), live collection of all 14 banks.

## Done

* `scripts/banks.py` — authoritative 14-bank registry in required output order.
* `scripts/bank_parsers.py` — parsers for bank.uz, SQB API, BRB API, Davr HTML.
* `scripts/fetch_banks.py` — concurrent collector, schema v2 dataset, atomic
  writes, previous-dataset preservation, staleness flags.
* `scripts/validate_data.py` — dataset + schema validation (no dependencies).
* `scripts/build_site.py` + `site/` — static GitHub Pages bundle with a
  stale-aware client.
* `scripts/check_endpoints.py` — probes the public distribution endpoints.
* `schemas/banks.schema.json` — versioned JSON Schema (draft 2020-12).
* `docs/endpoints.md` — endpoint and fallback-hosting documentation.
* `.github/workflows/update-rates.yml` — schedule, tests, refresh, commit,
  Pages deploy (with `enablement: true`).
* `tests/` — 76 offline tests + 4 live-source tests (opt-in via `ISH_VAQTI_LIVE=1`).

## Verified evidence

* Live collection: 14/14 banks returned rates (2026-11-12).
* `python -m unittest discover -s tests` → 76 passed, 4 skipped.
* `ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources` → 4 passed.
* `python -m scripts.validate_data` → `OK: 14/14 banks with rates`.
* `python -m scripts.build_site` → `_site/` bundle; rendered in a browser, all
  14 banks in order.

## Open items

* GitHub Pages could not be enabled via the REST API with the current token
  (`Resource not accessible by integration`). The workflow sets
  `enablement: true` on `actions/configure-pages`, which enables Pages on the
  first run. If that is rejected, enable Pages manually:
  Settings → Pages → Source = GitHub Actions.
* Pull request is open against `main`; do not merge without user approval.

## Next steps

1. Merge the PR (needs user approval).
2. Confirm the first workflow run succeeds and Pages deploys.
3. Run `python -m scripts.check_endpoints` to confirm the public URLs.
4. Optional: wire the Ish Vaqti HTML app to `data/banks.json` (needs explicit
   authorization; the app is currently untouched).
