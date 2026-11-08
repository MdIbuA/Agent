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
                                            extractor=d.get("extractor"))

    def _save(self, rec: Record) -> None:  # call with the lock held
        if self._db is None:
            return
        body = json.dumps({"invoice": invoice_to_dict(rec.invoice), "source": rec.source, "extractor": rec.extractor,
                           "unconfirmed": sorted(rec.unconfirmed), "answered": rec.answered})
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
            return serialize(rec)

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
