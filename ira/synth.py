"""Synthetic, messy SME invoices with KNOWN injected faults.

Why: free LLM tiers may log data, so never use real customer invoices. And because
we know exactly which faults were injected, we can measure the agent's accuracy --
the single number that makes judges trust a compliance product.
"""
from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

SELLERS = [  # (name, address, licensing authority) -- fictional businesses
    ("Al Noor Building Materials LLC", "Deira, Dubai", "Dubai Department of Economy and Tourism"),
    ("Blue Dhow Marine Supplies FZE", "Jebel Ali Free Zone, Dubai", "Jebel Ali Free Zone Authority"),
    ("Sahara Spice Trading LLC", "Al Ras, Dubai", "Dubai Department of Economy and Tourism"),
    ("Falcon Tech Repairs", "Al Nahda, Sharjah", "Sharjah Economic Development Department"),
]
BUYERS = [
    ("Gulf Horizon Contracting LLC", "Business Bay, Dubai"),
    ("Palm Fresh Restaurants LLC", "Al Khalidiyah, Abu Dhabi"),
    ("Emirates Cold Chain Logistics", "Industrial Area 4, Sharjah"),
]
ITEMS = [
    ("Cement bag 50kg", "18.50"), ("Steel rebar 12mm (ton)", "2450.00"),
    ("Marine rope 20m", "135.00"), ("Saffron 100g", "420.00"),
    ("Laptop screen replacement", "380.00"), ("Delivery charge", "75.00"),
]

# Each fault mutates the clean dict and returns the validator code it should trigger.
def _drop_buyer_trn(d):  d["buyer"]["trn"] = None; return "MISSING_BUYER_TRN"
def _short_seller_trn(d): d["seller"]["trn"] = d["seller"]["trn"][:12]; return "BAD_SELLER_TRN"
def _bad_vat(d):         d["lines"][0]["vat_rate"] = "10"; return "BAD_VAT_RATE"
def _line_math(d):
    d["lines"][0]["line_total"] = str(Decimal(d["lines"][0]["line_total"]) + 10); return "LINE_MATH_MISMATCH"
def _drop_number(d):     d["invoice_number"] = None; return "MISSING_INVOICE_NUMBER"
def _bad_date(d):        d["issue_date"] = "31/02/2026"; return "BAD_ISSUE_DATE"
def _vat_total(d):       d["vat_total"] = str(Decimal(d["vat_total"]) + 5); return "VAT_TOTAL_MISMATCH"
def _drop_buyer_addr(d): d["buyer"]["address"] = None; return "MISSING_BUYER_ADDRESS"
def _drop_due_date(d):   d["due_date"] = None; return "MISSING_DUE_DATE"

FAULTS = [_drop_buyer_trn, _short_seller_trn, _bad_vat, _line_math,
          _drop_number, _bad_date, _vat_total, _drop_buyer_addr, _drop_due_date]


def _trn(rng: random.Random) -> str:
    """Valid UAE TRN shape (PINT-AE ibr-132-ae): 15 digits, starts with 1, ends with 03."""
    return "100" + "".join(rng.choice("0123456789") for _ in range(10)) + "03"


def clean_invoice(rng: random.Random, n: int) -> dict:
    s, b = rng.choice(SELLERS), rng.choice(BUYERS)
    lines, net, vat = [], Decimal("0"), Decimal("0")
    for desc, price in rng.sample(ITEMS, rng.randint(1, 4)):
        qty = Decimal(rng.randint(1, 20))
        rate = Decimal("5") if rng.random() > 0.1 else Decimal("0")
        lt = (qty * Decimal(price)).quantize(Decimal("0.01"))
        net += lt
        vat += (lt * rate / 100).quantize(Decimal("0.01"))
        lines.append({"description": desc, "quantity": str(qty), "unit_price": price,
                      "vat_rate": str(rate), "line_total": str(lt)})
    month, day = rng.randint(1, 10), rng.randint(1, 28)
    return {
        "invoice_number": f"INV-2026-{n:04d}",
        "issue_date": f"2026-{month:02d}-{day:02d}",
        "due_date": f"2026-{month + 1:02d}-{day:02d}",
        "payment_means": rng.choice(["30", "30", "30", "20", "10", "54"]),
        "currency": "AED",
        "seller": {"name": s[0], "trn": _trn(rng), "address": s[1], "city": s[1].split(", ")[-1],
                   "legal_id": f"{rng.randint(100000, 999999)}", "legal_id_type": "TL", "legal_authority": s[2]},
        "buyer": {"name": b[0], "trn": _trn(rng), "address": b[1], "city": b[1].split(", ")[-1]},
        "lines": lines,
        "net_total": str(net), "vat_total": str(vat), "gross_total": str(net + vat),
    }


def credit_note_for(inv: dict, rng: random.Random, n: int) -> dict:
    """A credit note returning part of the first line of `inv` (e.g. damaged goods)."""
    line = dict(inv["lines"][0])
    qty = Decimal(max(1, int(Decimal(line["quantity"])) // 2))
    net = (qty * Decimal(line["unit_price"])).quantize(Decimal("0.01"))
    vat = (net * Decimal(line["vat_rate"]) / 100).quantize(Decimal("0.01"))
    line.update(quantity=str(qty), line_total=str(net))
    return {**inv, "invoice_number": f"CN-2026-{n:04d}", "invoice_type": "381", "due_date": None,
            "payment_means": None, "preceding_invoice": inv["invoice_number"],
            "preceding_invoice_date": inv["issue_date"], "credit_reason": "DL8.61.1.D", "lines": [line],
            "net_total": str(net), "vat_total": str(vat), "gross_total": str(net + vat)}


def generate(count: int = 50, seed: int = 42, clean_ratio: float = 0.3) -> list[dict]:
    """Return invoices each tagged with `_expected` = set of fault codes injected."""
    rng = random.Random(seed)
    out = []
    for n in range(1, count + 1):
        d = clean_invoice(rng, n)
        expected = []
        if rng.random() > clean_ratio:
            for fault in rng.sample(FAULTS, rng.randint(1, 3)):
                expected.append(fault(d))
        d["_expected"] = sorted(expected)
        d["source_file"] = f"synthetic_{n:04d}.json"
        out.append(d)
    return out


if __name__ == "__main__":
    path = Path(__file__).resolve().parent.parent / "data" / "synthetic_invoices.json"
    path.write_text(json.dumps(generate(), indent=2))
    print(f"wrote {path}")
