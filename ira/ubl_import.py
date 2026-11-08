"""Read UBL 2.1 / PINT-AE invoices and credit notes into the agent's model.

Lets the agent check e-invoices an ERP already produces, and is exercised against the
official OpenPeppol PINT AE example files in benchmarks/agreement.py.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from .models import to_decimal

CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS = {"cac": CAC, "cbc": CBC}
_MAX_BYTES = 5 * 1024 * 1024


def _t(node, path: str):
    if node is None:
        return None
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _party(p) -> dict:
    if p is None:
        return {}
    legal = p.find("cac:PartyLegalEntity/cbc:CompanyID", NS)
    return {
        "name": _t(p, "cac:PartyLegalEntity/cbc:RegistrationName") or _t(p, "cac:PartyName/cbc:Name"),
        "trn": _t(p, "cac:PartyTaxScheme/cbc:CompanyID"),
        "address": _t(p, "cac:PostalAddress/cbc:StreetName"),
        "city": _t(p, "cac:PostalAddress/cbc:CityName"),
        "country": _t(p, "cac:PostalAddress/cac:Country/cbc:IdentificationCode") or "AE",
        "emirate": _t(p, "cac:PostalAddress/cbc:CountrySubentity"),
        "legal_id": legal.text.strip() if legal is not None and legal.text else None,
        "legal_id_type": legal.get("schemeAgencyID") if legal is not None else None,
        "legal_authority": legal.get("schemeAgencyName") if legal is not None else None,
        "party_id": _t(p, "cac:PartyIdentification/cbc:ID"),
    }


def _adjustment(container) -> Decimal:
    """Charges minus allowances directly under `container` (not the price-level ones)."""
    total = Decimal("0")
    for ac in container.findall("cac:AllowanceCharge", NS):
        amt = to_decimal(_t(ac, "cbc:Amount")) or Decimal("0")
        total += amt if _t(ac, "cbc:ChargeIndicator") == "true" else -amt
    return total


def parse_ubl(xml_text: str) -> dict:
    """UBL Invoice or CreditNote XML -> the dict shape used by models.invoice_from_dict."""
    if len(xml_text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("XML file is too large.")
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError("XML with DTDs or entities is not accepted.")  # XXE / billion-laughs guard
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Not valid XML: {e}") from e
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in ("Invoice", "CreditNote"):
        raise ValueError(f"Expected a UBL Invoice or CreditNote, got <{kind}>.")
    credit = kind == "CreditNote"
    line_tag, qty_tag = ("cac:CreditNoteLine", "cbc:CreditedQuantity") if credit else \
                        ("cac:InvoiceLine", "cbc:InvoicedQuantity")

    lines = []
    for ln in root.findall(line_tag, NS):
        price = to_decimal(_t(ln, "cac:Price/cbc:PriceAmount"))
        base = to_decimal(_t(ln, "cac:Price/cbc:BaseQuantity")) or Decimal("1")
        rate = _t(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")
        lines.append({
            "description": _t(ln, "cac:Item/cbc:Name") or _t(ln, "cac:Item/cbc:Description"),
            "quantity": _t(ln, qty_tag),
            "unit_code": (ln.find(qty_tag, NS).get("unitCode") if ln.find(qty_tag, NS) is not None else None),
            "unit_price": str(price / base) if price is not None and base else None,
            "vat_rate": rate,
            "vat_category": _t(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
            "line_total": _t(ln, "cbc:LineExtensionAmount"),
            "adjustment": str(_adjustment(ln)),
        })

    lmt = root.find("cac:LegalMonetaryTotal", NS)
    # Tax total in document currency: the TaxTotal whose TaxAmount uses the document currency.
    cur = _t(root, "cbc:DocumentCurrencyCode") or "AED"
    vat_total = None
    for tt in root.findall("cac:TaxTotal", NS):
        amt = tt.find("cbc:TaxAmount", NS)
        if amt is not None and amt.get("currencyID", cur) == cur:
            vat_total = amt.text
            break
    return {
        "invoice_number": _t(root, "cbc:ID"),
        "issue_date": _t(root, "cbc:IssueDate"),
        "due_date": _t(root, "cbc:DueDate") or _t(root, "cac:PaymentMeans/cbc:PaymentDueDate"),
        "currency": cur,
        "invoice_type": _t(root, "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode")
                        or ("381" if credit else "380"),
        "transaction_type": _t(root, "cbc:ProfileExecutionID"),
        "customization_id": _t(root, "cbc:CustomizationID"),
        "payment_means": _t(root, "cac:PaymentMeans/cbc:PaymentMeansCode"),
        "preceding_invoice": _t(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
        "preceding_invoice_date": _t(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate"),
        "credit_reason": _t(root, "cac:DiscrepancyResponse/cbc:ResponseCode"),
        "seller": _party(root.find("cac:AccountingSupplierParty/cac:Party", NS)),
        "buyer": _party(root.find("cac:AccountingCustomerParty/cac:Party", NS)),
        "lines": lines,
        "doc_adjustments": [
            {"amount": str((to_decimal(_t(ac, "cbc:Amount")) or Decimal("0"))
                           * (1 if _t(ac, "cbc:ChargeIndicator") == "true" else -1)),
             "category": _t(ac, "cac:TaxCategory/cbc:ID"), "rate": _t(ac, "cac:TaxCategory/cbc:Percent")}
            for ac in root.findall("cac:AllowanceCharge", NS)],
        "net_total": _t(lmt, "cbc:TaxExclusiveAmount"),
        "vat_total": vat_total,
        "gross_total": _t(lmt, "cbc:TaxInclusiveAmount"),
    }
