"""Fetch and validate official CBU reference rates, without fabricating values."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
CURRENCIES = {"USD", "EUR", "RUB", "KZT", "GBP"}
OUTPUT = Path("data/cbu.json")

def parse_rates(payload, checked_at):
    if not isinstance(payload, list):
        raise ValueError("Expected a list of rates")
    rates = {}
    for item in payload:
        if not isinstance(item, dict) or item.get("Ccy") not in CURRENCIES:
            continue
        code = item["Ccy"]
        rate = float(str(item["Rate"]).replace(" ", "").replace(",", "."))
        nominal = int(item.get("Nominal", 1))
        if not (0 < rate < 1000000 and 0 < nominal <= 10000):
            raise ValueError(f"Invalid rate or nominal: {code}")
        if not item.get("Date"):
            raise ValueError(f"Missing date: {code}")
        rates[code] = {"rate_uzs": round(rate / nominal, 6),
                       "nominal": nominal, "published_at": str(item["Date"])}
    if set(rates) != CURRENCIES:
        raise ValueError(f"Missing currencies: {sorted(CURRENCIES - set(rates))}")
    return {"schema_version": 1, "source": "Central Bank of Uzbekistan",
            "source_url": URL, "checked_at": checked_at, "rates": rates}

def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".cbu-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def main():
    request = Request(URL, headers={"User-Agent": "IshVaqtiCurrencyMonitor/1.0",
                                    "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"CBU HTTP {response.status}")
        payload = json.load(response)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data = parse_rates(payload, checked_at)
    write_atomic(OUTPUT, data)
    print(f"Verified {len(data['rates'])} official reference rates")

if __name__ == "__main__":
    main()
