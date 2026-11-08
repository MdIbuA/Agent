"""Generate a UBL 2.1 invoice XML from a validated Invoice.

This produces the structured payload an Accredited Service Provider (ASP) ingests.
The agent does NOT transmit to Peppol -- only accredited ASPs may do that.

TODO before submission: confirm CUSTOMIZATION_ID / PROFILE_ID and the full element
set against the official PINT-AE specification, and validate the output against the
OASIS UBL 2.1 XSD (free download) as a second check.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal

from .models import Invoice, Party

NS = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"  # VERIFY against official spec
PROFILE_ID = "urn:peppol:bis:billing"                # VERIFY against official spec

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def _q(tag: str) -> str:
    prefix, _, local = tag.rpartition(":")
    return f"{{{NS[prefix]}}}{local}"


def _el(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, _q(tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _money(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _party(parent, tag: str, p: Party):
    wrap = _el(parent, tag)
    party = _el(wrap, "cac:Party")
    addr = _el(party, "cac:PostalAddress")
    _el(addr, "cbc:StreetName", p.address or "")
    _el(addr, "cbc:CityName", p.city or "")
    _el(_el(addr, "cac:Country"), "cbc:IdentificationCode", p.country or "AE")
    tax = _el(party, "cac:PartyTaxScheme")
    _el(tax, "cbc:CompanyID", p.trn or "")
    _el(_el(tax, "cac:TaxScheme"), "cbc:ID", "VAT")
    _el(_el(party, "cac:PartyLegalEntity"), "cbc:RegistrationName", p.name or "")


def to_ubl_xml(inv: Invoice) -> str:
    cur = inv.currency or "AED"
    root = ET.Element(_q(":Invoice"))
    _el(root, "cbc:CustomizationID", CUSTOMIZATION_ID)
    _el(root, "cbc:ProfileID", PROFILE_ID)
    _el(root, "cbc:ID", inv.invoice_number)
    _el(root, "cbc:IssueDate", inv.issue_date)
    _el(root, "cbc:InvoiceTypeCode", inv.invoice_type)
    _el(root, "cbc:DocumentCurrencyCode", cur)
    _party(root, "cac:AccountingSupplierParty", inv.seller)
    _party(root, "cac:AccountingCustomerParty", inv.buyer)

    # Group VAT by rate (UBL requires one TaxSubtotal per category/rate).
    by_rate: dict[Decimal, list[Decimal]] = {}
    net_total = Decimal("0")
    for ln in inv.lines:
        net = (ln.quantity * ln.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net_total += net
        by_rate.setdefault(ln.vat_rate, []).append(net)

    vat_total = Decimal("0")
    tax_total = _el(root, "cac:TaxTotal")
    tax_amount_el = _el(tax_total, "cbc:TaxAmount", "0", currencyID=cur)
    for rate, nets in sorted(by_rate.items()):
        taxable = sum(nets, Decimal("0"))
        # Per-line rounding, matching validate.py, so totals agree exactly.
        tax = sum(((n * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for n in nets),
                  Decimal("0"))
        vat_total += tax
        sub = _el(tax_total, "cac:TaxSubtotal")
        _el(sub, "cbc:TaxableAmount", _money(taxable), currencyID=cur)
        _el(sub, "cbc:TaxAmount", _money(tax), currencyID=cur)
        cat = _el(sub, "cac:TaxCategory")
        _el(cat, "cbc:ID", "S" if rate > 0 else "Z")  # S = standard, Z = zero-rated
        _el(cat, "cbc:Percent", _money(rate))
        _el(_el(cat, "cac:TaxScheme"), "cbc:ID", "VAT")
    tax_amount_el.text = _money(vat_total)

    lmt = _el(root, "cac:LegalMonetaryTotal")
    _el(lmt, "cbc:LineExtensionAmount", _money(net_total), currencyID=cur)
    _el(lmt, "cbc:TaxExclusiveAmount", _money(net_total), currencyID=cur)
    _el(lmt, "cbc:TaxInclusiveAmount", _money(net_total + vat_total), currencyID=cur)
    _el(lmt, "cbc:PayableAmount", _money(net_total + vat_total), currencyID=cur)

    for i, ln in enumerate(inv.lines, start=1):
        il = _el(root, "cac:InvoiceLine")
        _el(il, "cbc:ID", i)
        _el(il, "cbc:InvoicedQuantity", ln.quantity, unitCode="C62")  # C62 = "one"/unit
        _el(il, "cbc:LineExtensionAmount", _money(ln.quantity * ln.unit_price), currencyID=cur)
        item = _el(il, "cac:Item")
        _el(item, "cbc:Name", ln.description)
        cat = _el(item, "cac:ClassifiedTaxCategory")
        _el(cat, "cbc:ID", "S" if ln.vat_rate > 0 else "Z")
        _el(cat, "cbc:Percent", _money(ln.vat_rate))
        _el(_el(cat, "cac:TaxScheme"), "cbc:ID", "VAT")
        _el(_el(il, "cac:Price"), "cbc:PriceAmount", _money(ln.unit_price), currencyID=cur)

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
