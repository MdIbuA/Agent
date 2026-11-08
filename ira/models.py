"""Core data model for an invoice, aligned to a subset of PINT-AE business terms.

All money is Decimal (never float) because compliance maths must be exact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class Party:
    name: Optional[str] = None
    trn: Optional[str] = None          # UAE Tax Registration Number (15 digits)
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = "AE"


@dataclass
class LineItem:
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    vat_rate: Optional[Decimal] = None   # percent, e.g. Decimal("5")
    line_total: Optional[Decimal] = None  # net (excl. VAT) as stated on the source invoice


@dataclass
class Invoice:
    invoice_number: Optional[str] = None
    issue_date: Optional[str] = None      # ISO YYYY-MM-DD
    currency: Optional[str] = "AED"
    invoice_type: str = "380"             # UNCL1001: 380 = commercial invoice, 381 = credit note
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    lines: list[LineItem] = field(default_factory=list)
    stated_net_total: Optional[Decimal] = None
    stated_vat_total: Optional[Decimal] = None
    stated_gross_total: Optional[Decimal] = None
    source_file: Optional[str] = None


def to_decimal(value) -> Optional[Decimal]:
    """Lenient conversion for messy SME data: '1,250.00', 'AED 50', 50 -> Decimal."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).upper().replace("AED", "").replace(",", "").strip()
    try:
        return Decimal(text)
    except Exception:
        return None


def invoice_from_dict(d: dict) -> Invoice:
    """Build an Invoice from the JSON shape the LLM extractor (or synth data) produces."""
    def party(p: dict | None) -> Party:
        p = p or {}
        return Party(p.get("name"), p.get("trn"), p.get("address"), p.get("city"), p.get("country", "AE"))

    lines = [
        LineItem(
            description=l.get("description"),
            quantity=to_decimal(l.get("quantity")),
            unit_price=to_decimal(l.get("unit_price")),
            vat_rate=to_decimal(l.get("vat_rate")),
            line_total=to_decimal(l.get("line_total")),
        )
        for l in d.get("lines", [])
    ]
    return Invoice(
        invoice_number=d.get("invoice_number"),
        issue_date=d.get("issue_date"),
        currency=d.get("currency", "AED"),
        invoice_type=d.get("invoice_type", "380"),
        seller=party(d.get("seller")),
        buyer=party(d.get("buyer")),
        lines=lines,
        stated_net_total=to_decimal(d.get("net_total")),
        stated_vat_total=to_decimal(d.get("vat_total")),
        stated_gross_total=to_decimal(d.get("gross_total")),
        source_file=d.get("source_file"),
    )
