# Ish Vaqti — currency rates

Two independent, serverless datasets, refreshed by GitHub Actions:

1. **Official Central Bank of Uzbekistan reference rates** — `data/cbu.json`
   (USD, EUR, RUB, KZT, GBP).
2. **Commercial bank buying/selling rates** for the **14 supported banks** —
   `data/banks.json`.

Runs at 09:00, 13:00, 18:00 Asia/Tashkent via GitHub Actions
(`cron: '0 4,8,13 * * *'`). GitHub Actions scheduled runs are best-effort:
they can be delayed or skipped under load, so the schedule is a target, not a
guarantee.

> **Important:** CBU reference rates are NOT commercial banks' cash or mobile
> buy/sell rates. They live in `data/cbu.json` and are never substituted into
> `data/banks.json`.

## Supported banks (14, in output order)

| # | Bank | Source | Status |
| --- | --- | --- | --- |
| 1 | Universalbank | `universalbank.uz` API (cash) | VERIFIED |
| 2 | Davr Bank | `davrbank.uz` (cash + mobile) | VERIFIED |
| 3 | Asakabank | `bank.uz` fallback (official blocked) | VERIFIED (fallback) |
| 4 | Trastbank | `trastbank.uz` (cash) | VERIFIED |
| 5 | SQB | `sqb.uz` API (cash + mobile) | VERIFIED |
| 6 | Mikrokreditbank | `mkbank.uz` open-data feed (cash + mobile) | VERIFIED |
| 7 | Ipak Yo‘li Bank | `ipakyulibank.uz` (cash + mobile) | VERIFIED |
| 8 | O‘zmilliybank | `bank.uz` fallback (official unreachable) | VERIFIED (fallback) |
| 9 | Ipoteka-bank | `ipotekabank.uz` (cash + mobile) | VERIFIED |
| 10 | Biznesni rivojlantirish banki (BRB) | `brb.uz` API (cash + mobile) | VERIFIED |
| 11 | Agrobank | `agrobank.uz` API (cash + mobile) | VERIFIED |
| 12 | Hamkorbank | `hamkorbank.uz` API → `bank.uz` fallback (official HTTP 500) | VERIFIED (fallback) |
| 13 | Xalq banki | `xb.uz` API (cash) | VERIFIED |
| 14 | Kapitalbank | `bank.uz` fallback (official Cloudflare 403) | VERIFIED (fallback) |

Every bank is read from its own official domain or an authorised public API.
For the four banks whose official source is unreachable, the collector falls
back to the `bank.uz` aggregator, which is crawled only as its `robots.txt`
permits and with the bank's identity confirmed on each page. The official
source is always tried first; a fallback is used only when the official source
yields no rates; official and fallback values are never mixed, and the entry
records `selected_source` (`official` or `fallback`) plus a `reason` naming the
official failure. See `docs/official-sources.md` for the per-bank verification
record and the fallback policy.

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
      "fresh": false,                 // true only if a source stamp is within max_age_hours
      "carried_forward": false,
      "reason": null,
      "selected_source": "official",  // official | fallback | null
      "source_transition": null,      // {"from","to"} when the source class changed
      "sources": [
        { "kind": "sqb-api", "url": "https://sqb.uz/api/site-kurs-api/",
          "rate_type": "cash", "source_type": "official", "status": "ok" }
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
* `fresh` / `stale` describe the source's own publication time, judged from the
  real instant (offset-aware, normalised to UTC), never from string ordering:
  `fresh` is true only when at least one rate was published within
  `max_age_hours` of `generated_at`; `stale` is true when the bank publishes
  rates whose known instants are all older than that. When no usable instant
  exists (missing, malformed, offset-less or future-dated stamps) both are
  `false`: freshness is *unknown* and is never reported as fresh. A successful
  HTTP fetch of an outdated source is therefore not treated as fresh data.
* `status: "stale"` means the bank could not be refreshed and its last verified
  rates are being served; `carried_forward: true` marks those rates.
* `selected_source` says which source class produced the rates: `official` (the
  bank's own source), `fallback` (the verified `bank.uz` fallback) or `null`
  (unavailable). A `fallback` entry also carries a `reason` naming the official
  failure. Each `sources[]` entry carries the same distinction in `source_type`.
  Carry-forward never mixes classes: a rate retained from the previous dataset is
  reused only when the previous and current runs used the *same* class, so every
  published rate shares its entry's single `selected_source`. A class change is
  recorded in `source_transition` and the other class's rates are dropped, not
  relabelled.
* A failed refresh never overwrites the last verified dataset, and never
  publishes a dataset with no rates at all.

## Data integrity

* Updates are atomic: the file is written to a temporary file and renamed.
* Every dataset is validated before publishing (`scripts/validate_data.py`).
* If a refresh fails, or would publish no fresh rates, `data/banks.json` is left
  untouched.
* Clients must refuse to calculate with rates older than `max_age_hours` (24).

### Freshness policy

A request succeeding is not proof of fresh data. The collector keeps the concepts
separate: HTTP success, parse success, valid rates, *newly retrieved this run*,
publication time known, and publication time within `max_age_hours`.

* Freshness is decided from the source's own `published_at` instant, parsed and
  normalised to UTC. ISO strings are never compared lexicographically.
* A timestamp with no UTC offset is a bank's local wall-clock time; it is treated
  as *unknown* rather than assumed to be UTC (assuming would shift the instant by
  hours). Malformed and future-dated stamps are likewise unknown.
* A rate whose publication time is unknown is never reported as `fresh`.
* Carried-forward rates keep their original `published_at`; a run that only reuses
  old data cannot refresh `generated_at`.
* `generated_at`, `published_at`, `stale_after` and `max_age_hours` keep their
  established meaning; `fresh` and `source_transition` are additive fields.

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
* Four banks (Asakabank, O‘zmilliybank, Hamkorbank, Kapitalbank) have no
  reachable official rate source and are served from the verified `bank.uz`
  fallback (`selected_source: "fallback"`). KZT is available for O‘zmilliybank
  and Kapitalbank through that fallback; other banks publish no personal-channel
  KZT, so it stays `null` rather than being fabricated. GBP and RUB are not
  offered by all banks. See `docs/official-sources.md`.
* GitHub Actions scheduled runs are best-effort and may be delayed.

