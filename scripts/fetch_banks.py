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

from .banks import BANKS, SUPPORTED_CURRENCIES, Bank, Source
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


def _source_entries(source: Source, checked_at: datetime,
                    cache: dict[str, str]) -> tuple[dict, list[dict]]:
    """Fetch, identity-check and parse one source (all of its sections).

    Returns the parsed ``{code: {kind: payload}}`` map and the per-section
    provenance entries. A section that fails is recorded with an ``error``
    status; an identity mismatch fails the whole source because a page that does
    not name the bank must never contribute rates.
    """
    entries: list[dict] = []
    text = cache.get(source.url)
    if text is None:
        text = _fetch(source.url)
        cache[source.url] = text

    if source.expect:
        haystack = text.casefold()
        missing = [token for token in source.expect if token.casefold() not in haystack]
        if missing:
            for section in source.sections or ("",):
                entries.append({
                    "kind": source.kind,
                    "url": source.url,
                    "rate_type": source.kind_label,
                    "source_type": source.source_type,
                    "status": "error",
                    "error": f"identity check failed: {source.url} does not name {missing}",
                })
            return {}, entries

    parsed: dict = {}
    for section in source.sections or ("",):
        entry = {
            "kind": source.kind,
            "url": source.url,
            "rate_type": source.kind_label,
            "source_type": source.source_type,
        }
        try:
            result = parse_source(source.kind, text, section, checked_at)
        except (LayoutError, ValueError) as error:
            entry["status"] = "error"
            entry["error"] = f"{source.url}#{section or '-'}: {error}"
        else:
            entry["status"] = "ok"
            for code, kinds in result.items():
                for rate_kind, payload in kinds.items():
                    parsed.setdefault(code, {})[rate_kind] = payload
        entries.append(entry)
    return parsed, entries


def collect_bank(bank: Bank, checked_at: datetime) -> dict:
    """Collect a bank, preferring its official source and falling back if needed.

    The official source is always attempted first. A fallback (an approved
    third-party aggregator) is consulted only when the official source yields no
    usable rates, and its provenance is recorded distinctly. Official and
    fallback values are never merged into one dataset entry: a single rate pair
    always comes from a single source.
    """
    cache: dict[str, str] = {}

    official_rates: dict = {}
    official_sources: list[dict] = []
    errors: list[str] = []

    for source in bank.sources:
        try:
            parsed, entries = _source_entries(source, checked_at, cache)
        except (CollectionError, OSError) as error:
            entries = [{
                "kind": source.kind,
                "url": source.url,
                "rate_type": source.kind_label,
                "source_type": source.source_type,
                "status": "error",
                "error": str(error),
            }]
            parsed = {}
        official_sources.extend(entries)
        for entry in entries:
            if entry["status"] == "error":
                errors.append(entry.get("error", "source error"))
        for code, kinds in parsed.items():
            for rate_kind, payload in kinds.items():
                official_rates.setdefault(code, {})[rate_kind] = payload

    if official_rates:
        return _finalise_entry(bank, official_rates, official_sources, errors, "official")

    # No official data. Try the verified fallback, if the bank has one.
    fallback_sources: list[dict] = []
    fallback_rates: dict = {}
    fallback_errors: list[str] = []
    if bank.fallback is not None:
        try:
            parsed, entries = _source_entries(bank.fallback, checked_at, cache)
        except (CollectionError, OSError) as error:
            entries = [{
                "kind": bank.fallback.kind,
                "url": bank.fallback.url,
                "rate_type": bank.fallback.kind_label,
                "source_type": bank.fallback.source_type,
                "status": "error",
                "error": str(error),
            }]
            parsed = {}
        fallback_sources.extend(entries)
        for entry in entries:
            if entry["status"] == "error":
                fallback_errors.append(entry.get("error", "fallback error"))
        fallback_rates = parsed

    if fallback_rates:
        if errors:
            detail = "; ".join(errors)
        elif bank.unavailable_reason:
            detail = bank.unavailable_reason
        else:
            detail = "no rates"
        reason = f"official source unavailable: {detail}"
        return _finalise_entry(
            bank, fallback_rates, fallback_sources, fallback_errors, "fallback",
            official_note=reason,
        )

    return {
        "name": bank.name,
        "status": "unavailable",
        "reason": _unavailable_reason(bank, errors, fallback_errors),
        "sources": official_sources + fallback_sources,
        "currencies": {},
        "selected_source": None,
    }


