"""Collect verified commercial-bank exchange rates for the 14 supported banks.

Design rules enforced here:

* Only genuinely published rates are stored. Missing cells stay ``null`` and a
  bank that publishes nothing is marked ``unavailable`` with a reason.
* CBU reference rates are never substituted for commercial bank rates.
* An update is atomic: the dataset is written to a temporary file and renamed
  into place only after it validates.
* If a refresh fails, or would publish an empty/incomplete dataset, the last
  verified ``data/banks.json`` is preserved untouched.
* Source publication time and collection time are recorded separately, and
  staleness is explicit so consumers can refuse to calculate on old data.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .banks import BANKS, SUPPORTED_CURRENCIES, Bank
from .bank_parsers import LayoutError, parse_source

SCHEMA_VERSION = 2
OUTPUT = Path("data/banks.json")
USER_AGENT = "IshVaqtiCurrencyMonitor/1.0 (+https://github.com/royaltaxi963-gif/ish-vaqti-currency-rates)"
TIMEOUT = 25
RETRIES = 3
MAX_AGE_HOURS = 24


class CollectionError(RuntimeError):
    """A source could not be retrieved or parsed."""


def _fetch(url: str, attempts: int = RETRIES) -> str:
    """Fetch a URL with bounded exponential backoff."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "uz,en;q=0.8",
            })
            with urlopen(request, timeout=TIMEOUT) as response:
                if response.status != 200:
                    raise CollectionError(f"HTTP {response.status}")
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, "replace")
        except (HTTPError, URLError, TimeoutError, OSError, CollectionError) as error:
            last = error
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise CollectionError(f"{url}: {last}")


def collect_bank(bank: Bank, checked_at: datetime) -> dict:
    """Collect every source of a single bank and merge the results."""
    if not bank.sources:
        return {
            "name": bank.name,
            "status": "unavailable",
            "reason": bank.unavailable_reason or "no verified source",
            "sources": [],
            "currencies": {},
        }

    merged: dict = {}
    sources: list[dict] = []
    errors: list[str] = []
    cache: dict[str, str] = {}

    for source in bank.sources:
        sections = source.sections or ("",)
        for section in sections:
            entry = {"kind": source.kind, "url": source.url, "rate_type": source.kind_label}
            try:
                # An identical URL is fetched only once per collection cycle,
                # even when several sections or rate kinds share it.
                if source.url not in cache:
                    cache[source.url] = _fetch(source.url)
                parsed = parse_source(source.kind, cache[source.url], section, checked_at)
            except (CollectionError, LayoutError, ValueError) as error:
                entry["status"] = "error"
                entry["error"] = str(error)
                errors.append(f"{source.url}#{section or '-'}: {error}")
            else:
                entry["status"] = "ok"
                for code, kinds in parsed.items():
                    for rate_kind, payload in kinds.items():
                        merged.setdefault(code, {})[rate_kind] = payload
            sources.append(entry)

    if not merged:
        return {
            "name": bank.name,
            "status": "unavailable",
            "reason": "; ".join(errors) or "no rates published",
            "sources": sources,
            "currencies": {},
        }

    currencies = {}
    for code in SUPPORTED_CURRENCIES:
        kinds = merged.get(code)
        if not kinds:
            continue
        currencies[code] = {
            kind: kinds[kind] for kind in ("cash", "mobile") if kind in kinds
        }

    partial = any(source.get("status") == "error" for source in sources)
    return {
        "name": bank.name,
        "status": "partial" if partial else "verified",
        "reason": "; ".join(errors) if partial else None,
        "sources": sources,
        "currencies": currencies,
    }


def _same_sources(bank: Bank, old: dict) -> bool:
    """True when the previous dataset used the same official sources.

    Carrying rates forward across a source change would publish values that a
    different upstream produced, so a changed (or unrecorded) source set disables
    carry-forward for that bank.
    """
    recorded = old.get("sources")
    if not isinstance(recorded, list):
        return False
    previous = {(s.get("kind"), s.get("url")) for s in recorded if isinstance(s, dict)}
    current = {(s.kind, s.url) for s in bank.sources}
    return bool(current) and previous == current


def _merge_with_previous(bank: Bank, entry: dict, previous: dict | None) -> dict:
    """Carry forward verified rates when a refresh is missing or partial.

    A bank that fails to refresh keeps its last verified rates instead of being
    overwritten with an empty set, so consumers never lose data on a bad run.
    A bank with no configured source is deliberately unavailable (for example a
    blocked official site), so it must never inherit rates collected earlier
    from a different, since-removed source.
    """
    if previous is None or not bank.sources:
        return entry
    old = next((b for b in previous.get("banks", []) if b.get("slug") == bank.slug), None)
    if not old or not old.get("currencies") or not _same_sources(bank, old):
        return entry

    merged = dict(entry["currencies"])
    carried = False
    for code, kinds in old["currencies"].items():
        for kind, payload in kinds.items():
            if code not in merged or kind not in merged.get(code, {}):
                merged.setdefault(code, {})[kind] = payload
                carried = True

    if not entry["currencies"]:
        entry["status"] = "stale"
        entry["reason"] = entry.get("reason") or "refresh failed; serving last verified rates"
    elif carried:
        entry["status"] = "partial"
        entry["reason"] = entry.get("reason") or "some rates carried forward from the last verified dataset"
    entry["currencies"] = merged
    entry["carried_forward"] = carried
    return entry


