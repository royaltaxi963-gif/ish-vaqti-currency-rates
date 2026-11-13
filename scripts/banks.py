"""Authoritative registry of the 14 supported commercial banks.

Order is significant: it defines the output order in every published dataset.
An official bank domain or authorised public API is always preferred. A bank
whose official source is unreachable may additionally declare one *verified
fallback* (a reputable aggregator that republishes the bank's own published
rates and permits automated access). The fallback is used only when the
official source yields nothing usable; it never replaces a working official
source. A bank with neither is recorded as ``unavailable`` with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_CURRENCIES = ("USD", "EUR", "RUB", "KZT", "GBP")

RATE_KINDS = ("cash", "mobile")

OFFICIAL = "official"
FALLBACK = "fallback"

# bank.uz republishes each bank's own published rates and permits automated
# access (robots.txt: ``User-agent: * / Allow: /``, Crawl-delay 3). It is used
# only as a last resort when the bank's official source is unavailable; the
# collector prefers the official source whenever it returns usable rates.
BANKUZ_ATTRIBUTION = (
    "Rate collected from bank.uz (https://bank.uz), a third-party aggregator "
    "used only as a fallback because the bank's official source is unavailable; "
    "bank.uz republishes the bank's own published cash rates."
)


@dataclass(frozen=True)
class Source:
    """A single upstream location for one bank.

    ``kind`` selects the parser; ``kind_label`` is the primary rate type the
    source documents (a parser may still emit several kinds, e.g. cash and
    mobile, from one response). ``sections`` scopes multi-table sources such as
    Davr's cash/mobile tabs or Ipoteka's index tables. ``expect`` holds identity
    tokens that must appear in the fetched document before its rates are
    trusted, so a valid HTTP 200 is not mistaken for the correct bank.
    ``source_type`` is ``official`` or ``fallback`` and drives source selection.
    """

    kind: str
    url: str
    kind_label: str = "cash"
    sections: tuple[str, ...] = ()
    expect: tuple[str, ...] = ()
    source_type: str = OFFICIAL


@dataclass(frozen=True)
class Bank:
    """A supported bank and the verified sources that publish its rates."""

    slug: str
    name: str
    sources: tuple[Source, ...] = field(default_factory=tuple)
    fallback: Optional[Source] = None
    unavailable_reason: Optional[str] = None


BANKUZ = "https://bank.uz/uz/currency/bank/{slug}"


def _bankuz(slug: str, expect: tuple[str, ...]) -> Source:
    """A bank.uz fallback source that must name the correct bank."""
    return Source(
        "bankuz-html",
        BANKUZ.format(slug=slug),
        "cash",
        expect=expect,
        source_type=FALLBACK,
    )


BANKS: tuple[Bank, ...] = (
    Bank(
        "universalbank",
        "Universalbank",
        (Source("universalbank-api", "https://universalbank.uz/api/currencies/daily"),),
    ),
    Bank(
        "davr-bank",
        "Davr Bank",
        (
            Source(
                "davr-html",
                "https://davrbank.uz/uz/exchange-rate",
                "cash",
                ("Bank ofislarida valyutalar kursi",),
            ),
            Source(
                "davr-html",
                "https://davrbank.uz/uz/exchange-rate",
                "mobile",
                ("Mobil ilovada valyutalar kursi",),
            ),
        ),
    ),
    Bank(
        "asaka-bank",
        "Asakabank",
        fallback=_bankuz("asaka-bank", ("Asakabank",)),
        unavailable_reason=(
            "asakabank.uz/uz/press-center/exchange-rates renders its rate table "
            "client-side and serves no rates; its API host back.asakabank.uz "
            "answers HTTP 403 to every path from the collector network, so no "
            "official rate source is reachable"
        ),
    ),
    Bank(
        "trastbank",
        "Trastbank",
        (Source("trastbank-html", "https://trastbank.uz/uz/services/exchange-rates/"),),
    ),
    Bank(
        "sqb",
        "SQB",
        (
            Source(
                "sqb-api",
                "https://sqb.uz/api/site-kurs-api/",
                "cash",
                ("offline",),
            ),
            Source(
                "sqb-api",
                "https://sqb.uz/api/site-kurs-api/",
                "mobile",
                ("online", "atm"),
            ),
        ),
    ),
    Bank(
        "mikrokreditbank",
        "Mikrokreditbank",
        (Source("mkbank-json", "https://mkbank.uz/uz/services/open_data/rates/json/"),),
    ),
    Bank(
        "ipakyulibank",
        "Ipak Yo\u2018li Bank",
        (Source("ipakyuli-nuxt", "https://ipakyulibank.uz/physical/valyuta-ayirboshlash"),),
    ),
    Bank(
        "nbu",
        "O\u2018zmilliybank",
        fallback=_bankuz("nbu", ("Milliy bank",)),
        unavailable_reason=(
            "official site nbu.uz (185.104.210.5, also www.nbu.uz) accepts no "
            "TCP connection on ports 80 or 443 from the collector network (TLS "
            "handshake and HTTP request both time out); no official rate source "
            "is reachable"
        ),
    ),
    Bank(
        "ipoteka-bank",
        "Ipoteka-bank",
        (
            Source(
                "ipoteka-html",
                "https://ipotekabank.uz/services/currency/",
                "cash",
            ),
        ),
    ),
    Bank(
        "brb",
        "Biznesni rivojlantirish banki (BRB)",
        (
            Source(
                "brb-api",
                "https://brb.uz/api/currency/compare?type=jismoniy",
                "cash",
            ),
            Source(
                "brb-api",
                "https://brb.uz/api/currency/compare?type=jismoniy",
                "mobile",
            ),
        ),
    ),
    Bank(
        "agrobank",
        "Agrobank",
        (
            Source(
                "agrobank-api",
                "https://agrobank.uz/api/v1/?action=pages&code=uz/person/exchange_rates",
            ),
        ),
    ),
    Bank(
        "hamkorbank",
        "Hamkorbank",
        (Source("hamkorbank-api", "https://api-dbo.hamkorbank.uz/webflow/v1/exchanges"),),
        fallback=_bankuz("hamkorbank", ("Hamkorbank",)),
    ),
    Bank(
        "xalq-bank",
        "Xalq banki",
        (
            Source(
                "xalq-api",
                "https://xb.uz/api/v1/external/client/exchange-rate/last-thirty-day",
            ),
        ),
    ),
    Bank(
        "kapitalbank",
        "Kapitalbank",
        fallback=_bankuz("kapitalbank", ("Kapitalbank",)),
        unavailable_reason=(
            "official site kapitalbank.uz answers HTTP 403 with a Cloudflare "
            "anti-bot challenge (\"Just a moment...\"); kapital24.uz redirects "
            "there and no public rate API host resolves, so access must not be "
            "bypassed and no official rate source is reachable"
        ),
    ),
)

BANKS_BY_SLUG = {bank.slug: bank for bank in BANKS}

assert len(BANKS) == 14, "the target list must contain exactly 14 banks"
assert len(BANKS_BY_SLUG) == len(BANKS), "bank slugs must be unique"
