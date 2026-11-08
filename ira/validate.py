"""Deterministic validation. The LLM never decides compliance -- this module does.

Rule set is a CORE SUBSET for the MVP. Before submission, map every rule to the
official PINT-AE data dictionary / FTA specification and extend the list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Invoice

ALLOWED_VAT_RATES = {Decimal("5"), Decimal("0")}
CENT = Decimal("0.01")
TRN_RE = re.compile(r"^\d{15}$")


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
    if inv.currency != "AED":
        add(Issue("NON_AED_CURRENCY", "warning", "currency",
                  f"Currency is {inv.currency}; VAT amounts must also be reported in AED.",
                  "What exchange rate to AED applies to this invoice?"))

    # --- Parties ------------------------------------------------------------
    for role, party in (("seller", inv.seller), ("buyer", inv.buyer)):
        if not party.name:
            add(Issue(f"MISSING_{role.upper()}_NAME", "error", f"{role}.name",
                      f"{role.title()} legal name is missing.", f"What is the {role}'s legal name?"))
        trn = normalize_trn(party.trn)
        if not trn:
            add(Issue(f"MISSING_{role.upper()}_TRN", "error", f"{role}.trn",
                      f"{role.title()} TRN is missing.",
                      f"What is the {role}'s 15-digit Tax Registration Number?"))
        elif not TRN_RE.match(trn):
            add(Issue(f"BAD_{role.upper()}_TRN", "error", f"{role}.trn",
                      f"{role.title()} TRN '{party.trn}' is not 15 digits.",
                      f"Please re-check the {role}'s TRN. It should be exactly 15 digits."))
        if not party.address:
            add(Issue(f"MISSING_{role.upper()}_ADDRESS", "error", f"{role}.address",
                      f"{role.title()} address is missing.", f"What is the {role}'s address?"))
    s_trn, b_trn = normalize_trn(inv.seller.trn), normalize_trn(inv.buyer.trn)
    if s_trn and s_trn == b_trn:
        add(Issue("SAME_TRN", "error", "buyer.trn",
                  "Seller and buyer have the same TRN.", "Which TRN belongs to the buyer?"))

    # --- Lines --------------------------------------------------------------
    if not inv.lines:
        add(Issue("NO_LINES", "error", "lines", "Invoice has no line items.",
                  "What goods or services does this invoice cover?"))

    net_sum = Decimal("0")
    vat_sum = Decimal("0")
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
        if ln.vat_rate is None:
            add(Issue("MISSING_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} VAT rate is missing.",
                      f"Is line {i} standard-rated (5%), zero-rated (0%) or exempt?"))
            lines_ok = False
            continue
        if ln.vat_rate not in ALLOWED_VAT_RATES:
            add(Issue("BAD_VAT_RATE", "error", f"{f}.vat_rate",
                      f"Line {i} VAT rate {ln.vat_rate}% is not a UAE rate (5% or 0%).",
                      f"Line {i} shows {ln.vat_rate}% VAT. Should it be 5%?"))
            vat_ok = False
        net = _r(ln.quantity * ln.unit_price)
        if ln.line_total is not None and abs(net - ln.line_total) > CENT:
            add(Issue("LINE_MATH_MISMATCH", "error", f"{f}.line_total",
                      f"Line {i}: {ln.quantity} x {ln.unit_price} = {net}, but invoice says {ln.line_total}.",
                      f"Line {i} total doesn't match qty x price. Which value is correct?"))
        net_sum += net
        vat_sum += _r(net * ln.vat_rate / 100)

    # --- Totals (only meaningful if every line was computable) --------------
    if lines_ok and inv.lines:
        tol = CENT * len(inv.lines)  # allow per-line rounding drift
        gross = net_sum + vat_sum
        for code, stated, calc, label in (
            ("NET_TOTAL_MISMATCH", inv.stated_net_total, net_sum, "net total"),
            ("VAT_TOTAL_MISMATCH", inv.stated_vat_total, vat_sum, "VAT total"),
            ("GROSS_TOTAL_MISMATCH", inv.stated_gross_total, gross, "gross total"),
        ):
            if code != "NET_TOTAL_MISMATCH" and not vat_ok:
                continue
            if stated is not None and abs(stated - calc) > tol:
                add(Issue(code, "error", label.replace(" ", "_"),
                          f"Stated {label} {stated} != calculated {calc}.",
                          f"The {label} looks wrong ({stated} vs {calc}). Can you confirm?"))
    return issues


def readiness_score(issues: list[Issue]) -> int:
    """0-100. Each error costs 15, each warning 5. Simple and explainable to judges."""
    penalty = sum(15 if i.severity == "error" else 5 for i in issues)
    return max(0, 100 - penalty)
