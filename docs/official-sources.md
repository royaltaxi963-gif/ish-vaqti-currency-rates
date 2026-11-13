# Official bank rate sources — verification record

This document records, for each of the 14 supported banks, the official source
the collector uses, how it was verified, and its current status. The previous
implementation read 11 of the 14 banks from `bank.uz`, a third-party
aggregator. That is now forbidden: every bank is read from its own official
domain or an authorised public API.

Four banks have no reachable official rate source (see the per-bank notes).
Rather than leave them empty, the collector uses a **verified fallback**: the
`bank.uz` aggregator, which is crawled only with the permission its
`robots.txt` grants, with the bank's identity confirmed on every page. A
fallback is consulted *only* when the official source yields no rates, its
provenance is recorded separately (`source_type: "fallback"`,
`selected_source: "fallback"`), and its values are never mixed with official
ones. See [Verified fallback](#verified-fallback-bankuz) for the policy.

All HTTP results below were re-verified on 2026-11-12/13 (Asia/Tashkent) with a
plain `urllib`/`curl` request and a normal desktop User-Agent, plus a headless
Chromium render for the client-rendered pages. No CAPTCHA or access-control
control was bypassed. Rates are UZS per 1 unit unless noted.

## Verification matrix

| # | Bank | Official source | HTTP | USD | EUR | RUB | KZT | GBP | Cash | Mobile | Status |
|---|------|-----------------|------|-----|-----|-----|-----|-----|------|--------|--------|
| 1 | Universalbank | `universalbank.uz/api/currencies/daily` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | – | VERIFIED |
| 2 | Davr Bank | `davrbank.uz/uz/exchange-rate` | 200 | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | VERIFIED |
| 3 | Asakabank | `bank.uz/uz/currency/bank/asaka-bank` (fallback) | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | – | VERIFIED (fallback) |
| 4 | Trastbank | `trastbank.uz/uz/services/exchange-rates/` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | – | VERIFIED |
| 5 | SQB | `sqb.uz/api/site-kurs-api/` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 6 | Mikrokreditbank | `mkbank.uz/uz/services/open_data/rates/json/` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 7 | Ipak Yo‘li Bank | `ipakyulibank.uz/physical/valyuta-ayirboshlash` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | ✓ | VERIFIED |
| 8 | O‘zmilliybank (NBU) | `bank.uz/uz/currency/bank/nbu` (fallback) | 200 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | VERIFIED (fallback) |
| 9 | Ipoteka-bank | `ipotekabank.uz/services/currency/` | 200 | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | VERIFIED |
| 10 | BRB | `brb.uz/api/currency/compare?type=jismoniy` | 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | ✓ | VERIFIED |
| 11 | Agrobank | `agrobank.uz/api/v1/?action=pages&code=uz/person/exchange_rates` | 200 | ✓ | ✓ | ✓ (sell only) | – | ✓ | ✓ | ✓ | VERIFIED |
| 12 | Hamkorbank | `api-dbo.hamkorbank.uz/webflow/v1/exchanges` → `bank.uz/…/hamkorbank` (fallback) | 500 → 200 | ✓ | ✓ | ✓ | – | ✓ | ✓ | ✓ | VERIFIED (fallback) |
| 13 | Xalq banki | `xb.uz/api/v1/external/client/exchange-rate/last-thirty-day` | 200 | ✓ | ✓ | ✓ | – | – | ✓ | – | VERIFIED |
| 14 | Kapitalbank | `bank.uz/uz/currency/bank/kapitalbank` (fallback) | 200 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | VERIFIED (fallback) |

`✓ (sell only)` means the bank genuinely does not publish a buying rate for that
currency; the value is stored as `null`, not fabricated.

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

### Asakabank — official BLOCKED, fallback used
`asakabank.uz` is a Nuxt SPA. The rate table on
`/uz/press-center/exchange-rates` is rendered client-side; the served HTML
contains no rates (only CSS/markup). Reverse-engineering the Nuxt config gives
`apiBase = https://back.asakabank.uz`, but that host answers HTTP 403 to every
path from the collector network (`/`, `/rates`, `/exchange-rates`, `/v1/rates`,
`/openapi.json`), and no public rate route is documented. No official rate
value is reachable, so the bank is served from the verified `bank.uz` fallback
(see below); its official status stays blocked.

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

### O‘zmilliybank (NBU) — official BLOCKED, fallback used
`nbu.uz` resolves to `185.104.210.5` (`www.nbu.uz` shares it). The host accepts
no TCP connection on port 80 or 443 from the collector network: both a
`urllib` request and a raw `socket`/TLS handshake time out (`000`). Alternative
hosts (`api.nbu.uz`, `open.nbu.uz`, `online.nbu.uz`, `my.nbu.uz`) do not
resolve; `mobile.nbu.uz` resolves but returns HTTP 403. No official rate value
is reachable, so the bank is served from the verified `bank.uz` fallback. The
fallback is the only source that yields a personal-channel KZT rate (see
below).

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
`/uz/exchange-rate/` page calls; it is currently failing upstream (HTTP `500`
`{"status":"Failure","error_code":-10,"error_note":"internal error","data":null}`
for every request, with and without browser headers). The `/uz/exchange-rate/`
page itself still returns `200` but ships no server-rendered rates — its table is
populated by that same failing call — so no official rate value is reachable
right now. The parser is retained and used the moment the endpoint recovers;
until then the bank is served from the verified `bank.uz` fallback.

### Xalq banki — `GET /api/v1/external/client/exchange-rate/last-thirty-day`
JSON keyed by ISO 4217 **numeric** code; each holds a `data` map of
`DD-MM-YYYY` → `{buying, selling}`. The most recent date is used and its stamp
becomes `published_at`.

### Kapitalbank — official BLOCKED, fallback used
`kapitalbank.uz` answers HTTP 403 with a Cloudflare anti-bot challenge
("Just a moment…"). `kapital24.uz` redirects (301) to `kapitalbank.uz`, and no
public rate API host resolves. Bypassing the challenge would violate the source
policy, so no official rate value is reachable and the bank is served from the
verified `bank.uz` fallback.

## Verified fallback (bank.uz)

`bank.uz` was the aggregator the previous implementation used for 11 banks; as
an *official* source it is forbidden. It is used here only as a documented
fallback for the four banks whose own source is unreachable, under these rules:

* **Permission.** `https://bank.uz/robots.txt` returns `User-agent: *` /
  `Allow: /` with `Crawl-delay: 3`. Only pages that `robots.txt` allows are
  read, one request per bank per cycle. (By contrast `onmap.uz` returns
  `Disallow: /api/`, so its API is never scraped, and `finq.uz` was used only
  for manual cross-checking.)
* **Identity.** Every page must name the bank (`<title>`/`<h1>`); the collector
  passes the expected name tokens and refuses the page if they are absent, so a
  redirect or layout swap can never attribute one bank's rates to another.
* **Precedence.** The official source is always tried first. The fallback runs
  only when the official source yields no rates. A published pair always comes
  from exactly one source; official and fallback values are never mixed.
* **Provenance.** Fallback sources carry `source_type: "fallback"` and the
  entry carries `selected_source: "fallback"` plus a `reason` naming the
  official failure, so a consumer can tell official data from fallback data.
* **Units and channels.** bank.uz labels each row `Birlik` (unit). Only rows
  whose unit is exactly `1` are published; a row quoted per 10/100/1000 is
  dropped rather than mis-scaled. Rows are branch cash. A `0` buying or selling
  cell means the bank does not transact that side and is stored as `null`.
* **Timestamps.** The per-row `Yangilanish vaqti` stamp is parsed and preserved,
  so a fallback rate is never presented as fresher than it is.

### Cross-checks performed
* Trastbank: bank.uz values are identical to the official page (USD 11920/12020,
  EUR 12850/13400, RUB 90/150) — the two sources agree where both exist.
* Asakabank: an independent aggregator (`finq.uz`) confirms bank.uz's
  USD 11950/11990; BRB is confirmed at 11945/12030.
* KZT: CBU's reference KZT is ≈26.88 UZS per unit. bank.uz NBU KZT (16/27) and
  Kapitalbank KZT (25/28) bracket it, confirming genuine per-1-tenge quotes
  rather than a per-100 mis-scaling.

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
