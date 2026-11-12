# Official bank rate sources — verification record

This document records, for each of the 14 supported banks, the official source
the collector uses, how it was verified, and its current status. The previous
implementation read 11 of the 14 banks from `bank.uz`, a third-party
aggregator. That is now forbidden: every bank is read from its own official
domain or an authorised public API, or reported as **blocked**.

All HTTP results below were re-verified on 2026-11-12/13 (Asia/Tashkent) with a
plain `urllib`/`curl` request and a normal desktop User-Agent, plus a headless
Chromium render for the client-rendered pages. No CAPTCHA or access-control
control was bypassed. Rates are UZS per 1 unit unless noted.

## Verification matrix

| # | Bank | Official source | HTTP | USD | EUR | RUB | KZT | GBP | Cash | Mobile | Status |
|---|------|-----------------|------|-----|-----|-----|-----|-----|------|--------|--------|
| 1 | Universalbank | `universalbank.uz/api/currencies/daily` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | – | VERIFIED |
| 2 | Davr Bank | `davrbank.uz/uz/exchange-rate` | 200 | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | VERIFIED |
| 3 | Asakabank | `asakabank.uz` (client-side, `back.asakabank.uz`) | – | – | – | – | – | – | – | – | BLOCKED |
| 4 | Trastbank | `trastbank.uz/uz/services/exchange-rates/` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | – | VERIFIED |
| 5 | SQB | `sqb.uz/api/site-kurs-api/` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 6 | Mikrokreditbank | `mkbank.uz/uz/services/open_data/rates/json/` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 7 | Ipak Yo‘li Bank | `ipakyulibank.uz/physical/valyuta-ayirboshlash` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | ✓ | VERIFIED |
| 8 | O‘zmilliybank (NBU) | `nbu.uz` | 000 | – | – | – | – | – | – | – | BLOCKED |
| 9 | Ipoteka-bank | `ipotekabank.uz/services/currency/` | 200 | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | VERIFIED |
| 10 | BRB | `brb.uz/api/currency/compare?type=jismoniy` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | ✓ | VERIFIED |
| 11 | Agrobank | `agrobank.uz/api/v1/?action=pages&code=uz/person/exchange_rates` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 12 | Hamkorbank | `api-dbo.hamkorbank.uz/webflow/v1/exchanges` | 500* | – | – | – | – | – | – | – | BLOCKED (upstream) |
| 13 | Xalq banki | `xb.uz/api/v1/external/client/exchange-rate/last-thirty-day` | 200 | ✓ | ✓ | ✓ | – | – | ✓ | – | VERIFIED |
| 14 | Kapitalbank | `kapitalbank.uz` | 403 | – | – | – | – | – | – | – | BLOCKED |

`✓ (sell only)` means the bank genuinely does not publish a buying rate for that
currency; the value is stored as `null`, not fabricated.

\* Hamkorbank's official endpoint is currently failing upstream: it returns
HTTP `500` `{"status":"Failure","error_code":-10,"error_note":"internal
error","data":null}` for every request (with and without browser headers, and
from a browser fetch context). The `/uz/exchange-rate/` page itself still
returns `200` but ships no server-rendered rates — its table is populated by
that same failing call — so no official rate value is reachable right now. The
bank is therefore treated as blocked upstream; the last verified rates are
carried forward with their original timestamps rather than overwritten.

No bank among the 14 publishes a personal cash or mobile KZT rate on an
official page that was reachable. SQB's public API does carry a KZT row, but
only under its `juridic` (legal-entity) channel, which is out of scope; the
personal `offline`/`online`/`atm` channels omit KZT. KZT therefore stays `null`
everywhere and the collector does not invent it.

## Per-bank notes

### Universalbank — `GET /api/currencies/daily`
JSON `{items: [...]}`. Each item is keyed by ISO 4217 **numeric** code
(`840`, `978`, `643`, `826`), so the parser maps numeric → alpha-3.
`hasBuyingRate`/`hasSellingRate` are `false` when the bank does not transact
that side; the raw value is then `0.00` and is dropped. `nominal` is the unit
count (1). Channel: branch cash (`rateDate` = effective date).

### Davr Bank — `/uz/exchange-rate`
Server-rendered HTML with two tables, headed *Bank ofislarida valyutalar kursi*
(cash) and *Mobil ilovada valyutalar kursi* (mobile). Columns are
`Valyuta | MB | Sotuv | Xarid`. The `MB` column is the CBU reference rate and is
**ignored**; `Sotuv` is the bank's selling price and `Xarid` the buying price.
RUB is not published (all-zero rows are dropped).

### Asakabank — BLOCKED
`asakabank.uz` is a Nuxt SPA. The rate table on
`/uz/press-center/exchange-rates` is rendered client-side; the served HTML
contains no rates (only CSS/markup). Reverse-engineering the Nuxt config gives
`apiBase = https://back.asakabank.uz`, but that host answers HTTP 403 to every
path from the collector network (`/`, `/rates`, `/exchange-rates`, `/v1/rates`,
`/openapi.json`), and no public rate route is documented. The bank is recorded
as blocked with this reason; no third-party aggregator is substituted.

### Trastbank — `/uz/services/exchange-rates/`
Server-rendered table `Valyuta | Sotib olish | Sotish | MB kursi`, plus a stamp
`Sotib olish/Sotish - DD.MM.YYYY HH:MM dan`. The `MB kursi` column is the CBU
reference rate and is ignored.

