"""Deterministic validation. The LLM never decides compliance -- this module does.

Rule set is a CORE SUBSET for the MVP. Before submission, map every rule to the
official PINT-AE data dictionary / FTA specification and extend the list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .codelists import CREDIT_REASONS, COUNTRIES, CURRENCIES, PAYMENT_MEANS_CODES, UNIT_CODES
from .models import SELF_ACCOUNTED, ZERO_CATEGORIES, ZERO_RATE_CATEGORIES, Invoice, line_category

ALLOWED_VAT_RATES = {Decimal("5"), Decimal("0")}
CENT = Decimal("0.01")
# PINT-AE ibr-132-ae: TRN is 15 digits, starts with 1, ends with 03.
TRN_RE = re.compile(r"^1\d{12}03$")
EMIRATE_CODES = {"AUH", "DXB", "SHJ", "AJM", "UAQ", "RAK", "FUJ"}
# Official PINT AE payment means (UNCL4461 subset), with friendly names for the UI.
PAYMENT_MEANS = {"1": "Not defined", "10": "Cash", "20": "Cheque", "21": "Banker's draft",
                 "30": "Credit transfer", "49": "Direct debit", "54": "Credit card",
                 "55": "Debit card", "68": "Online payment service"}
assert set(PAYMENT_MEANS) == PAYMENT_MEANS_CODES, "keep in sync with the official code list"
PINT_AE_CUSTOMIZATION = "urn:peppol:pint:billing-1@ae-1"


@dataclass(frozen=True)
class Issue:
    code: str          # stable ID, used by the eval harness
    severity: str      # "error" blocks submission, "warning" needs review
    field: str         # where the problem is
    message: str       # human explanation
    question: str = "" # what the agent should ask the SME owner to fix it


def _r(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_trn(raw: str | None) -> str | None:
    """SMEs write TRNs with spaces/dashes; strip them before checking."""
    if raw is None:
        return None
    return re.sub(r"[\s\-]", "", str(raw))


def validate(inv: Invoice) -> list[Issue]:
    issues: list[Issue] = []
    add = issues.append

    # --- Header -------------------------------------------------------------
    if not inv.invoice_number:
        add(Issue("MISSING_INVOICE_NUMBER", "error", "invoice_number",
                  "Invoice number is missing.", "What is the invoice number?"))
    if not inv.issue_date:
        add(Issue("MISSING_ISSUE_DATE", "error", "issue_date",
                  "Issue date is missing.", "What date was this invoice issued?"))
    else:
        try:
            d = date.fromisoformat(inv.issue_date)
            if d > date.today():
                add(Issue("FUTURE_ISSUE_DATE", "warning", "issue_date",
                          f"Issue date {d} is in the future.", "Is the issue date correct?"))
        except ValueError:
            add(Issue("BAD_ISSUE_DATE", "error", "issue_date",
                      f"Issue date '{inv.issue_date}' is not YYYY-MM-DD.",
                      "What is the exact issue date?"))
    if inv.customization_id and inv.customization_id != PINT_AE_CUSTOMIZATION:
        add(Issue("WRONG_SPECIFICATION", "error", "customization_id",
                  f"Document declares '{inv.customization_id}', not the UAE PINT AE specification.", ""))
    if inv.currency and inv.currency not in CURRENCIES:
        add(Issue("BAD_CURRENCY", "error", "currency",
                  f"Currency '{inv.currency}' is not an ISO 4217 code.", "Which currency is this invoice in?"))
    elif inv.currency != "AED":
        add(Issue("NON_AED_CURRENCY", "warning", "currency",
                  f"Currency is {inv.currency}; VAT amounts must also be reported in AED.",
                  "What exchange rate to AED applies to this invoice?"))

    # --- Parties ------------------------------------------------------------
    for role, party in (("seller", inv.seller), ("buyer", inv.buyer)):
        if not party.name:
            add(Issue(f"MISSING_{role.upper()}_NAME", "error", f"{role}.name",
                      f"{role.title()} legal name is missing.", f"What is the {role}'s legal name?"))
        trn = normalize_trn(party.trn)
        if not trn and role == "buyer" and ((party.country or "AE") != "AE" or party.party_id or party.legal_id):
            pass  # foreign or non-VAT-registered buyer identified another way (PINT-AE ibr-135-ae)
        elif not trn:
            add(Issue(f"MISSING_{role.upper()}_TRN", "error", f"{role}.trn",
                      f"{role.title()} TRN is missing.",
                      f"What is the {role}'s 15-digit Tax Registration Number?"))
        elif not TRN_RE.match(trn):
            add(Issue(f"BAD_{role.upper()}_TRN", "error", f"{role}.trn",
                      f"{role.title()} TRN '{party.trn}' is not a valid UAE TRN "
                      "(15 digits, starting with 1 and ending with 03).",
                      f"Please re-check the {role}'s TRN. It has 15 digits, starts with 1 and ends with 03."))
        if not party.address:
            add(Issue(f"MISSING_{role.upper()}_ADDRESS", "error", f"{role}.address",
                      f"{role.title()} address is missing.", f"What is the {role}'s address?"))
        if party.country and party.country not in COUNTRIES:
            add(Issue(f"BAD_{role.upper()}_COUNTRY", "error", f"{role}.country",
                      f"{role.title()} country '{party.country}' is not an ISO 3166 code.", ""))
        if (party.country or "AE") == "AE" and party.emirate not in EMIRATE_CODES:
            add(Issue(f"MISSING_{role.upper()}_EMIRATE", "error", f"{role}.emirate",
                      f"{role.title()} emirate is missing or invalid (PINT-AE ibr-128-ae).",
                      f"Which emirate is the {role} in?"))
    # PINT-AE ibr-150-ae / ibr-172-ae: seller legal registration + issuing authority.
    if not inv.seller.legal_id:
        add(Issue("MISSING_SELLER_LICENSE", "error", "seller.legal_id",
                  "Seller trade licence number is missing (PINT-AE ibr-150-ae).",
                  "What is the seller's trade licence number?"))
    elif (inv.seller.legal_id_type or "TL") == "TL" and not inv.seller.legal_authority:
        add(Issue("MISSING_SELLER_LICENSE_AUTHORITY", "error", "seller.legal_authority",
                  "Trade licence issuing authority is missing (PINT-AE ibr-172-ae).",
                  "Which authority issued the seller's trade licence?"))

    # Advisory check against the official Ajman DED licence register (UAE open data).
    from .registry import check_seller_licence
    finding = check_seller_licence(inv.seller.legal_id, inv.seller.legal_authority, inv.seller.name)
    if finding:
        add(Issue(finding[0], "warning", "seller.legal_id", finding[1],
                  "Please re-check the seller's trade licence number."))

    s_trn, b_trn = normalize_trn(inv.seller.trn), normalize_trn(inv.buyer.trn)
    if s_trn and s_trn == b_trn:
        add(Issue("SAME_TRN", "error", "buyer.trn",
                  "Seller and buyer have the same TRN.", "Which TRN belongs to the buyer?"))

    if inv.invoice_type in ("381", "81"):
        if inv.credit_reason not in CREDIT_REASONS:  # PINT-AE ibr-158-ae
            add(Issue("MISSING_CREDIT_REASON", "error", "credit_reason",
                      "Credit note reason is missing or not an official UAE reason code.",
                      "Why is this credit note being issued?"))
        if inv.credit_reason != "VD" and not inv.preceding_invoice:  # ibr-055-ae
            add(Issue("MISSING_PRECEDING_INVOICE", "error", "preceding_invoice",
                      "A credit note must reference the invoice it corrects.",
                      "Which invoice number does this credit note correct?"))

    # --- Payment (PINT-AE ibr-127-ae, ibr-191-ae). Exempt: credit notes (381, 81, 261)
    #     and deemed supplies (transaction flag position 2).
    deemed = len(inv.transaction_type or "") > 1 and inv.transaction_type[1] == "1"
    if inv.invoice_type not in ("381", "81", "261") and not deemed:
        if not inv.due_date:
            add(Issue("MISSING_DUE_DATE", "error", "due_date",
                      "Payment due date is missing (PINT-AE ibr-127-ae).",
                      "When is payment due for this invoice?"))
        else:
            try:
                date.fromisoformat(inv.due_date)
            except ValueError:
                add(Issue("BAD_DUE_DATE", "error", "due_date",
                          f"Due date '{inv.due_date}' is not a valid date.", "When is payment due?"))
        if inv.payment_means not in PAYMENT_MEANS_CODES:
            add(Issue("MISSING_PAYMENT_MEANS", "error", "payment_means",
                      "Payment method is missing (PINT-AE ibr-191-ae).",
                      "How will the buyer pay this invoice?"))

    # --- Lines --------------------------------------------------------------
    if not inv.lines:
        add(Issue("NO_LINES", "error", "lines", "Invoice has no line items.",
                  "What goods or services does this invoice cover?"))

    net_sum = Decimal("0")
    taxable: dict[tuple[str, Decimal], Decimal] = {}
    lines_ok = True
    vat_ok = True  # a bad rate makes VAT/gross totals meaningless; report the root cause only
    for i, ln in enumerate(inv.lines, start=1):
        f = f"lines[{i}]"
        if not ln.description:
            add(Issue("MISSING_LINE_DESCRIPTION", "error", f"{f}.description",
                      f"Line {i} has no description.", f"What was sold on line {i}?"))
        if ln.quantity is None or ln.unit_price is None:
            add(Issue("MISSING_LINE_AMOUNT", "error", f"{f}.quantity",
                      f"Line {i} is missing quantity or unit price.",
                      f"What are the quantity and unit price on line {i}?"))
            lines_ok = False
            continue
        if ln.quantity <= 0 and inv.invoice_type == "380":
            add(Issue("NON_POSITIVE_QTY", "warning", f"{f}.quantity",
                      f"Line {i} quantity is {ln.quantity}; should this be a credit note?",
                      "Is this a credit note rather than an invoice?"))
        if ln.unit_code and ln.unit_code not in UNIT_CODES:
            add(Issue("BAD_UNIT_CODE", "error", f"{f}.unit_code",
                      f"Line {i} unit '{ln.unit_code}' is not a UN/ECE Rec 20 unit code.", ""))
        cat = line_category(ln)
        if ln.vat_rate is None and cat in ZERO_CATEGORIES:
            ln.vat_rate = Decimal("0")
        if ln.vat_rate is None:
            add(Issue("MISSING_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} VAT rate is missing.",
                      f"Is line {i} standard-rated (5%), zero-rated (0%) or exempt?"))
            lines_ok = False
            continue
        if cat == "S" and ln.vat_rate != Decimal("5"):
            add(Issue("BAD_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} is standard-rated but shows {ln.vat_rate}% VAT; the UAE rate is 5%.",
                      f"Line {i} shows {ln.vat_rate}% VAT. Should it be 5%?"))
            vat_ok = False
        elif cat in ZERO_RATE_CATEGORIES and ln.vat_rate != 0:
            add(Issue("BAD_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} has VAT category {cat}, which carries 0% VAT, but shows {ln.vat_rate}%.",
                      f"Line {i}: should VAT be 0% (category {cat}) or 5%?"))
            vat_ok = False
        elif cat in SELF_ACCOUNTED and ln.vat_rate not in ALLOWED_VAT_RATES:
            add(Issue("BAD_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} ({cat}) shows {ln.vat_rate}% VAT; expected 5% or 0%.", ""))
            vat_ok = False
        elif cat not in ZERO_CATEGORIES | {"S"}:
            add(Issue("BAD_VAT_CATEGORY", "error", f"{f}.vat_category",
                      f"Line {i} VAT category '{cat}' is not used in the UAE.", ""))
        elif ln.vat_rate not in ALLOWED_VAT_RATES:
            add(Issue("BAD_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} VAT rate {ln.vat_rate}% is not a UAE rate (5% or 0%).",
                      f"Line {i} shows {ln.vat_rate}% VAT. Should it be 5%?"))
            vat_ok = False
        net = _r(ln.quantity * ln.unit_price + ln.adjustment)
        if ln.line_total is not None and abs(net - ln.line_total) > CENT:
            add(Issue("LINE_MATH_MISMATCH", "error", f"{f}.line_total",
                      f"Line {i}: {ln.quantity} x {ln.unit_price} = {net}, but invoice says {ln.line_total}.",
                      f"Line {i} total doesn't match qty x price. Which value is correct?"))
        net_sum += net
        key = (cat, ln.vat_rate)
        taxable[key] = taxable.get(key, Decimal("0")) + net

    # --- Totals (only meaningful if every line was computable) --------------
    if lines_ok and inv.lines:
        tol = CENT * len(inv.lines)  # allow per-line rounding drift in source documents
        for amount, cat, rate in inv.doc_adjustments:
            net_sum += amount
            taxable[(cat, rate)] = taxable.get((cat, rate), Decimal("0")) + amount
        # Official method: VAT per category on the category's taxable amount, rounded once.
        # Only standard-rated (S) supplies carry VAT charged by the seller.
        vat_sum = sum((_r(base * rate / 100) for (cat, rate), base in taxable.items() if cat == "S"),
                      Decimal("0"))
        gross = net_sum + vat_sum
        for code, stated, calc, label in (
            ("NET_TOTAL_MISMATCH", inv.stated_net_total, net_sum, "net total"),
            ("VAT_TOTAL_MISMATCH", inv.stated_vat_total, vat_sum, "VAT total"),
            ("GROSS_TOTAL_MISMATCH", inv.stated_gross_total, gross, "gross total"),
        ):
            if code != "NET_TOTAL_MISMATCH" and not vat_ok:
                continue
            if stated is not None and abs(_r(stated) - calc) > tol:
                add(Issue(code, "error", label.replace(" ", "_"),
                          f"Stated {label} {stated} != calculated {calc}.",
                          f"The {label} looks wrong ({stated} vs {calc}). Can you confirm?"))
    return issues


def readiness_score(issues: list[Issue]) -> int:
    """0-100. Each error costs 15, each warning 5. Simple and explainable to judges."""
    penalty = sum(15 if i.severity == "error" else 5 for i in issues)
    return max(0, 100 - penalty)