def _unavailable_reason(bank: Bank, official_errors: list[str], fallback_errors: list[str]) -> str:
    reason = bank.unavailable_reason or "; ".join(official_errors) or "no rates published"
    if fallback_errors:
        reason = f"{reason}; fallback also failed: {'; '.join(fallback_errors)}"
    return reason


def _finalise_entry(bank: Bank, merged: dict, sources: list[dict], errors: list[str],
                    selected: str, official_note: str | None = None) -> dict:
    currencies = {}
    for code in SUPPORTED_CURRENCIES:
        kinds = merged.get(code)
        if not kinds:
            continue
        currencies[code] = {
            kind: kinds[kind] for kind in ("cash", "mobile") if kind in kinds
        }

    partial = any(source.get("status") == "error" for source in sources)

    reason = None
    if selected == "fallback":
        note = official_note or "official source unavailable"
        if bank.fallback is not None and bank.fallback.kind == "bankuz-html":
            from .banks import BANKUZ_ATTRIBUTION
            reason = f"{note}. {BANKUZ_ATTRIBUTION}"
        else:
            reason = note
    elif partial:
        reason = "; ".join(errors)

    return {
        "name": bank.name,
        "status": "partial" if partial else "verified",
        "reason": reason,
        "sources": sources,
        "currencies": currencies,
        "selected_source": selected,
    }


def _source_keys(bank: Bank) -> set[tuple[str, str]]:
    """The set of (kind, url) this bank could legitimately collect from.

    Includes the fallback so that rates carried forward from a fallback are only
    reused while that fallback is still an approved source for the bank.
    """
    keys = {(source.kind, source.url) for source in bank.sources}
    if bank.fallback is not None:
        keys.add((bank.fallback.kind, bank.fallback.url))
    return keys


def _same_sources(bank: Bank, old: dict) -> bool:
    """True when the previous dataset used the same (or a subset of) sources.

    Carrying rates forward across a source change would publish values that a
    different upstream produced, so a previous source set that is not a subset of
    the bank's current approved sources disables carry-forward for that bank.
    """
    recorded = old.get("sources")
    if not isinstance(recorded, list) or not recorded:
        return False
    previous = {(s.get("kind"), s.get("url")) for s in recorded if isinstance(s, dict)}
    if not previous:
        return False
    return previous <= _source_keys(bank)


def _merge_with_previous(bank: Bank, entry: dict, previous: dict | None) -> dict:
    """Carry forward verified rates when a refresh is missing or partial.

    A bank that fails to refresh keeps its last verified rates instead of being
    overwritten with an empty set, so consumers never lose data on a bad run.
    Rates are only reused while the previous source is still an approved source
    for the bank (official or its verified fallback), so a value produced by a
    since-removed source is never republished.
    """
    if previous is None:
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
        # The served rates came from whatever source produced the previous
        # dataset; keep that provenance instead of reporting no source.
        entry["selected_source"] = old.get("selected_source")
    elif carried:
        entry["status"] = "partial"
        entry["reason"] = entry.get("reason") or "some rates carried forward from the last verified dataset"
    entry["currencies"] = merged
    entry["carried_forward"] = carried
    entry.setdefault("selected_source", None)
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
        entry.setdefault("selected_source", None)
        # Emit a stable key order so a refresh only changes values, not layout.
        entry = {
            "name": entry["name"],
            "status": entry["status"],
            "reason": entry.get("reason"),
            "selected_source": entry["selected_source"],
            "sources": entry["sources"],
            "currencies": entry["currencies"],
            "carried_forward": bool(entry["carried_forward"]),
            "stale": entry["stale"],
        }
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
    for bank in banks:
        if bank.get("selected_source") not in (None, "official", "fallback"):
            raise ValueError(f"{bank['slug']}: bad selected_source {bank['selected_source']}")
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
