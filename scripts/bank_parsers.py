"""Parsers for the verified official bank sources.

Every parser returns the same shape so the collector can treat all banks
uniformly:

    {"code": {"cash": {"buy": float, "sell": float, "published_at": str|None},
              "mobile": {...}}}

A currency/kind pair is only emitted when the source genuinely publishes a
numeric rate. Zero or empty cells mean "not offered" and are dropped instead of
being reported as a 0 rate. Unknown layouts raise ``LayoutError`` so the caller
can fall back to the previously verified dataset rather than publish garbage.

Only official bank domains are parsed here. See ``docs/official-sources.md`` for
the per-bank endpoint, channel and unit evidence.
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

# Plausible band for 1 unit of a foreign currency in UZS. The bands are a
# sanity guard against a value scaled by the wrong factor, not a filter on
# legitimate rates: they are deliberately wide, and RUB in particular is left
# broad because banks publish real cash RUB quotes well away from the CBU
# reference rate. A value outside its band is dropped as a parsing error.
PLAUSIBLE = {
    "USD": (5000.0, 25000.0),
    "EUR": (5000.0, 30000.0),
    "RUB": (20.0, 1000.0),
    "KZT": (5.0, 300.0),
    "GBP": (5000.0, 30000.0),
}

# ISO 4217 numeric -> alpha-3, for sources that key rows by numeric code.
NUMERIC_CODES = {
    "840": "USD", "978": "EUR", "643": "RUB", "398": "KZT", "826": "GBP",
}


class LayoutError(ValueError):
    """Raised when a page/response no longer matches the expected structure."""


def _to_float(raw) -> Optional[float]:
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
# Timestamp handling
# --------------------------------------------------------------------------- #

_ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
)


def _to_tashkent(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=TASHKENT)
    return moment.astimezone(TASHKENT)


def _plausible(moment: datetime, checked_at: Optional[datetime]) -> bool:
    """Reject stamps that are implausibly far from the collection time."""
    if checked_at is None:
        return True
    return abs((checked_at - moment).total_seconds()) <= 3 * 24 * 3600


def _parse_dt(raw, checked_at: Optional[datetime] = None) -> Optional[str]:
    """Parse the timestamp formats the official sources publish.

    Handles ISO 8601 (with or without offset), ``DD.MM.YYYY[ HH:MM[:SS]]``,
    ``DD-MM-YYYY`` and ``DD <month-name> YYYY`` (Uzbek months). Returns an ISO
    string in Asia/Tashkent, or ``None`` when the stamp is unreadable or
    implausible.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    moment: Optional[datetime] = None

    iso = _ISO.search(text)
    if iso:
        year, month, day, hour, minute, second, offset = iso.groups()
        tz = TASHKENT
        if offset:
            offset = "+00:00" if offset == "Z" else offset
            if len(offset) == 5:  # +0500 -> +05:00
                offset = offset[:3] + ":" + offset[3:]
            sign = 1 if offset[0] == "+" else -1
            hh, mm = int(offset[1:3]), int(offset[4:6])
            tz = timezone(sign * timedelta(hours=hh, minutes=mm))
        try:
            moment = datetime(int(year), int(month), int(day), int(hour),
                              int(minute), int(second or 0), tzinfo=tz)
        except ValueError:
            moment = None

    if moment is None:
        match = re.search(
            r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
            text,
        )
        if match:
            day, month, year, hour, minute, second = match.groups()
            try:
                moment = datetime(int(year), int(month), int(day),
                                  int(hour or 0), int(minute or 0),
                                  int(second or 0), tzinfo=TASHKENT)
            except ValueError:
                moment = None

    if moment is None:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            year, month, day = match.groups()
            try:
                moment = datetime(int(year), int(month), int(day), tzinfo=TASHKENT)
            except ValueError:
                moment = None

    if moment is None:
        match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
        if match:
            day, month, year = match.groups()
            try:
                moment = datetime(int(year), int(month), int(day), tzinfo=TASHKENT)
            except ValueError:
                moment = None

    if moment is None:
        match = re.search(r"(\d{1,2})\s+([A-Za-z\u2018\u2019']+),?\s+(\d{4})", text)
        if match:
            day, month_name, year = match.groups()
            month = UZ_MONTHS.get(month_name.lower())
            if month:
                try:
                    moment = datetime(int(year), month, int(day), tzinfo=TASHKENT)
                except ValueError:
                    moment = None

    if moment is None:
        return None
    moment = _to_tashkent(moment)
    if not _plausible(moment, checked_at):
        return None
    return moment.isoformat()


