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

| # | Bank | Verified source |
| --- | --- | --- |
| 1 | Universalbank | bank.uz |
| 2 | Davr Bank | davrbank.uz (cash + mobile) |
| 3 | Asakabank | bank.uz |
| 4 | Trastbank | bank.uz |
| 5 | SQB | sqb.uz API (cash + mobile) |
| 6 | Mikrokreditbank | bank.uz |
| 7 | Ipak Yo‘li Bank | bank.uz |
| 8 | O‘zmilliybank | bank.uz |
| 9 | Ipoteka-bank | bank.uz |
| 10 | Biznesni rivojlantirish banki (BRB) | brb.uz API (cash + mobile) |
| 11 | Agrobank | bank.uz |
| 12 | Hamkorbank | bank.uz |
| 13 | Xalq banki | bank.uz |
| 14 | Kapitalbank | bank.uz |

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

* bank.uz exposes a single cash/card rate per currency and does not split cash
  from mobile, so those banks report `cash` only. SQB, BRB and Davr publish a
  distinct mobile rate and report both.
* KZT is published by only some banks; GBP and RUB are not offered by all.
* GitHub Actions scheduled runs are best-effort and may be delayed.