### SQB — `GET /api/site-kurs-api/`
JSON `{data: {offline, online, atm, juridic}}`. `offline` rows are branch cash
and are integers **scaled by 100** (`1193000` → `11930.00`); `online` and `atm`
rows are already in UZS. `online` (app) fills `mobile`; `atm` fills `mobile`
only when the app rate is absent. `juridic` (legal-entity) rows are ignored;
they are the only rows that carry KZT, so SQB contributes no KZT to the
personal-channel dataset.

### Mikrokreditbank — `/uz/services/open_data/rates/json/`
Published open-data feed of G1..G5 fields. `G1` is the stamp
`DD.MM.YYYY HH:MM:SS`; `G2` is the channel (`BANK` cash / `APP` / `ATM`);
`G3` the currency; `G4` the buying rate and `G5` the selling rate. The earlier
integration failure was a timestamp-format bug — the collector could not parse
`DD.MM.YYYY` and stored `published_at: null` — which is fixed here.

### Ipak Yo‘li Bank — `/physical/valyuta-ayirboshlash`
Nuxt page with an inline `__NUXT_DATA__` graph holding three tabs: `Ilovada`
(app), `Kassada` (branch cash) and `Bankomatda` (ATM). Rates are integers
**scaled by 100**; `lastUpdated` is a Unix epoch. The app rate fills `mobile`;
the ATM rate fills `mobile` only when the app does not publish that currency.

### O‘zmilliybank (NBU) — BLOCKED
`nbu.uz` resolves to `185.104.210.5` (`www.nbu.uz` shares it). The host accepts
no TCP connection on port 80 or 443 from the collector network: both a
`urllib` request and a raw `socket`/TLS handshake time out (`000`). Alternative
hosts (`api.nbu.uz`, `open.nbu.uz`, `online.nbu.uz`, `my.nbu.uz`) do not
resolve; `mobile.nbu.uz` resolves but returns HTTP 403. Recorded as blocked.

### Ipoteka-bank — `/services/currency/`
One official index page publishes every currency across three tabs:
`Filialda` (branch cash, `#all`), `Bankomatda` (ATM, `#atms`) and `Ilovada`
(app, `#mobileApp`). Each panel is a `Valyuta | Xarid | Sotish | MB kursi`
table; `Xarid` is the bank's buying price, `Sotish` the selling price and
`MB kursi` the CBU reference value, which is ignored. The stamp is an ISO
`<time datetime="...">` (Asia/Tashkent). The app rate fills `mobile`; the ATM
rate fills `mobile` only for a currency the app does not publish. This replaces
the previous per-currency pages (`/usd-uzs/`, `/eur-uzs/`) and now also yields
GBP plus the mobile channel in a single request. The bank publishes no RUB
quote here, so RUB stays `null` rather than being fabricated.

### BRB — `GET /api/currency/compare?type=jismoniy`
JSON `{data: [...]}`; values are integers **scaled by 100**. The `MOBIL …` rows
are the mobile-app rates; every other row is branch cash. `updated_at` is the
publication stamp.

### Agrobank — `GET /api/v1/?action=pages&code=uz/person/exchange_rates`
JSON `{success: true, data: {sections: [...]}}`. Within each section, a `tab`
block (`office` → cash, `atm` → mobile) precedes a `currency-rates` block whose
items are `{alpha3, buy, rate, sale, updated}`. `rate` is the CBU reference
value and is ignored; `buy`/`sale` are the bank's prices. A zero side is
dropped.

### Hamkorbank — `GET /webflow/v1/exchanges`
JSON `{data: [...]}`; values are integers **scaled by 100**.
`destination_code` `2` is branch cash and `7` is the mobile app. Among cash rows
the `begin_sum_i == 0` row is the standard rate (rows with `begin_sum_i > 0` are
a "up to 10,000" tier and are ignored when the standard row is present).
`created_at` is the stamp. The endpoint is the one the bank's own
`/uz/exchange-rate/` page calls; it is currently failing upstream (see above),
so this parser is retained but the bank's live status is blocked until the
endpoint recovers.

### Xalq banki — `GET /api/v1/external/client/exchange-rate/last-thirty-day`
JSON keyed by ISO 4217 **numeric** code; each holds a `data` map of
`DD-MM-YYYY` → `{buying, selling}`. The most recent date is used and its stamp
becomes `published_at`.

### Kapitalbank — BLOCKED
`kapitalbank.uz` answers HTTP 403 with a Cloudflare anti-bot challenge
("Just a moment…"). `kapital24.uz` redirects (301) to `kapitalbank.uz`, and no
public rate API host resolves. Bypassing the challenge would violate the source
policy, so the bank is recorded as blocked with this reason.

## Channel model

* `cash` — branch / over-the-counter rate.
* `mobile` — mobile-app rate, or the ATM rate where a bank publishes an ATM rate
  and no app rate. ATM values are never labelled as cash.

`buy` is the UZS the bank pays when buying foreign currency from the customer;
`sell` is the UZS the bank charges when selling foreign currency to the
customer. A missing side is `null`.

## Timestamps

Every `published_at` is normalised to ISO 8601 in Asia/Tashkent (`+05:00`).
Supported inputs: ISO 8601 with or without offset, `DD.MM.YYYY[ HH:MM[:SS]]`,
`DD-MM-YYYY`, `DD <month> YYYY` (Uzbek month names) and Unix epochs. A stamp
more than 3 days from collection time is treated as a parsing error and dropped
rather than published, so an old rate can never masquerade as fresh.
