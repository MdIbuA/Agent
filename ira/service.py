"""Application service used by the web API: holds a workspace of invoices in memory,
applies the owner's answers, and re-validates after every change.

Kept separate from the HTTP layer so it is unit-testable without a server.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .agent import IMAGE_SUFFIXES, _FIELD_SETTERS, document_extract
from .models import Invoice, invoice_from_dict, invoice_to_dict, to_decimal
from .rule_extract import normalize_date
from .ubl import to_ubl_xml
from .validate import Issue, readiness_score, validate

# Owner-answerable fields beyond the header/party setters in agent.py.
_EXTRA_SETTERS = {
    "gross_total": lambda inv, v: setattr(inv, "stated_gross_total", to_decimal(v)),
}
# short name -> (answerable field, label, getter)
_UNCONFIRMED = {
    "invoice_number": ("invoice_number", "invoice number", lambda i: i.invoice_number),
    "date": ("issue_date", "issue date", lambda i: i.issue_date),
    "due_date": ("due_date", "due date", lambda i: i.due_date),
    "total": ("gross_total", "total", lambda i: i.stated_gross_total),
    "company": ("seller.name", "seller name", lambda i: i.seller.name),
    "seller_trn": ("seller.trn", "seller TRN", lambda i: i.seller.trn),
    "buyer_trn": ("buyer.trn", "buyer TRN", lambda i: i.buyer.trn),
    "buyer_name": ("buyer.name", "buyer name", lambda i: i.buyer.name),
    "seller_licence": ("seller.legal_id", "seller's trade licence (from the official Ajman register)",
                       lambda i: i.seller.legal_id),
}
_UNCONFIRMED_FIELD = {k: v[0] for k, v in _UNCONFIRMED.items()}


@dataclass
class Record:
    id: str
    invoice: Invoice
    source: str                      # "sample" | "json" | "xml" | "pdf" | "scan"
    unconfirmed: set[str] = field(default_factory=set)  # OCR fields awaiting owner confirmation
    answered: dict[str, str] = field(default_factory=dict)
    extractor: str | None = None     # "rules", "rules + AI", "rules (AI unavailable)"
    learned: dict[str, str] = field(default_factory=dict)  # field -> invoice id the answer came from

    def issues(self) -> list[Issue]:
        issues = validate(self.invoice)
        order = list(_UNCONFIRMED)
        for f in sorted(self.unconfirmed, key=order.index):
            fld, label, get = _UNCONFIRMED[f]
            value = get(self.invoice)
            if value in (None, ""):
                continue  # nothing was read; the validator already asks for it if required
            if f in ("date", "due_date"):
                from datetime import date as _d
                try:
                    d = _d.fromisoformat(str(value))
                    value = f"{d.day} {d:%b %Y}"  # portable (no %-d, which fails on Windows)
                except ValueError:
                    pass
            elif f == "total":
                value = f"{self.invoice.currency or 'AED'} {value}"
            # Hide a validator error on the same field: confirming or correcting covers both.
            issues = [i for i in issues if i.field != fld]
            issues.append(Issue(f"UNCONFIRMED_{f.upper()}", "warning", fld,
                                f"The {label} was read from a scan and needs a quick check.",
                                f"Confirm the {label}: is it {value}?"))
        return issues


def _money(x: Decimal | None) -> str | None:
    return None if x is None else f"{x:.2f}"


def _answerable(field_name: str) -> bool:
    return field_name in _FIELD_SETTERS or field_name in _EXTRA_SETTERS


def serialize(rec: Record) -> dict:
    inv = rec.invoice
    issues = rec.issues()
    errors = [i for i in issues if i.severity == "error"]
    status = "ready" if not issues else ("review" if not errors else "blocked")
    net = sum(((l.quantity or 0) * (l.unit_price or 0) for l in inv.lines), Decimal("0"))
    return {
        "id": rec.id,
        "source": rec.source,
        "extractor": rec.extractor,
        "learned": sorted(rec.learned),
        "file": inv.source_file,
        "invoiceNumber": inv.invoice_number,
        "issueDate": inv.issue_date,
        "currency": inv.currency or "AED",
        "seller": {"name": inv.seller.name, "trn": inv.seller.trn, "address": inv.seller.address},
        "buyer": {"name": inv.buyer.name, "trn": inv.buyer.trn, "address": inv.buyer.address},
        "lines": [{"description": l.description, "quantity": str(l.quantity) if l.quantity is not None else None,
                   "unitPrice": _money(l.unit_price), "vatRate": str(l.vat_rate) if l.vat_rate is not None else None,
                   "lineTotal": _money(l.line_total)} for l in inv.lines],
        "totals": {"net": _money(inv.stated_net_total) or (_money(net) if inv.lines else None),
                   "vat": _money(inv.stated_vat_total), "gross": _money(inv.stated_gross_total)},
        "status": status,
        "readyForAsp": not errors,
        "score": readiness_score(issues),
        "issues": [{"code": i.code, "severity": i.severity, "field": i.field, "message": i.message,
                    "question": i.question, "answerable": _answerable(i.field) or i.code.startswith("UNCONFIRMED")}
                   for i in issues],
    }


def party_key(p) -> str | None:
    """Identity of a business across invoices: its TRN when valid, else its normalised name."""
    import re as _re
    trn = _re.sub(r"\D", "", p.trn or "")
    if len(trn) == 15:
        return "T" + trn
    name = _re.sub(r"[^A-Z0-9]", "", (p.name or "").upper())
    return "N" + name if len(name) >= 4 else None


class Workspace:
    """Thread-safe store. In memory by default; pass db_path to persist to SQLite so work
    survives restarts. Each invoice is one row of JSON (invoice + confirmation state)."""

    def __init__(self, db_path: str | Path | None = None):
        self._lock = threading.Lock()
        self._records: dict[str, Record] = {}
        self._db = None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, seq INTEGER, body TEXT)")
            for rid, body in self._db.execute("SELECT id, body FROM invoices ORDER BY seq"):
                d = json.loads(body)
                self._records[rid] = Record(id=rid, invoice=invoice_from_dict(d["invoice"]), source=d["source"],
                                            unconfirmed=set(d["unconfirmed"]), answered=d["answered"],
                                            extractor=d.get("extractor"), learned=d.get("learned", {}))

    def _save(self, rec: Record) -> None:  # call with the lock held
        if self._db is None:
            return
        body = json.dumps({"invoice": invoice_to_dict(rec.invoice), "source": rec.source, "extractor": rec.extractor,
                           "unconfirmed": sorted(rec.unconfirmed), "answered": rec.answered, "learned": rec.learned})
        self._db.execute("INSERT INTO invoices (id, seq, body) VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 "
                         "FROM invoices), ?) ON CONFLICT(id) DO UPDATE SET body = excluded.body", (rec.id, body))
        self._db.commit()

    def _forget(self, rid: str | None) -> None:
        if self._db is None:
            return
        if rid is None:
            self._db.execute("DELETE FROM invoices")
        else:
            self._db.execute("DELETE FROM invoices WHERE id = ?", (rid,))
        self._db.commit()

    # --- ingest -------------------------------------------------------------
    def add_dicts(self, items: list[dict], source: str) -> list[dict]:
        out = []
        with self._lock:
            for d in items:
                rec = Record(id=uuid.uuid4().hex[:10], invoice=invoice_from_dict(d), source=source,
                             unconfirmed=set(d.get("_unconfirmed", [])), extractor=d.get("_extractor"))
                self._records[rec.id] = rec
                self._save(rec)
                out.append(serialize(rec))
        return out

    def add_scan(self, path: Path, engine: str | None) -> dict:
        if path.suffix.lower() not in IMAGE_SUFFIXES | {".pdf"}:
            raise ValueError(f"Unsupported file type: {path.suffix}")
        d = document_extract(path, engine)
        source = "pdf" if d["_via"] == "text-layer" else "scan"
        return self.add_dicts([d], source=source)[0]

    # --- queries ------------------------------------------------------------
    def list(self) -> list[dict]:
        with self._lock:
            return [serialize(r) for r in self._records.values()]

    def get(self, rid: str) -> Record:
        with self._lock:
            if rid not in self._records:
                raise KeyError(rid)
            return self._records[rid]

    def summary(self) -> dict:
        items = self.list()
        n = len(items)
        ready = sum(i["status"] == "ready" for i in items)
        return {
            "invoices": n,
            "ready": ready,
            "review": sum(i["status"] == "review" for i in items),
            "blocked": sum(i["status"] == "blocked" for i in items),
            "readinessPct": round(100 * ready / n, 1) if n else 0.0,
            "avgScore": round(sum(i["score"] for i in items) / n, 1) if n else 0.0,
            "openQuestions": sum(1 for i in items for q in i["issues"] if q["answerable"]),
        }

    # --- commands -----------------------------------------------------------
    def answer(self, rid: str, field_name: str, value: str) -> dict:
        value = (value or "").strip()
        if not value:
            raise ValueError("Answer cannot be empty.")
        with self._lock:
            rec = self._records.get(rid)
            if rec is None:
                raise KeyError(rid)
            setter = _FIELD_SETTERS.get(field_name) or _EXTRA_SETTERS.get(field_name)
            if setter is None:
                raise ValueError(f"Field '{field_name}' can't be edited here.")
            if field_name in ("issue_date", "due_date"):  # accept 25/12/2026, 25 Dec 2026, ISO
                iso = normalize_date(value)
                if not iso:
                    raise ValueError("Couldn't read that date. Try a format like 25/12/2026.")
                value = iso
            if field_name == "gross_total" and to_decimal(value) is None:
                raise ValueError("Enter an amount like 1250.00.")
            setter(rec.invoice, value)
            rec.answered[field_name] = value
            for short, fld in _UNCONFIRMED_FIELD.items():  # an explicit answer confirms OCR fields
                if fld == field_name:
                    rec.unconfirmed.discard(short)
            self._save(rec)
            applied = self._propagate(rec, field_name, value, setter)
            return {**serialize(rec), "appliedTo": applied}

    # Party facts that are the same on every invoice with that party. Payment terms, dates and
    # amounts are per-invoice and are never copied.
    _PARTY_FIELDS = {"seller.legal_id", "seller.legal_authority", "seller.emirate", "seller.address",
                     "seller.trn", "buyer.trn", "buyer.emirate", "buyer.address"}

    def _propagate(self, src: Record, field_name: str, value: str, setter) -> list[str]:
        """Agent memory: apply a party fact to the other invoices with the same party, only where
        that field is still empty (never overwrites). Call with the lock held."""
        if field_name not in self._PARTY_FIELDS:
            return []
        role = field_name.split(".")[0]
        key = party_key(getattr(src.invoice, role))
        if not key:
            return []
        attr = field_name.split(".")[1]
        applied = []
        for rec in self._records.values():
            party = getattr(rec.invoice, role)
            if rec.id == src.id or party_key(party) != key or getattr(party, attr) not in (None, ""):
                continue
            setter(rec.invoice, value)
            rec.learned[field_name] = src.id
            self._save(rec)
            applied.append(rec.id)
        return applied

    def confirm(self, rid: str, field_name: str) -> dict:
        """Owner says the OCR value is correct as read."""
        with self._lock:
            rec = self._records.get(rid)
            if rec is None:
                raise KeyError(rid)
            for short, fld in _UNCONFIRMED_FIELD.items():
                if fld == field_name:
                    rec.unconfirmed.discard(short)
            self._save(rec)
            return serialize(rec)

    def delete(self, rid: str) -> None:
        with self._lock:
            self._records.pop(rid, None)
            self._forget(rid)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._forget(None)

    def xml(self, rid: str) -> str:
        rec = self.get(rid)
        if any(i.severity == "error" for i in rec.issues()):
            raise ValueError("Resolve all blocking issues before exporting XML.")
        if not rec.invoice.lines:
            raise ValueError("Invoice has no line items to export.")
        return to_ubl_xml(rec.invoice)


# ---- Agent actions: customer requests and the readiness report -------------------------

_BUYER_NEEDS = {  # buyer fields the owner usually has to ask the customer for
    "buyer.trn": ("your 15-digit Tax Registration Number (TRN)", "رقم التسجيل الضريبي المكوّن من 15 رقماً"),
    "buyer.address": ("your full address", "العنوان الكامل"),
    "buyer.emirate": ("the emirate of your address", "الإمارة التي يقع فيها عنوانكم"),
    "buyer.name": ("your registered legal name", "الاسم القانوني المسجّل"),
}


def outreach(ws: "Workspace") -> list[dict]:
    """One draft message per customer, covering every invoice that needs their details."""
    groups: dict[str, dict] = {}
    with ws._lock:
        records = list(ws._records.values())
    for rec in records:
        issues = rec.issues()
        needs = [i.field for i in issues if i.field in _BUYER_NEEDS and i.severity == "error"]
        if not needs:
            continue
        b = rec.invoice.buyer
        key = party_key(b) or f"R{rec.id}"
        g = groups.setdefault(key, {"buyer": b.name, "buyerTrn": b.trn, "invoices": [], "needs": [],
                                    "seller": rec.invoice.seller.name})
        g["invoices"].append(rec.invoice.invoice_number or rec.invoice.source_file or rec.id)
        g["needs"] += [n for n in needs if n not in g["needs"]]
    out = []
    for g in groups.values():
        name = g["buyer"] or "Customer"
        invs = ", ".join(g["invoices"])
        en_items = "\n".join(f"  • {_BUYER_NEEDS[n][0]}" for n in g["needs"])
        ar_items = "\n".join(f"  • {_BUYER_NEEDS[n][1]}" for n in g["needs"])
        sign = g["seller"] or ""
        g["messageEn"] = (f"Dear {name} team,\n\nThe UAE is moving to mandatory e-invoicing (PINT AE). To issue "
                          f"invoice{'s' if len(g['invoices']) > 1 else ''} {invs} correctly, please send us:\n"
                          f"{en_items}\n\nThank you,\n{sign}").strip()
        # \u2066…\u2069 isolate Latin names and invoice numbers so they don't scramble inside Arabic text.
        g["messageAr"] = (f"السادة \u2068{name}\u2069 المحترمين،\n\nتنتقل دولة الإمارات إلى الفوترة الإلكترونية الإلزامية. "
                          f"لإصدار الفواتير التالية بشكل صحيح:\n\u2066{invs}\u2069\n\nيرجى تزويدنا بما يلي:\n{ar_items}\n\n"
                          f"مع الشكر،\n\u2068{sign}\u2069").strip()
        out.append(g)
    return sorted(out, key=lambda g: -len(g["invoices"]))


# Published penalty amounts (Ministerial Decisions on e-invoicing, as reported in 2026):
# AED 100 per invoice not issued/transmitted electronically on time, capped at AED 5,000 per
# month. Indicative only -- the agent states this and links the source in BENCHMARK/README.
PENALTY_PER_INVOICE = 100
PENALTY_MONTHLY_CAP = 5000

_ISSUE_LABELS = {
    "MISSING_BUYER_TRN": "Buyer TRN missing", "BAD_BUYER_TRN": "Buyer TRN invalid",
    "BAD_SELLER_TRN": "Seller TRN invalid", "MISSING_SELLER_TRN": "Seller TRN missing",
    "MISSING_DUE_DATE": "Due date missing", "MISSING_PAYMENT_MEANS": "Payment method missing",
    "MISSING_SELLER_LICENSE": "Trade licence missing", "MISSING_SELLER_LICENSE_AUTHORITY": "Licence authority missing",
    "MISSING_BUYER_EMIRATE": "Buyer emirate missing", "MISSING_SELLER_EMIRATE": "Seller emirate missing",
    "MISSING_BUYER_ADDRESS": "Buyer address missing", "BAD_VAT_RATE": "Wrong VAT rate",
    "VAT_TOTAL_MISMATCH": "VAT total doesn't add up", "GROSS_TOTAL_MISMATCH": "Total doesn't add up",
    "LINE_MATH_MISMATCH": "Line amount doesn't add up", "MISSING_INVOICE_NUMBER": "Invoice number missing",
    "BAD_ISSUE_DATE": "Invalid issue date", "NO_LINES": "No line items",
}


def report(ws: "Workspace") -> dict:
    from collections import Counter
    items = ws.list()
    with ws._lock:
        recs = {r.id: r for r in ws._records.values()}
    blocked = [i for i in items if not i["readyForAsp"]]
    by_month = Counter((i["issueDate"] or "unknown")[:7] for i in blocked)
    exposure = sum(min(PENALTY_PER_INVOICE * n, PENALTY_MONTHLY_CAP) for n in by_month.values())
    issue_counts = Counter()
    for i in blocked:
        for code in {q["code"] for q in i["issues"] if q["severity"] == "error"}:
            issue_counts[code] += 1
    learned = sum(len(r.learned) for r in recs.values())
    return {
        "summary": ws.summary(),
        "notReady": len(blocked),
        "exposureAed": exposure,
        "exposureByMonth": dict(sorted(by_month.items())),
        "penaltyBasis": {"perInvoice": PENALTY_PER_INVOICE, "monthlyCap": PENALTY_MONTHLY_CAP},
        "topIssues": [{"code": c, "label": _ISSUE_LABELS.get(c, c.replace("_", " ").title()), "invoices": n}
                      for c, n in issue_counts.most_common(8)],
        "answersReusedByAgent": learned,
        "customerRequests": len(outreach(ws)),
    }
