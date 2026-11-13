# Progress checkpoint

Durable state for resuming this work. Update after each verified increment.

## Status: official + verified-fallback collection complete; integrity sprint done

Branch `feat/official-bank-sources`, PR #2. Two verified increments:

1. Official + verified-fallback collection, 14/14 coverage (2026-11-13).
2. Data-integrity sprint fixing three reviewed defects — timestamp comparison,
   mixed-source carry-forward, false freshness signals.

## Data-integrity sprint (defects A/B/C)

* **Defect A (timestamps).** Freshness is now decided from real instants, not
  `max()` over ISO strings. `_parse_instant` normalises offset-aware stamps to
  UTC; `_bank_freshness` classifies a bank as fresh / stale / unknown. Naive
  (offset-less), malformed and future-dated stamps are treated as *unknown*, not
  assumed to be UTC.
* **Defect B (provenance).** Carry-forward never mixes source classes. A retained
  rate is reused only when the previous and current runs used the same class, so
  every published rate shares its entry's single `selected_source`. A class change
  is recorded in the additive `source_transition` field and the other class's
  rates are dropped rather than relabelled.
* **Defect C (freshness).** `_has_fresh_rates` no longer equates "newly retrieved"
  with "fresh"; it requires a source instant within `max_age_hours`. A successful
  fetch of an outdated source cannot publish a fresh-looking dataset, and the run
  keeps the previous file instead of refreshing `generated_at`.

Regression tests: `tests/test_freshness_and_provenance.py` (38 tests).

## Done

* `scripts/banks.py` — authoritative 14-bank registry in required output order.
  Each bank points at its **own official domain** (or an authorised public API).
  Four banks (Asakabank, O'zmilliybank, Hamkorbank, Kapitalbank) additionally
  carry a `fallback` — the verified `bank.uz` source — used only when the
  official source yields no rates. `Source` carries `source_type`
  (`official`/`fallback`) and, for a fallback, `expect` identity tokens.
* `scripts/bank_parsers.py` — one parser per source: Universalbank, Davr,
  Trastbank, SQB, Mikrokreditbank, Ipak Yo'li, Ipoteka, BRB, Agrobank,
  Hamkorbank, Xalq banki, and the new `bankuz-html` fallback parser (unit- and
  channel-aware). `bank.uz` is never used as an official source.
* `scripts/fetch_banks.py` — concurrent collector, schema v2 dataset, atomic
  writes, previous-dataset preservation, staleness flags, per-cycle URL cache.
  Source selection: official first, fallback only when official yields nothing;
  a fallback page must name the bank (identity check) or it is refused; official
  and fallback values are never mixed. Each entry records `selected_source` and
  a `reason`; each `sources[]` entry records `source_type`.
* `scripts/validate_data.py` — dataset + schema validation (no dependencies).
* `schemas/banks.schema.json` — adds optional `selected_source` per bank and
  `source_type` per source (backward-compatible additions; consumers unaffected).
* `docs/official-sources.md` — per-bank verification matrix, evidence and the
  bank.uz fallback policy (robots permission, identity, precedence, provenance,
  units, timestamps, cross-checks).
* `tests/` — offline tests (fixtures incl. four sanitized bank.uz pages) plus 8
  opt-in live-source tests.

## Verified evidence

* `python -m unittest discover -s tests` → 183 pass (8 skipped live tests).
* `python -m unittest tests.test_freshness_and_provenance` → 38 pass.
* `ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources` → 8 passed;
  live collection reached **14/14** banks.
* `python -m scripts.fetch_banks` → `verified rates for 14/14 banks (10 fresh)`.
* `python -m scripts.validate_data` → `OK: 14/14 banks with rates`.
* Dataset validates against `schemas/banks.schema.json` with `jsonschema`
  (draft 2020-12, `additionalProperties: false`).
* Freshness split of the published dataset: 10 fresh, 3 stale (Universalbank,
  Davr, Xalq — daily stamps older than 24h), 1 unknown (SQB publishes no stamp).
* GitHub Actions **PR validation** (`.github/workflows/pr-validation.yml`) is
  green on PR #2: run 43378722810, `pull_request`, conclusion `success`, all 8
  steps passed, 0 failed. It is `contents: read`, runs no live collection, and
  writes nothing (the "Assert the checks did not modify tracked data" step
  passed). PR #2 was `dirty` (a `data/banks.json` conflict with main's scheduled
  refresh) which blocks `pull_request` runs; the conflict was resolved by
  merging main into the branch, after which the run started automatically.
* RUB is collected from every bank that publishes it (Trastbank, Ipak Yo'li,
  BRB, Xalq, Agrobank/SQB/Universalbank/MKBank sell-side, and the four
  fallback banks). KZT is now available for O'zmilliybank and Kapitalbank via
  the fallback; other banks publish no personal-channel KZT, so it stays `null`.

## Fallback banks (official source unreachable, served from bank.uz)

* **Asakabank** — Nuxt SPA; rates load client-side from `back.asakabank.uz`; no
  public rate endpoint reachable (403 on every path).
* **O'zmilliybank (NBU)** — `nbu.uz` (185.104.210.5) refuses ports 80/443;
  `mobile.nbu.uz` returns 403.
* **Kapitalbank** — Cloudflare anti-bot challenge (HTTP 403); not bypassed.
* **Hamkorbank** — official endpoint `api-dbo.hamkorbank.uz/webflow/v1/exchanges`
  currently returns HTTP 500 `{"status":"Failure","error_code":-10}` for every
  request; the `/uz/exchange-rate/` page ships no server-rendered rates. Its
  parser is retained and used the moment the endpoint recovers.

## Open items

* GitHub Pages enablement (infrastructure-owned) is out of scope here.
* Pull request #2 is open against `main`; do not merge without user approval.

## Next steps

1. Review the integration PR.
2. Re-run the live source checks after the next upstream layout change.
3. If a fallback bank publishes a public API later, add an official adapter —
   the collector will then prefer it automatically over the fallback.
