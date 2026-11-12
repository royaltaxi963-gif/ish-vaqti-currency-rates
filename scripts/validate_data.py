"""Validate the published datasets without external dependencies.

The schema in ``schemas/banks.schema.json`` is the contract; this module checks
the invariants that matter for consumers (identity, ordering, currency codes,
rate types, non-empty rates) and prints a short summary. It exits non-zero when
a dataset would be unsafe to publish.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .banks import BANKS, SUPPORTED_CURRENCIES

BANKS_FILE = Path("data/banks.json")
CBU_FILE = Path("data/cbu.json")
SCHEMA_FILE = Path("schemas/banks.schema.json")


def _fail(message: str) -> None:
    print(f"INVALID: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_banks(path: Path = BANKS_FILE) -> dict:
    if not path.exists():
        _fail(f"{path} is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        _fail(f"{path} is not valid JSON: {error}")

    if data.get("schema_version") != 2:
        _fail("schema_version must be 2")
    if data.get("max_age_hours") != 24:
        _fail("max_age_hours must be 24")
    if not data.get("stale_after") or not data.get("generated_at"):
        _fail("generated_at and stale_after are required")

    banks = data.get("banks")
    if not isinstance(banks, list) or len(banks) != len(BANKS):
        _fail(f"expected exactly {len(BANKS)} banks")
    if [b.get("slug") for b in banks] != [b.slug for b in BANKS]:
        _fail("bank identity or ordering changed")

    for bank in banks:
        slug = bank.get("slug")
        if bank.get("status") not in ("verified", "partial", "stale", "unavailable"):
            _fail(f"{slug}: unknown status {bank.get('status')!r}")
        if not bank.get("sources"):
            # A blocked bank has no official source; it must say why.
            if bank.get("status") != "unavailable" or not bank.get("reason"):
                _fail(f"{slug}: no sources recorded and no reason given")
        for source in bank["sources"]:
            if not source.get("url", "").startswith("https://"):
                _fail(f"{slug}: source url must be https")
        for code, kinds in bank.get("currencies", {}).items():
            if code not in SUPPORTED_CURRENCIES:
                _fail(f"{slug}: unsupported currency {code}")
            if not kinds:
                _fail(f"{slug}: empty entry for {code}")
            for kind, payload in kinds.items():
                if kind not in ("cash", "mobile"):
                    _fail(f"{slug}: unknown rate type {kind}")
                buy, sell = payload.get("buy"), payload.get("sell")
                if buy is None and sell is None:
                    _fail(f"{slug}: {code}/{kind} has neither buy nor sell")
                for label, value in (("buy", buy), ("sell", sell)):
                    if value is not None and value <= 0:
                        _fail(f"{slug}: {code}/{kind} {label} must be positive")

    if not any(bank.get("currencies") for bank in banks):
        _fail("dataset contains no rates")
    return data


def validate_schema_file(path: Path = SCHEMA_FILE) -> dict:
    if not path.exists():
        _fail(f"{path} is missing")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        _fail(f"{path} is not valid JSON: {error}")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != 2:
        _fail("schema does not describe version 2")
    return schema


def validate_cbu(path: Path = CBU_FILE) -> dict:
    if not path.exists():
        _fail(f"{path} is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        _fail(f"{path} is not valid JSON: {error}")
    if data.get("schema_version") != 1:
        _fail("cbu.json schema_version must be 1")
    if set(data.get("rates", {})) != set(SUPPORTED_CURRENCIES):
        _fail("cbu.json must contain all supported currencies")
    return data


def main() -> int:
    validate_schema_file()
    banks = validate_banks()
    validate_cbu()
    verified = banks["summary"]["banks_with_rates"]
    print(f"OK: {verified}/{len(BANKS)} banks with rates, "
          f"stale_after={banks['stale_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