def _normalise_timestamp(raw, checked_at: Optional[datetime] = None) -> Optional[str]:
    """Backwards-compatible wrapper around :func:`_parse_dt`."""
    return _parse_dt(raw, checked_at)


def _epoch_to_iso(raw, checked_at: Optional[datetime] = None) -> Optional[str]:
    """Turn a Unix epoch (seconds) into a Tashkent ISO string."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    try:
        moment = datetime.fromtimestamp(value, tz=TASHKENT)
    except (OverflowError, OSError, ValueError):
        return None
    if not _plausible(moment, checked_at):
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
    groups = (("offline", "cash", 100), ("online", "mobile", 1), ("atm", "mobile", 1))
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
            # ATM only fills mobile when the online app rate is absent.
            if key == "atm" and rates.get(code.upper(), {}).get("mobile"):
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
    return _parse_dt(f"{match.group(1)} {match.group(2)} {match.group(3)}", checked_at)


# --------------------------------------------------------------------------- #
# Mikrokreditbank open data
# (https://mkbank.uz/uz/services/open_data/rates/json/)
# --------------------------------------------------------------------------- #


def parse_mkbank_json(payload: object, checked_at: Optional[datetime] = None) -> dict:
    """Parse MKBank's published open-data G1..G5 fields.

    G1 is the publication stamp (``DD.MM.YYYY HH:MM:SS``), G2 is the channel
    (``BANK`` cash / ``APP`` mobile / ``ATM``), G3 the currency, G4 the buying
    rate and G5 the selling rate. Missing or zero values are not invented.
    """
    rows = payload
    if isinstance(rows, dict):
        for key in ("data", "results", "items"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
    if not isinstance(rows, list):
        raise LayoutError("MKBank: expected open-data rows")
    rates: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields = {str(k).upper(): v for k, v in row.items()}
        code = str(fields.get("G3") or "").upper().strip()
        group = str(fields.get("G2") or "").upper().strip()
        if code not in SUPPORTED_CURRENCIES or group not in ("BANK", "APP", "ATM"):
            continue
        kind = "cash" if group == "BANK" else "mobile"
        published = _parse_dt(fields.get("G1"), checked_at)
        _merge(rates, code, kind, _to_float(fields.get("G4")),
               _to_float(fields.get("G5")), published)
    if not rates:
        raise LayoutError("MKBank: no supported rates in open data")
    return rates


# --------------------------------------------------------------------------- #
# Universalbank (https://universalbank.uz/api/currencies/daily)
# --------------------------------------------------------------------------- #


def parse_universalbank(payload: object, checked_at: Optional[datetime] = None) -> dict:
    """Parse Universalbank's public daily-currency API.

    Rows are keyed by ISO 4217 numeric ``code`` with ``nominal`` units per
    quote. ``hasBuyingRate``/``hasSellingRate`` are false when the bank does not
    buy or sell that currency (the raw value is then ``0.00`` and is dropped).
    The rate is a branch cash rate; ``rateDate`` is the effective date.
    """
    if not isinstance(payload, dict):
        raise LayoutError("Universalbank: unexpected payload")
    items = payload.get("items")
    if not isinstance(items, list):
        raise LayoutError("Universalbank: missing items")
    rates: dict = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = NUMERIC_CODES.get(str(item.get("code") or "").strip())
        if code is None:
            continue
        try:
            nominal = float(item.get("nominal") or 1) or 1.0
        except (TypeError, ValueError):
            nominal = 1.0
        buy = _to_float(item.get("buyingRate")) if item.get("hasBuyingRate") else None
        sell = _to_float(item.get("sellingRate")) if item.get("hasSellingRate") else None
        buy = buy / nominal if buy is not None else None
        sell = sell / nominal if sell is not None else None
        published = _parse_dt(item.get("rateDate") or item.get("confirmedAt"), checked_at)
        _merge(rates, code, "cash", buy, sell, published)
    if not rates:
        raise LayoutError("Universalbank: no rates parsed")
    return rates


# --------------------------------------------------------------------------- #
# Trastbank (https://trastbank.uz/uz/services/exchange-rates/)
# --------------------------------------------------------------------------- #

_TRAST_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def parse_trastbank(page: str, checked_at: datetime) -> dict:
    """Parse Trastbank's server-rendered branch rate table.

    Columns are ``Valyuta | Sotib olish (buy) | Sotish (sell) | MB kursi``; the
    stamp under the table is ``Sotib olish/Sotish - DD.MM.YYYY HH:MM dan``.
    """
    match = re.search(
        r"Sotib olish/Sotish\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?)",
        page,
    )
    published = _parse_dt(match.group(1), checked_at) if match else None
    rates: dict = {}
    for row in _TRAST_ROW.findall(page):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 3:
            continue
        code = cells[0].upper()
        if code not in SUPPORTED_CURRENCIES:
            continue
        buy = _to_float(cells[1])
        sell = _to_float(cells[2])
        _merge(rates, code, "cash", buy, sell, published)
    if not rates:
        raise LayoutError("Trastbank: no rates parsed")
    return rates


# --------------------------------------------------------------------------- #
# Ipak Yo'li Bank
# (https://ipakyulibank.uz/physical/valyuta-ayirboshlash)
# --------------------------------------------------------------------------- #


def parse_ipakyuli(page: str, checked_at: datetime) -> dict:
    """Parse the Nuxt payload embedded in Ipak Yo'li's exchange page.

    The page ships a ``__NUXT_DATA__`` graph with three tabs: ``Ilovada`` (mobile
    app), ``Kassada`` (branch cash) and ``Bankomatda`` (ATM). Rates are integers
    scaled by 100. The app rate fills ``mobile``; the ATM rate fills ``mobile``
    only when the app does not publish that currency, matching the dataset's
    documented ``mobile = app or ATM`` meaning.
    """
    tabs = _ipakyuli_tabs(page)
    if not tabs:
        raise LayoutError("Ipak Yo'li: rate tables not found")
    rates: dict = {}
    order = {"Kassada": "cash", "Ilovada": "mobile", "Bankomatda": "mobile"}
    for label in ("Kassada", "Ilovada", "Bankomatda"):
        tab = tabs.get(label)
        if not tab:
            continue
        kind = order[label]
        published = _epoch_to_iso(tab.get("lastUpdated"), checked_at)
        for entry in tab.get("rates", []) or []:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code_name") or "").upper()
            if code not in SUPPORTED_CURRENCIES:
                continue
            rate = entry.get("rate") or {}
            buy = _scaled_value(rate.get("buy"), 100)
            sell = _scaled_value(rate.get("sell"), 100)
            if label == "Bankomatda":
                existing = rates.get(code, {}).get("mobile")
                if existing and (existing.get("buy") or existing.get("sell")):
                    continue
            _merge(rates, code, kind, buy, sell, published)
    if not rates:
        raise LayoutError("Ipak Yo'li: no rates parsed")
    return rates


def _ipakyuli_tabs(page: str) -> dict:
    marker = page.find("__NUXT_DATA__")
    if marker < 0:
        return {}
    start = page.find(">", marker) + 1
    end = page.find("</script>", start)
    if start <= 0 or end < 0:
        return {}
    try:
        graph = json.loads(page[start:end])
    except json.JSONDecodeError:
        return {}
    if not isinstance(graph, list):
        return {}
    tabs: dict = {}
    for index, node in enumerate(graph):
        if not isinstance(node, dict) or "rates" not in node or "varName" not in node:
            continue
        resolved = _resolve_nuxt(graph, index)
        if isinstance(resolved, dict) and isinstance(resolved.get("name"), str):
            tabs[resolved["name"]] = resolved
    return tabs


def _resolve_nuxt(graph: list, index, depth: int = 0):
    """Resolve Nuxt's index-referenced payload graph into plain Python values."""
    if depth > 12 or not isinstance(index, int) or index < 0 or index >= len(graph):
        return None
    node = graph[index]
    if isinstance(node, dict):
        return {key: _resolve_nuxt(graph, value, depth + 1)
                for key, value in node.items()}
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0] in (
            "Date", "Set", "Map", "RegExp", "BigInt", "undefined", "null",
            "ShallowReactive", "Reactive", "Ref", "EmptyRef",
        ):
            return node
        return [_resolve_nuxt(graph, item, depth + 1) for item in node]
    return node


