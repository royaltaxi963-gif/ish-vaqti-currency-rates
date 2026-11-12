"""Parsers for the verified upstream sources.

Every parser returns the same shape so the collector can treat all banks
uniformly:

    {"code": {"cash": {"buy": float, "sell": float, "published_at": str|None},
              "mobile": {...}}}

A currency/kind pair is only emitted when the source genuinely publishes a
numeric rate. Zero or empty cells mean "not offered" and are dropped instead of
being reported as a 0 rate. Unknown layouts raise ``LayoutError`` so the caller
can fall back to the previously verified dataset rather than publish garbage.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .banks import SUPPORTED_CURRENCIES

TASHKENT = timezone(timedelta(hours=5))

UZ_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
    "iyul": 7, "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10,
    "noyabr": 11, "dekabr": 12,
}

# Plausible band for 1 unit of a foreign currency in UZS. Anything outside is a
# unit or parsing error, not a real quote. Bands are deliberately wide enough to
# allow real market spreads (banks buy RUB well below its reference rate) while
# still catching a value that was scaled by the wrong factor.
PLAUSIBLE = {
    "USD": (5000.0, 25000.0),
    "EUR": (5000.0, 30000.0),
    "RUB": (40.0, 500.0),
    "KZT": (5.0, 200.0),
    "GBP": (5000.0, 30000.0),
}


class LayoutError(ValueError):
    """Raised when a page/response no longer matches the expected structure."""


def _to_float(raw: str) -> Optional[float]:
    """Normalise a localised number such as ``11 950`` or ``12 020,00``."""
    if raw is None:
        return None
    cleaned = str(raw).replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned or ""):
        return None
    return float(cleaned)


def _valid(code: str, value: Optional[float]) -> bool:
    low, high = PLAUSIBLE.get(code, (0.0, float("inf")))
    return value is not None and low <= value <= high


def _merge(target: dict, code: str, kind: str, buy, sell, published_at) -> None:
    if code not in SUPPORTED_CURRENCIES:
        return
    buy = buy if _valid(code, buy) else None
    sell = sell if _valid(code, sell) else None
    if buy is None and sell is None:
        return
    target.setdefault(code, {})[kind] = {
        "buy": buy,
        "sell": sell,
        "published_at": published_at,
    }


# --------------------------------------------------------------------------- #
# bank.uz
# --------------------------------------------------------------------------- #

_BANKUZ_ROW = re.compile(
    r'flag-[a-z]{2}"></span>\s*([A-Z]{3}).*?'
    r'Sotib olish</span>\s*<span class="medium-text">\s*([\d\s]+?)\s*</span>.*?'
    r'Sotish</span>\s*<span class="medium-text">\s*([\d\s]+?)\s*</span>.*?'
    r'<span class="green-date">\s*([^<]+?)\s*</span>',
    re.S,
)


def parse_bankuz(page: str, checked_at: datetime) -> dict:
    """Parse one ``bank.uz/uz/currency/bank/<slug>`` page.

    bank.uz publishes a single cash/card rate per currency and exposes no
    cash-versus-mobile split, so rows are recorded as ``cash``.
    """
    marker = page.find('class="table-kurs"')
    if marker < 0:
        raise LayoutError("bank.uz: rate table not found")
    segment = page[marker:marker + 40000]
    rates: dict = {}
    for code, buy, sell, stamp in _BANKUZ_ROW.findall(segment):
        published = _parse_bankuz_time(stamp, checked_at)
        _merge(rates, code, "cash", _to_float(buy), _to_float(sell), published)
    if not rates:
        raise LayoutError("bank.uz: no rows parsed")
    return rates


def _parse_bankuz_time(stamp: str, checked_at: datetime) -> Optional[str]:
    """bank.uz stamps are ``DD.MM.YYYY HH:MM`` in Asia/Tashkent."""
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", stamp)
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        moment = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), tzinfo=TASHKENT,
        )
    except ValueError:
        return None
    # Reject stamps that are implausibly far from the collection time.
    if abs((checked_at - moment).total_seconds()) > 3 * 24 * 3600:
        return None
    return moment.isoformat()


# --------------------------------------------------------------------------- #
# SQB (https://sqb.uz/api/site-kurs-api/)
# --------------------------------------------------------------------------- #


def parse_sqb(payload: dict) -> dict:
    """Parse SQB's public kurs API.

    ``offline`` rows are branch cash rates and are integers scaled by 100
    (1193000 -> 11930.00). ``online``/``atm`` rows are already expressed in UZS.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LayoutError("SQB: unexpected payload")
    rates: dict = {}
    groups = (("offline", "cash", 100), ("atm", "mobile", 1), ("online", "mobile", 1))
    for key, kind, scale in groups:
        rows = data.get(key) or []
        if not isinstance(rows, list):
            raise LayoutError(f"SQB: {key} is not a list")
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            if not isinstance(code, str) or code.upper() not in SUPPORTED_CURRENCIES:
                continue
            buy = _scaled_value(row.get("buy"), scale)
            sell = _scaled_value(row.get("sell"), scale)
            _merge(rates, code.upper(), kind, buy, sell, None)
    if not rates:
        raise LayoutError("SQB: no rates parsed")
    return rates


def _scaled_value(raw, scale: int) -> Optional[float]:
    if raw in (None, "", 0, "0"):
        return None
    try:
        return int(raw) / scale
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# BRB (https://brb.uz/api/currency/compare?type=jismoniy)
# --------------------------------------------------------------------------- #


