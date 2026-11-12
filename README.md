# Ish Vaqti — currency rates

Serverless scheduled collector for **official Central Bank of Uzbekistan reference rates** (USD, EUR, RUB, KZT, GBP).

Runs at 09:00, 12:00, 15:00, 18:00 Asia/Tashkent via GitHub Actions. GitHub may delay or skip scheduled executions.

**Important:** CBU reference rates are NOT commercial banks' cash or mobile buy/sell rates. Commercial bank collection for the 13 identified banks, unknown-bank identification, fallback hosting, GitHub Pages publishing and app integration are **not yet implemented**.

Failed fetching or validation does not overwrite the last valid data. The published date comes from the source; checked_at is the retrieval timestamp.

Run locally:
```bash
python -m unittest discover -s tests -v
python -m scripts.fetch_cbu
```