def _stale_after(generated_at: datetime) -> str:
    return (generated_at + timedelta(hours=MAX_AGE_HOURS)).isoformat(timespec="seconds")


def _bank_stale(currencies: dict, generated_at: datetime) -> bool:
    """True when every published stamp for the bank is older than the limit.

    Sources that publish no timestamp cannot be judged, so they are not marked
    stale; clients should fall back to the dataset-level ``stale_after``.
    """
    stamps = [
        payload.get("published_at")
        for kinds in currencies.values()
        for payload in kinds.values()
        if payload.get("published_at")
    ]
    if not stamps:
        return False
    newest = max(stamps)
    try:
        moment = datetime.fromisoformat(newest)
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (generated_at - moment) > timedelta(hours=MAX_AGE_HOURS)


def build_dataset(now: datetime, previous: dict | None = None, fetch_workers: int = 6) -> dict:
    """Collect all 14 banks concurrently and assemble the versioned dataset."""
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=fetch_workers) as pool:
        futures = {pool.submit(collect_bank, bank, now): bank for bank in BANKS}
        for future in as_completed(futures):
            bank = futures[future]
            try:
                results[bank.slug] = future.result()
            except Exception as error:  # defensive: never lose the whole run
                results[bank.slug] = {
                    "name": bank.name,
                    "status": "unavailable",
                    "reason": f"collector error: {error}",
                    "sources": [],
                    "currencies": {},
                }

    banks = []
    verified = 0
    for bank in BANKS:
        entry = _merge_with_previous(bank, results[bank.slug], previous)
        if entry["currencies"]:
            verified += 1
        entry["stale"] = _bank_stale(entry["currencies"], now)
        entry.setdefault("carried_forward", False)
        banks.append({"slug": bank.slug, **entry})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "max_age_hours": MAX_AGE_HOURS,
        "stale_after": _stale_after(now),
        "supported_currencies": list(SUPPORTED_CURRENCIES),
        "rate_types": ["cash", "mobile"],
        "notes": (
            "Commercial bank buying/selling rates only. CBU reference rates are "
            "never substituted here; see data/cbu.json for official reference rates. "
            "Refuse to calculate with rates older than max_age_hours (see stale_after)."
        ),
        "summary": {"banks_total": len(BANKS), "banks_with_rates": verified},
        "banks": banks,
    }


def validate_dataset(data: dict) -> None:
    """Reject a dataset that would be unsafe to publish."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected schema_version")
    banks = data.get("banks")
    if not isinstance(banks, list) or len(banks) != len(BANKS):
        raise ValueError("expected exactly 14 banks")
    slugs = [bank.get("slug") for bank in banks]
    if slugs != [bank.slug for bank in BANKS]:
        raise ValueError("bank order or identity changed")
    with_rates = [bank for bank in banks if bank.get("currencies")]
    if not with_rates:
        raise ValueError("refusing to publish a dataset with no rates")
    for bank in with_rates:
        for code, kinds in bank["currencies"].items():
            if code not in SUPPORTED_CURRENCIES:
                raise ValueError(f"{bank['slug']}: unsupported currency {code}")
            if not kinds:
                raise ValueError(f"{bank['slug']}: empty currency entry {code}")
            for kind, payload in kinds.items():
                if kind not in ("cash", "mobile"):
                    raise ValueError(f"{bank['slug']}: bad rate type {kind}")
                if payload.get("buy") is None and payload.get("sell") is None:
                    raise ValueError(f"{bank['slug']}: {code}/{kind} has no rate")


def write_atomic(path: Path, data: dict) -> None:
    """Write JSON via a temporary file so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".banks-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_previous(path: Path = OUTPUT) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _has_fresh_rates(dataset: dict) -> bool:
    """True when at least one bank produced a genuinely fresh rate this run."""
    return any(
        bank.get("currencies") and not bank.get("carried_forward")
        for bank in dataset.get("banks", [])
    )


def run(output: Path = OUTPUT, now: datetime | None = None) -> dict:
    """Collect, validate and atomically publish the dataset.

    On any failure the previously published file is left in place. When every
    source fails, the previous file is preserved byte-for-byte rather than being
    rewritten with carried-forward data.
    """
    moment = now or datetime.now(timezone.utc)
    previous = load_previous(output)
    try:
        dataset = build_dataset(moment, previous=previous)
        validate_dataset(dataset)
    except Exception as error:
        if previous is not None:
            print(f"update failed ({error}); keeping previous verified dataset")
            return previous
        raise

    if previous is not None and not _has_fresh_rates(dataset):
        print("no fresh rates this run; keeping the previous verified dataset")
        return previous

    if previous is not None and previous.get("banks") == dataset["banks"]:
        print("rates unchanged; keeping the existing verified dataset")
        return previous
    write_atomic(output, dataset)
    print(
        f"verified rates for {dataset['summary']['banks_with_rates']}/"
        f"{dataset['summary']['banks_total']} banks"
    )
    return dataset


def main() -> int:
    try:
        run()
    except Exception as error:
        print(f"fatal: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
