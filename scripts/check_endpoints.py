"""Probe the public distribution endpoints and report their status.

Free, best-effort check used to confirm the fallback chain is live. It needs
outbound network access and never fails the build on its own.
"""
from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO = "royaltaxi963-gif/ish-vaqti-currency-rates"
ENDPOINTS = {
    "pages": f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/data/banks.json",
    "jsdelivr": f"https://cdn.jsdelivr.net/gh/{REPO}@main/data/banks.json",
    "raw": f"https://raw.githubusercontent.com/{REPO}/main/data/banks.json",
}
TIMEOUT = 20


def probe(name: str, url: str) -> tuple[str, str]:
    try:
        request = Request(url, headers={"User-Agent": "IshVaqtiEndpointCheck/1.0"})
        with urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        banks = payload.get("summary", {}).get("banks_with_rates", "?")
        return name, f"ok (banks_with_rates={banks})"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as error:
        return name, f"unavailable ({error})"


def main() -> int:
    for name, url in ENDPOINTS.items():
        label, status = probe(name, url)
        print(f"{label:10} {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
