"""Authoritative registry of the 14 supported commercial banks.

Order is significant: it defines the output order in every published dataset.
Only official bank domains or authorised public APIs are listed here. A bank
whose official source cannot be reached is recorded as ``unavailable`` with an
explicit reason instead of being pointed at a third-party aggregator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_CURRENCIES = ("USD", "EUR", "RUB", "KZT", "GBP")

RATE_KINDS = ("cash", "mobile")


@dataclass(frozen=True)
class Source:
    """A single upstream location for one bank.

    ``kind`` selects the parser; ``kind_label`` is the primary rate type the
    source documents (a parser may still emit several kinds, e.g. cash and
    mobile, from one response). ``sections`` scopes multi-table sources such as
    Davr's cash/mobile tabs or Ipoteka's per-currency pages.
    """

    kind: str
    url: str
    kind_label: str = "cash"
    sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bank:
    """A supported bank and the verified official sources that publish rates."""

    slug: str
    name: str
    sources: tuple[Source, ...] = field(default_factory=tuple)
    unavailable_reason: Optional[str] = None


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
        unavailable_reason=(
            "official site asakabank.uz renders rates client-side from "
            "back.asakabank.uz; no public rate endpoint was reachable"
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
        unavailable_reason=(
            "official site nbu.uz (185.104.210.5) refuses all connections on "
            "ports 80 and 443 from the collector network"
        ),
    ),
    Bank(
        "ipoteka-bank",
        "Ipoteka-bank",
        (
            Source(
                "ipoteka-html",
                "https://ipotekabank.uz/services/currency/usd-uzs/",
                "cash",
                ("USD",),
            ),
            Source(
                "ipoteka-html",
                "https://ipotekabank.uz/services/currency/eur-uzs/",
                "cash",
                ("EUR",),
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
        unavailable_reason=(
            "official site kapitalbank.uz is behind a Cloudflare anti-bot "
            "challenge (HTTP 403); access must not be bypassed"
        ),
    ),
)

BANKS_BY_SLUG = {bank.slug: bank for bank in BANKS}

assert len(BANKS) == 14, "the target list must contain exactly 14 banks"
assert len(BANKS_BY_SLUG) == len(BANKS), "bank slugs must be unique"