def parse_brb(payload: dict) -> dict:
    """Parse BRB's public currency API.

    Values are integers scaled by 100. The ``MOBIL USD`` row is the mobile-app
    rate; every other row is the branch cash rate.
    """
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise LayoutError("BRB: unexpected payload")
    published = _normalise_timestamp(payload.get("updated_at"))
    rates: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_code = str(row.get("code", "")).upper()
        kind = "cash"
        if raw_code.startswith("MOBIL "):
            raw_code, kind = raw_code[len("MOBIL "):], "mobile"
        if raw_code not in SUPPORTED_CURRENCIES:
            continue
        buy = _brb_value(row.get("buy"))
        sell = _brb_value(row.get("sell"))
        _merge(rates, raw_code, kind, buy, sell, published)
    if not rates:
        raise LayoutError("BRB: no rates parsed")
    return rates


def _normalise_timestamp(raw) -> Optional[str]:
    """Turn a ``YYYY-MM-DD HH:MM:SS`` source stamp into an ISO string."""
    if not isinstance(raw, str):
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?", raw)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        moment = datetime(int(year), int(month), int(day), int(hour), int(minute),
                          int(second or 0), tzinfo=TASHKENT)
    except ValueError:
        return None
    return moment.isoformat()


def _brb_value(raw) -> Optional[float]:
    try:
        return int(raw) / 100
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Davr Bank (https://davrbank.uz/uz/exchange-rate)
# --------------------------------------------------------------------------- #

_DAVR_CURRENCY = {
    "AQSH dollari": "USD",
    "Yevro": "EUR",
    "Rossiya rubli": "RUB",
    "Qozog\u2018iston tengesi": "KZT",
    "Qozog'iston tengesi": "KZT",
    "Funt sterling": "GBP",
    "Angliya funt sterlingi": "GBP",
}

_DAVR_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)


def parse_davr(page: str, sections: Iterable[str], checked_at: datetime) -> dict:
    """Parse Davr Bank's server-rendered rate tables.

    Each requested section is a separate table with the columns
    ``Valyuta | MB | Sotuv (sell) | Xarid (buy)``. Rows whose section is not
    published (for example the mobile table when it is missing) are skipped.
    """
    rates: dict = {}
    for section in sections:
        body = _davr_section(page, section)
        if body is None:
            continue
        published = _davr_published(page, checked_at)
        for row in _DAVR_ROW.findall(body):
            cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            cells = [re.sub(r"\s+", " ", c) for c in cells]
            if len(cells) < 4:
                continue
            code = _DAVR_CURRENCY.get(cells[0])
            if code is None:
                continue
            sell = _to_float(cells[2])
            buy = _to_float(cells[3])
            kind = "mobile" if "Mobil" in section else "cash"
            _merge(rates, code, kind, buy, sell, published)
    if not rates:
        raise LayoutError("Davr: no rates parsed")
    return rates


def _davr_section(page: str, section: str) -> Optional[str]:
    """Return the HTML of one table, keyed by its heading text."""
    index = page.find(section)
    if index < 0:
        return None
    start = page.find("<table", index)
    if start < 0:
        return None
    end = page.find("</table>", start)
    if end < 0:
        return None
    return page[start:end]


def _davr_published(page: str, checked_at: datetime) -> Optional[str]:
    """The heading timestamp sits above the first table on the page."""
    match = re.search(r"Yangilandi:\s*(\d{1,2})-([a-z]+),\s*(\d{4})", page)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = UZ_MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        moment = datetime(int(year), month, int(day), tzinfo=TASHKENT)
    except ValueError:
        return None
    if abs((checked_at - moment).total_seconds()) > 3 * 24 * 3600:
        return None
    return moment.isoformat()


def parse_mkbank_json(payload: object) -> dict:
    """Parse MKBank's published open-data G1..G5 fields.

    G2=BANK is branch cash, APP is mobile; G3=currency,
    G4=buy, G5=sell. Missing or zero values are not invented.
    """
    rows = payload
    if isinstance(rows, dict):
        for key in ("data", "results", "items"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
    if not isinstance(rows, list):
        raise LayoutError("MKBank: expected open-data rows")
    rates = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields = {str(k).upper(): v for k, v in row.items()}
        code = str(fields.get("G3") or "").upper().strip()
        group = str(fields.get("G2") or "").upper().strip()
        if code not in SUPPORTED_CURRENCIES or group not in ("BANK", "APP"):
            continue
        kind = "cash" if group == "BANK" else "mobile"
        raw_stamp = str(fields.get("G1") or "")
        published = _normalise_timestamp(raw_stamp)
        _merge(rates, code, kind, _to_float(fields.get("G4")),
               _to_float(fields.get("G5")), published)
    if not rates:
        raise LayoutError("MKBank: no supported rates in open data")
    return rates


def parse_source(kind: str, text: str, section: str, checked_at: datetime) -> dict:
    """Dispatch to the right parser for a source ``kind``."""
    if kind == "bankuz":
        return parse_bankuz(text, checked_at)
    if kind == "davr-html":
        return parse_davr(text, (section,), checked_at)
    payload = json.loads(text)
    if kind == "sqb-api":
        return parse_sqb(payload)
    if kind == "brb-api":
        return parse_brb(payload)
    if kind == "mkbank-json":
        return parse_mkbank_json(payload)
    raise LayoutError(f"unknown source kind: {kind}")
