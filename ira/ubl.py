"""Generate a PINT-AE (Peppol PINT, UAE) UBL 2.1 invoice from a validated Invoice.

Structure follows the official OpenPeppol PINT AE Billing v1.0.3 example
"Standard invoice Mandatory fields.xml", and output is checked against the official
compiled Schematron in benchmarks/pint_ae_check.py (see BENCHMARK.md).

The agent does NOT transmit to Peppol -- only Accredited Service Providers may do that.
Only technical identifiers are derived here (UUID, transaction-type code, Peppol
endpoint from the TRN). Business facts (due date, payment method, emirate) must come
from the invoice or the owner; validate.py blocks export until they are present.
"""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal

from .models import Invoice, Party

NS = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"   # PINT AE Billing (official example)
PROFILE_ID = "urn:peppol:bis:billing"
TRANSACTION_TYPE_STANDARD = "00000000"               # BTAE-02: no special flags (not FTZ, deemed, export...)
UAE_TIN_SCHEME = "0235"                              # Peppol EAS for UAE TIN
UNIT_PIECE = "H87"                                   # UN/ECE Rec 20: piece
_UUID_NS = uuid.UUID("6f1c3a52-6a77-4a8e-9c0f-6d2a1f0e5b11")

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

CENT = Decimal("0.01")


def _q(tag: str) -> str:
    prefix, _, local = tag.rpartition(":")
    return f"{{{NS[prefix]}}}{local}"


