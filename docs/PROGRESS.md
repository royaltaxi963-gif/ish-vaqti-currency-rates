# Progress checkpoint

Durable state for resuming this work. Update after each verified increment.

## Status: official + verified-fallback collection complete, 14/14 coverage

Branch `feat/official-bank-sources`, PR #2. Last verified: 2026-11-13
(Asia/Tashkent) with a live collection run reaching **14/14** banks.

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

* `python -m unittest discover -s tests` → all pass (8 skipped live tests).
* `ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources` → 8 passed;
  live collection reached **14/14** banks.
* `python -m scripts.fetch_banks` → `verified rates for 14/14 banks`.
* `python -m scripts.validate_data` → `OK: 14/14 banks with rates`.
* Dataset validates against `schemas/banks.schema.json` with `jsonschema`
  (draft 2020-12, `additionalProperties: false`).
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
