# Ish Vaqti — currency rates

Two independent, serverless datasets, refreshed by GitHub Actions:

1. **Official Central Bank of Uzbekistan reference rates** — `data/cbu.json`
   (USD, EUR, RUB, KZT, GBP).
2. **Commercial bank buying/selling rates** for the **14 supported banks** —
   `data/banks.json`.

Runs at 09:00, 12:00, 15:00, 18:00 Asia/Tashkent via GitHub Actions
(`cron: '0 4,7,10,13 * * *'`). GitHub Actions scheduled runs are best-effort:
they can be delayed or skipped under load, so the schedule is a target, not a
guarantee.

> **Important:** CBU reference rates are NOT commercial banks' cash or mobile
> buy/sell rates. They live in `data/cbu.json` and are never substituted into
> `data/banks.json`.

## Supported banks (14, in output order)

| # | Bank | Official source | Status |
| --- | --- | --- | --- |
| 1 | Universalbank | `universalbank.uz` API (cash) | VERIFIED |
| 2 | Davr Bank | `davrbank.uz` (cash + mobile) | VERIFIED |
| 3 | Asakabank | `asakabank.uz` (client-side, no public API) | BLOCKED |
| 4 | Trastbank | `trastbank.uz` (cash) | VERIFIED |
| 5 | SQB | `sqb.uz` API (cash + mobile) | VERIFIED |
| 6 | Mikrokreditbank | `mkbank.uz` open-data feed (cash + mobile) | VERIFIED |
| 7 | Ipak Yo‘li Bank | `ipakyulibank.uz` (cash + mobile) | VERIFIED |
| 8 | O‘zmilliybank | `nbu.uz` (unreachable) | BLOCKED |
| 9 | Ipoteka-bank | `ipotekabank.uz` (cash + mobile) | VERIFIED |
| 10 | Biznesni rivojlantirish banki (BRB) | `brb.uz` API (cash + mobile) | VERIFIED |
| 11 | Agrobank | `agrobank.uz` API (cash + mobile) | VERIFIED |
| 12 | Hamkorbank | `hamkorbank.uz` API (upstream HTTP 500) | BLOCKED |
| 13 | Xalq banki | `xb.uz` API (cash) | VERIFIED |
| 14 | Kapitalbank | `kapitalbank.uz` (Cloudflare 403) | BLOCKED |

Every bank is read from its own official domain or an authorised public API.
See `docs/official-sources.md` for the per-bank verification record. A bank
whose official source cannot be reached is reported as `unavailable`/blocked
with an explicit reason — never via a third-party aggregator.

Rates are genuinely published by each bank. `null` means the bank does not
publish that rate — it is never fabricated. Currencies and rate types a bank
does not publish are simply absent from its `currencies` object.

## Data model

`data/banks.json` (`schema_version: 2`, see `schemas/banks.schema.json`):

```jsonc
{
  "schema_version": 2,
  "generated_at": "2026-11-12T16:47:47+00:00",  // collection time
  "max_age_hours": 24,
  "stale_after": "2026-11-13T16:47:47+00:00",    // refuse to calculate after this
  "supported_currencies": ["USD", "EUR", "RUB", "KZT", "GBP"],
  "rate_types": ["cash", "mobile"],
  "summary": { "banks_total": 14, "banks_with_rates": 14 },
  "banks": [
    {
      "slug": "sqb",
      "name": "SQB",
      "status": "verified",           // verified | partial | stale | unavailable
      "stale": false,
      "carried_forward": false,
      "reason": null,
      "sources": [
        { "kind": "sqb-api", "url": "https://sqb.uz/api/site-kurs-api/",
          "rate_type": "cash", "status": "ok" }
      ],
      "currencies": {
        "USD": {
          "cash":   { "buy": 11930.0, "sell": 12020.0, "published_at": null },
          "mobile": { "buy": 11940.0, "sell": 12010.0, "published_at": null }
        }
      }
    }
  ]
}
```

* `buy` / `sell` are UZS per 1 unit of the currency.
* `published_at` is the source's own publication time, distinct from
  `generated_at` (the collection time). `null` when the source publishes none.
* `status: "stale"` means the bank could not be refreshed and its last verified
  rates are being served; `carried_forward: true` marks those rates.
* A failed refresh never overwrites the last verified dataset, and never
  publishes a dataset with no rates at all.

## Data integrity

* Updates are atomic: the file is written to a temporary file and renamed.
* Every dataset is validated before publishing (`scripts/validate_data.py`).
* If a refresh fails, or would publish no fresh rates, `data/banks.json` is left
  untouched.
* Clients must refuse to calculate with rates older than `max_age_hours` (24).

## Public endpoints

See `docs/endpoints.md`. Primary GitHub Pages endpoint plus jsDelivr and
raw.githubusercontent.com fallbacks (all free; no Cloudflare):

```
https://royaltaxi963-gif.github.io/ish-vaqti-currency-rates/data/banks.json
https://cdn.jsdelivr.net/gh/royaltaxi963-gif/ish-vaqti-currency-rates@main/data/banks.json
https://raw.githubusercontent.com/royaltaxi963-gif/ish-vaqti-currency-rates/main/data/banks.json
```

## Run locally

```bash
python -m unittest discover -s tests -v          # offline unit tests
ISH_VAQTI_LIVE=1 python -m unittest tests.test_live_sources -v   # live source checks
python -m scripts.fetch_cbu                      # official reference rates
python -m scripts.fetch_banks                    # commercial bank rates
python -m scripts.validate_data                  # validate published datasets
python -m scripts.build_site                     # build the _site/ Pages bundle
python -m scripts.check_endpoints                # probe the public endpoints
```

## Limitations

* Not every bank publishes a distinct mobile rate; banks that publish cash only
  report `cash`. SQB, BRB, Davr, Ipak Yo‘li, Mikrokreditbank, Agrobank,
  Hamkorbank and Ipoteka-bank publish a mobile/app (or ATM) rate as well.
* KZT is not offered on the personal cash/mobile channels of any reachable
  official source, so it stays `null`; GBP and RUB are not offered by all banks.
* Four banks are currently blocked and reported as `unavailable` with a reason
  (Asakabank, O‘zmilliybank, Hamkorbank, Kapitalbank); see
  `docs/official-sources.md`.
* GitHub Actions scheduled runs are best-effort and may be delayed.

