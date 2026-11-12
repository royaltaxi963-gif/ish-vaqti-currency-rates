# Progress checkpoint

Durable state for resuming this work. Update after each verified increment.

## Status: official-source migration implemented, awaiting review

Last verified: 2026-11-12 (Asia/Tashkent evening) with a live collection run.

## Done

* `scripts/banks.py` — authoritative 14-bank registry in required output order.
  Each bank points at its **own official domain** (or an authorised public API).
  Banks whose official source is unreachable are recorded with no source and an
  explicit `unavailable_reason`.
* `scripts/bank_parsers.py` — one parser per official source:
  Universalbank, Davr, Trastbank, SQB, Mikrokreditbank, Ipak Yo'li, Ipoteka,
  BRB, Agrobank, Hamkorbank, Xalq banki. `bank.uz` parsing was removed.
* `scripts/fetch_banks.py` — concurrent collector, schema v2 dataset, atomic
  writes, previous-dataset preservation, staleness flags, per-cycle URL cache
  (a shared URL is fetched once), and carry-forward that is disabled when a
  bank's source set changes or the bank is deliberately blocked.
* `scripts/validate_data.py` — dataset + schema validation (no dependencies);
  now accepts a blocked bank with no sources when it carries a reason.
* `schemas/banks.schema.json` — unchanged versioned JSON Schema (draft 2020-12).
* `docs/official-sources.md` — per-bank verification matrix and evidence.
* `tests/` — 113 offline tests + 6 opt-in live-source tests.

## Verified evidence

* `python -m unittest discover -s tests` → 113 passed, 4 skipped.
* `ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources` → 6 passed;
  live collection reached **10/14** banks: agrobank, brb, davr-bank,
  ipakyulibank, ipoteka-bank, mikrokreditbank, sqb, trastbank, universalbank,
  xalq-bank.
* `python -m scripts.fetch_banks` → `verified rates for 10/14 banks`.
* `python -m scripts.validate_data` → `OK: 10/14 banks with rates`.
* RUB is collected from every bank that publishes it (Trastbank, Ipak Yo'li,
  BRB, Xalq, Agrobank sell-side, SQB sell-side, Universalbank sell-side,
  MKBank sell-side, Hamkorbank).

## Blocked banks (not fabricated)

* **Asakabank** — Nuxt SPA; rates load client-side from `back.asakabank.uz`; no
  public rate endpoint reachable.
* **O'zmilliybank (NBU)** — `nbu.uz` (185.104.210.5) refuses ports 80/443.
* **Kapitalbank** — Cloudflare anti-bot challenge (HTTP 403); not bypassed.

Hamkorbank's official endpoint is intermittently `503`; when it fails the
collector preserves the last verified rates with their original timestamps.

## Open items

* GitHub Pages enablement (infrastructure-owned) is out of scope here.
* Pull request is open against `main`; do not merge without user approval.

## Next steps

1. Review the integration PR.
2. Re-run the live source checks after the next upstream layout change.
3. If a blocked bank publishes a public API later, add an adapter and move it
   from `unavailable_reason` to a `Source`.