# --------------------------------------------------------------------------- #
# Ipoteka-bank (https://ipotekabank.uz/services/currency/<pair>/)
# --------------------------------------------------------------------------- #

_IPOTEKA_BUY = re.compile(
    r"Sotib olish kursi:\s*1\s*([A-Z]{3})\s*=\s*([\d\s\u00a0.,]+?)\s*UZS"
)
_IPOTEKA_SELL = re.compile(
    r"Sotish kursi:\s*1\s*([A-Z]{3})\s*=\s*([\d\s\u00a0.,]+?)\s*UZS"
)


def parse_ipoteka(page: str, code: str, checked_at: datetime) -> dict:
    """Parse one Ipoteka-bank per-currency page.

    The branch rate is published as ``Sotib olish kursi: 1 USD = 11915 UZS`` and
    ``Sotish kursi: 1 USD = 12030 UZS``; the stamp appears as
    ``Обновлено DD.MM.YYYY HH:MM:SS``. ``code`` is the currency of the page.
    """
    if code not in SUPPORTED_CURRENCIES:
        raise LayoutError(f"Ipoteka: unsupported currency {code}")
    buy = _ipoteka_value(_IPOTEKA_BUY, page, code)
    sell = _ipoteka_value(_IPOTEKA_SELL, page, code)
    if buy is None and sell is None:
        raise LayoutError(f"Ipoteka: no {code} rate found")
    stamp = re.search(
        r"(?:Обновлено|yangilangan)\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2})",
        page,
    )
    published = _parse_dt(stamp.group(1), checked_at) if stamp else None
    rates: dict = {}
    _merge(rates, code, "cash", buy, sell, published)
    if not rates:
        raise LayoutError(f"Ipoteka: no valid {code} rate")
    return rates