def _el(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, _q(tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _r(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _money(x: Decimal) -> str:
    return str(_r(x))


def _num(x: Decimal) -> str:
    """Quantities and percentages without trailing zeros (10, 2.5)."""
    return format(x.normalize(), "f")


def document_uuid(inv: Invoice) -> str:
    """BTAE-07. Deterministic so re-exporting the same invoice yields the same identifier."""
    return str(uuid.uuid5(_UUID_NS, f"{inv.seller.trn}|{inv.invoice_number}|{inv.issue_date}"))


def _party(parent, tag: str, p: Party):
    party = _el(_el(parent, tag), "cac:Party")
    if p.trn:  # Peppol electronic address: UAE TIN = first 10 digits of the TRN
        _el(party, "cbc:EndpointID", p.trn[:10], schemeID=UAE_TIN_SCHEME)
    addr = _el(party, "cac:PostalAddress")
    _el(addr, "cbc:StreetName", p.address or "")
    _el(addr, "cbc:CityName", p.city or "")
    if p.emirate:
        _el(addr, "cbc:CountrySubentity", p.emirate)
    _el(_el(addr, "cac:Country"), "cbc:IdentificationCode", p.country or "AE")
    tax = _el(party, "cac:PartyTaxScheme")
    _el(tax, "cbc:CompanyID", p.trn or "")
    _el(_el(tax, "cac:TaxScheme"), "cbc:ID", "VAT")
    legal = _el(party, "cac:PartyLegalEntity")
    _el(legal, "cbc:RegistrationName", p.name or "")
    if p.legal_id:
        attrs = {"schemeAgencyID": p.legal_id_type or "TL"}
        if p.legal_authority:
            attrs["schemeAgencyName"] = p.legal_authority
        _el(legal, "cbc:CompanyID", p.legal_id, **attrs)


def _category(rate: Decimal) -> str:
    return "S" if rate > 0 else "Z"  # S = standard rated, Z = zero rated


def to_ubl_xml(inv: Invoice) -> str:
    cur = inv.currency or "AED"
    root = ET.Element(_q(":Invoice"))
    _el(root, "cbc:CustomizationID", CUSTOMIZATION_ID)
    _el(root, "cbc:ProfileID", PROFILE_ID)
    _el(root, "cbc:ProfileExecutionID", TRANSACTION_TYPE_STANDARD)
    _el(root, "cbc:ID", inv.invoice_number)
    _el(root, "cbc:UUID", document_uuid(inv))
    _el(root, "cbc:IssueDate", inv.issue_date)
    if inv.due_date:
        _el(root, "cbc:DueDate", inv.due_date)
    _el(root, "cbc:InvoiceTypeCode", inv.invoice_type)
    _el(root, "cbc:DocumentCurrencyCode", cur)
    _party(root, "cac:AccountingSupplierParty", inv.seller)
    _party(root, "cac:AccountingCustomerParty", inv.buyer)
    if inv.payment_means:
        _el(_el(root, "cac:PaymentMeans"), "cbc:PaymentMeansCode", inv.payment_means)

    # Per-line amounts, rounded per line exactly as validate.py does, so totals agree.
    lines = []
    for ln in inv.lines:
        net = _r(ln.quantity * ln.unit_price)
        vat = _r(net * ln.vat_rate / 100)
        lines.append((ln, net, vat))

    by_rate: dict[Decimal, list[tuple[Decimal, Decimal]]] = {}
    for ln, net, vat in lines:
        by_rate.setdefault(ln.vat_rate, []).append((net, vat))
    net_total = sum((n for _, n, _ in lines), Decimal("0"))
    vat_total = sum((v for _, _, v in lines), Decimal("0"))

    tax_total = _el(root, "cac:TaxTotal")
    _el(tax_total, "cbc:TaxAmount", _money(vat_total), currencyID=cur)
    for rate, parts in sorted(by_rate.items()):
        sub = _el(tax_total, "cac:TaxSubtotal")
        _el(sub, "cbc:TaxableAmount", _money(sum((n for n, _ in parts), Decimal("0"))), currencyID=cur)
        _el(sub, "cbc:TaxAmount", _money(sum((v for _, v in parts), Decimal("0"))), currencyID=cur)
        cat = _el(sub, "cac:TaxCategory")
        _el(cat, "cbc:ID", _category(rate))
        _el(cat, "cbc:Percent", _num(rate))
        _el(_el(cat, "cac:TaxScheme"), "cbc:ID", "VAT")

    lmt = _el(root, "cac:LegalMonetaryTotal")
    _el(lmt, "cbc:LineExtensionAmount", _money(net_total), currencyID=cur)
    _el(lmt, "cbc:TaxExclusiveAmount", _money(net_total), currencyID=cur)
    _el(lmt, "cbc:TaxInclusiveAmount", _money(net_total + vat_total), currencyID=cur)
    _el(lmt, "cbc:PayableAmount", _money(net_total + vat_total), currencyID=cur)

    for i, (ln, net, vat) in enumerate(lines, start=1):
        il = _el(root, "cac:InvoiceLine")
        _el(il, "cbc:ID", i)
        _el(il, "cbc:InvoicedQuantity", _num(ln.quantity), unitCode=UNIT_PIECE)
        _el(il, "cbc:LineExtensionAmount", _money(net), currencyID=cur)
        item = _el(il, "cac:Item")
        _el(item, "cbc:Description", ln.description)
        _el(item, "cbc:Name", ln.description)
        cat = _el(item, "cac:ClassifiedTaxCategory")
        _el(cat, "cbc:ID", _category(ln.vat_rate))
        _el(cat, "cbc:Percent", _num(ln.vat_rate))
        _el(_el(cat, "cac:TaxScheme"), "cbc:ID", "VAT")
        price = _el(il, "cac:Price")
        _el(price, "cbc:PriceAmount", _money(ln.unit_price), currencyID=cur)
        _el(price, "cbc:BaseQuantity", "1", unitCode=UNIT_PIECE)
        ac = _el(price, "cac:AllowanceCharge")  # gross price = net price (no price discount)
        _el(ac, "cbc:ChargeIndicator", "false")
        _el(ac, "cbc:Amount", "0.00", currencyID=cur)
        _el(ac, "cbc:BaseAmount", _money(ln.unit_price), currencyID=cur)
        ext = _el(il, "cac:ItemPriceExtension")  # BTAE-10 / BTAE-08: line amounts in AED
        _el(ext, "cbc:Amount", _money(net + vat), currencyID=cur)
        _el(_el(ext, "cac:TaxTotal"), "cbc:TaxAmount", _money(vat), currencyID=cur)

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
