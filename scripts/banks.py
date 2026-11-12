"""Authoritative registry of the 14 supported commercial banks.

Order is significant: it defines the output order in every published dataset.
Only the sources listed here are treated as verified; anything else is reported
as unavailable rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_CURRENCIES = ("USD", "EUR", "RUB", "KZT", "GBP")

RATE_KINDS = ("cash", "mobile")

# bank.uz publishes one card ("offline"/cash) rate row per currency and does not
# distinguish cash from mobile, so rows collected there are labelled "cash".
BANKUZ_KIND = "cash"


@dataclass(frozen=True)
class Source:
    """A single upstream location for one bank."""

    kind: str  # "bankuz" | "brb-api" | "sqb-api" | "davr-html"
    url: str
    kind_label: str = BANKUZ_KIND  # rate type produced by this source
    sections: tuple[str, ...] = ()  # for multi-section sources such as Davr


@dataclass(frozen=True)
class Bank:
    """A supported bank and the verified sources that publish its rates."""

    slug: str
    name: str
    sources: tuple[Source, ...] = field(default_factory=tuple)
    unavailable_reason: Optional[str] = None


BANKUZ = "https://bank.uz/uz/currency/bank/{slug}"


def _bankuz(slug: str) -> Source:
    return Source(kind="bankuz", url=BANKUZ.format(slug=slug), kind_label=BANKUZ_KIND)


BANKS: tuple[Bank, ...] = (
    Bank("universalbank", "Universalbank", (_bankuz("universalbank"),)),
    Bank(
        "davr-bank",
        "Davr Bank",
        (
            Source(
                kind="davr-html",
                url="https://davrbank.uz/uz/exchange-rate",
                kind_label="cash",
                sections=("Bank ofislarida valyutalar kursi",),
            ),
            Source(
                kind="davr-html",
                url="https://davrbank.uz/uz/exchange-rate",
                kind_label="mobile",
                sections=("Mobil ilovada valyutalar kursi",),
            ),
        ),
    ),
    Bank("asaka-bank", "Asakabank", (_bankuz("asaka-bank"),)),
    Bank("trastbank", "Trastbank", (_bankuz("trastbank"),)),
    Bank(
        "sqb",
        "SQB",
        (
            Source(
                kind="sqb-api",
                url="https://sqb.uz/api/site-kurs-api/",
                kind_label="cash",
                sections=("offline",),
            ),
            Source(
                kind="sqb-api",
                url="https://sqb.uz/api/site-kurs-api/",
                kind_label="mobile",
                sections=("online", "atm"),
            ),
        ),
    ),
    Bank("mikrokreditbank", "Mikrokreditbank", (_bankuz("mikrokreditbank"),)),
    Bank("ipakyulibank", "Ipak Yo\u2018li Bank", (_bankuz("ipakyulibank"),)),
    Bank("nbu", "O\u2018zmilliybank", (_bankuz("nbu"),)),
    Bank("ipoteka-bank", "Ipoteka-bank", (_bankuz("ipoteka-bank"),)),
    Bank(
        "brb",
        "Biznesni rivojlantirish banki (BRB)",
        (
            Source(
                kind="brb-api",
                url="https://brb.uz/api/currency/compare?type=jismoniy",
                kind_label="cash",
            ),
            Source(
                kind="brb-api",
                url="https://brb.uz/api/currency/compare?type=jismoniy",
                kind_label="mobile",
            ),
        ),
    ),
    Bank("agrobank", "Agrobank", (_bankuz("agrobank"),)),
    Bank("hamkorbank", "Hamkorbank", (_bankuz("hamkorbank"),)),
    Bank("xalq-bank", "Xalq banki", (_bankuz("xalq-bank"),)),
    Bank("kapitalbank", "Kapitalbank", (_bankuz("kapitalbank"),)),
)

BANKS_BY_SLUG = {bank.slug: bank for bank in BANKS}

assert len(BANKS) == 14, "the target list must contain exactly 14 banks"
assert len(BANKS_BY_SLUG) == len(BANKS), "bank slugs must be unique"