def _ipoteka_value(pattern: re.Pattern, page: str, code: str) -> Optional[float]:
    for found_code, raw in pattern.findall(page):
        if found_code.upper() == code:
            value = _to_float(raw)
            if value is not None:
                return value
    return None


# --------------------------------------------------------------------------- #
# Agrobank (https://agrobank.uz/api/v1/?action=pages&code=...)
# --------------------------------------------------------------------------- #


def parse_agrobank(payload: object) -> dict:
    """Parse Agrobank's page API for ``person/exchange_rates``.

    Sections hold alternating ``tab`` blocks (``office`` branch cash, ``atm``)
    and ``currency-rates`` blocks whose items are
    ``{alpha3, buy, rate, sale, updated}``. A zero ``buy``/``sale`` means the
    bank does not transact that side and is dropped.
    """
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise LayoutError("Agrobank: request not successful")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LayoutError("Agrobank: missing data")
    kind_by_tab = {"office": "cash", "atm": "mobile"}
    rates: dict = {}
    for section in data.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        current_kind: Optional[str] = None
        for block in section.get("blocks", []) or []:
            if not isinstance(block, dict):
                continue
            content = block.get("content") or {}
            if block.get("type") == "tab":
                current_kind = kind_by_tab.get(content.get("code"))
                continue
            if block.get("type") != "currency-rates" or current_kind is None:
                continue
            for item in content.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("alpha3") or "").upper()
                if code not in SUPPORTED_CURRENCIES:
                    continue
                _merge(rates, code, current_kind,
                       _to_float(item.get("buy")), _to_float(item.get("sale")),
                       _parse_dt(item.get("updated")))
    if not rates:
        raise LayoutError("Agrobank: no rates parsed")
    return rates


# --------------------------------------------------------------------------- #
# Hamkorbank (https://api-dbo.hamkorbank.uz/webflow/v1/exchanges)
# --------------------------------------------------------------------------- #


