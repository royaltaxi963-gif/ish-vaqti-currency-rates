# Public endpoints and fallback hosting

The verified datasets are plain static JSON files committed to `main`. They are
served from several free, independent locations so a consumer can keep working
when one of them is unavailable.

## Primary endpoint (GitHub Pages)

```
https://royaltaxi963-gif.github.io/ish-vaqti-currency-rates/data/banks.json
https://royaltaxi963-gif.github.io/ish-vaqti-currency-rates/data/cbu.json
```

The Pages site is published by `.github/workflows/update-rates.yml` after each
successful data refresh.

## Fallback endpoints (no Cloudflare, free tier only)

| Provider | URL pattern | Notes |
| --- | --- | --- |
| jsDelivr | `https://cdn.jsdelivr.net/gh/royaltaxi963-gif/ish-vaqti-currency-rates@main/data/banks.json` | Independent CDN, caches for ~12h, no account required |
| raw.githubusercontent.com | `https://raw.githubusercontent.com/royaltaxi963-gif/ish-vaqti-currency-rates/main/data/banks.json` | Always current, no CDN cache |

Recommended client order: **Pages → jsDelivr → raw.githubusercontent.com**.

`raw.githubusercontent.com` returns the newest commit immediately, while
jsDelivr may serve a cached copy for up to ~12 hours. A client that needs the
freshest data should prefer Pages or raw; a client that wants low latency and can
tolerate a short cache should prefer jsDelivr.

## Client caching contract

Every dataset carries `generated_at` and `stale_after`. Clients should:

1. Cache the JSON locally and revalidate when `stale_after` passes.
2. Refuse to calculate with rates older than `max_age_hours` (24).
3. Treat `status` values other than `verified` as needing a fallback source.
4. Never treat the CBU reference rates in `data/cbu.json` as commercial bank
   buying or selling rates.

## Checking a fallback is live

```bash
python -m scripts.check_endpoints
```

The command probes the endpoints above and prints their status. It is
best-effort and needs outbound network access.