def parse_hamkorbank(payload: object) -> dict:
    """Parse Hamkorbank's public exchanges feed.

    ``destination_code`` 2 is the branch cash rate; ``destination_code`` 7 is
    the mobile-app rate. Among cash rows the ``begin_sum_i == 0`` row is the
    standard rate (rows with ``begin_sum_i > 0`` are the "up to 10,000" tier).
    All values are integers scaled by 100.
    """
    if not isinstance(payload, dict):
        raise LayoutError("Hamkorbank: unexpected payload")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise LayoutError("Hamkorbank: missing data")
    chosen: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("currency_char") or "").upper()
        if code not in SUPPORTED_CURRENCIES:
            continue
        destination = str(row.get("destination_code") or "").strip()
        try:
            begin_sum = int(row.get("begin_sum_i") or 0)
        except (TypeError, ValueError):
            begin_sum = 0
        if destination == "7":
            kind, priority = "mobile", 2
        elif destination == "2" and begin_sum == 0:
            kind, priority = "cash", 2
        elif destination == "2":
            kind, priority = "cash", 1
        else:
            continue
        current = chosen.get((code, kind))
        if current is None or priority >= current[0]:
            chosen[(code, kind)] = (
                priority,
                _scaled_value(row.get("buying_rate"), 100),
                _scaled_value(row.get("selling_rate"), 100),
                _parse_dt(row.get("created_at") or row.get("begin_date")),
            )
    rates: dict = {}
    for (code, kind), (_, buy, sell, published) in chosen.items():
        _merge(rates, code, kind, buy, sell, published)
    if not rates:
        raise LayoutError("Hamkorbank: no rates parsed")
    return rates


# --------------------------------------------------------------------------- #
# Xalq banki (https://xb.uz/api/v1/external/client/exchange-rate/last-thirty-day)
# --------------------------------------------------------------------------- #


def parse_xalq(payload: object, checked_at: Optional[datetime] = None) -> dict:
    """Parse Xalq banki's public client exchange-rate API.

    The response is keyed by ISO 4217 numeric code; each holds a ``data`` map of
    ``DD-MM-YYYY`` -> ``{buying, selling}``. The most recent date is used, and
    its stamp becomes ``published_at``. Values are UZS per 1 unit.
    """
    if not isinstance(payload, dict):
        raise LayoutError("Xalq: unexpected payload")
    rates: dict = {}
    for numeric, info in payload.items():
        code = NUMERIC_CODES.get(str(numeric).strip())
        if code is None or not isinstance(info, dict):
            continue
        data = info.get("data")
        if not isinstance(data, dict) or not data:
            continue
        latest = max(data, key=lambda stamp: _xalq_date_key(stamp))
        day = data[latest]
        if not isinstance(day, dict):
            continue
        _merge(rates, code, "cash", _to_float(day.get("buying")),
               _to_float(day.get("selling")), _parse_dt(latest, checked_at))
    if not rates:
        raise LayoutError("Xalq: no rates parsed")
    return rates


def _xalq_date_key(stamp) -> tuple:
    match = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", str(stamp))
    if not match:
        return (0, 0, 0)
    day, month, year = match.groups()
    return (int(year), int(month), int(day))


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def parse_source(kind: str, text: str, section: str, checked_at: datetime) -> dict:
    """Dispatch to the right parser for a source ``kind``."""
    if kind == "davr-html":
        return parse_davr(text, (section,), checked_at)
    if kind == "trastbank-html":
        return parse_trastbank(text, checked_at)
    if kind == "ipakyuli-nuxt":
        return parse_ipakyuli(text, checked_at)
    if kind == "ipoteka-html":
        return parse_ipoteka(text, section, checked_at)

    payload = json.loads(text)
    if kind == "sqb-api":
        return parse_sqb(payload)
    if kind == "brb-api":
        return parse_brb(payload)
    if kind == "mkbank-json":
        return parse_mkbank_json(payload, checked_at)
    if kind == "universalbank-api":
        return parse_universalbank(payload, checked_at)
    if kind == "agrobank-api":
        return parse_agrobank(payload)
    if kind == "hamkorbank-api":
        return parse_hamkorbank(payload)
    if kind == "xalq-api":
        return parse_xalq(payload, checked_at)
    raise LayoutError(f"unknown source kind: {kind}")
