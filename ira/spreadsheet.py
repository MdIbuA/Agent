"""Import an SME's invoice register from Excel (.xlsx) or CSV.

Small businesses keep invoices in spreadsheets with their own column names, in English or
Arabic, sometimes with a title above the header row. This module finds the header row, maps
columns by meaning, and groups rows into invoices:

- one row per LINE (rows sharing an invoice number become one invoice), or
- one row per INVOICE (only net / VAT / total amounts): a single summary line is created.

The seller is the business itself, so seller details come from the business profile, not
from the sheet. Every mapping decision is returned so the UI can show what was understood.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .rule_extract import normalize_date

# canonical field -> header synonyms (lower-case, compared after normalising spaces/punctuation)
SYNONYMS: dict[str, list[str]] = {
    "invoice_number": ["invoice no", "invoice number", "invoice #", "inv no", "inv #", "inv", "bill no",
                       "bill number", "document no", "voucher no", "invoice", "رقم الفاتورة", "رقم الفاتوره",
                       "الفاتورة"],
    "date": ["date", "invoice date", "issue date", "inv date", "bill date", "التاريخ", "تاريخ الفاتورة",
             "تاريخ الإصدار"],
    "due_date": ["due date", "due", "payment due", "due on", "تاريخ الاستحقاق"],
    "customer": ["customer", "customer name", "client", "client name", "buyer", "bill to", "party",
                 "party name", "name", "العميل", "اسم العميل", "المشتري"],
    "customer_trn": ["customer trn", "trn", "buyer trn", "client trn", "vat no", "vat number", "tax no",
                     "trn no", "الرقم الضريبي", "رقم التسجيل الضريبي"],
    "customer_address": ["address", "customer address", "client address", "العنوان", "عنوان العميل"],
    "description": ["description", "item", "item description", "product", "service", "particulars",
                    "details", "البيان", "الوصف", "الصنف"],
    "quantity": ["qty", "quantity", "units", "الكمية", "العدد"],
    "unit_price": ["rate", "price", "unit price", "unit rate", "سعر الوحدة", "السعر"],
    "vat_rate": ["vat %", "vat rate", "tax %", "tax rate", "vat percent", "نسبة الضريبة"],
    "amount": ["amount", "line total", "net", "net amount", "taxable amount", "amount excl vat",
               "subtotal", "المبلغ", "المبلغ قبل الضريبة", "الصافي"],
    "vat_amount": ["vat", "vat amount", "tax", "tax amount", "ضريبة القيمة المضافة", "الضريبة", "قيمة الضريبة"],
    "total": ["total", "gross", "grand total", "total incl vat", "amount incl vat", "invoice total",
              "الإجمالي", "المجموع"],
    "payment": ["payment", "payment method", "payment mode", "paid by", "طريقة الدفع"],
}

MAX_ROWS = 20000


def _norm(h) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"[_\-./:()\[\]]+", " ", s)
    s = s.replace("#", " # ").replace("%", " % ")
    return " ".join(s.split())


_INDEX = {_norm(syn): field for field, syns in SYNONYMS.items() for syn in syns}


def _match(header) -> str | None:
    h = _norm(header)
    if not h:
        return None
    if h in _INDEX:
        return _INDEX[h]
    # contains a known synonym as whole words, e.g. "Customer Name (as per licence)"
    best = None
    for syn, field in _INDEX.items():
        if len(syn) >= 3 and re.search(rf"(^| ){re.escape(syn)}( |$)", h):
            if best is None or len(syn) > len(best[0]):
                best = (syn, field)
    return best[1] if best else None


def read_rows(data: bytes, filename: str) -> list[list]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
            if len(rows) > MAX_ROWS:
                raise ValueError(f"Sheet has more than {MAX_ROWS:,} rows.")
        return rows
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)][: MAX_ROWS + 1]


def _find_header(rows: list[list]) -> tuple[int, dict[int, str]]:
    best = (-1, {})
    for i, row in enumerate(rows[:15]):
        mapping = {}
        for j, cell in enumerate(row):
            f = _match(cell)
            if f and f not in mapping.values():
                mapping[j] = f
        if len(mapping) > len(best[1]):
            best = (i, mapping)
    if len(best[1]) < 3 or "invoice_number" not in best[1].values():
        raise ValueError("Couldn't find a header row with an invoice-number column and at least 3 known columns.")
    return best


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return Decimal(s) if s not in ("", "-", ".") else None
    except InvalidOperation:
        return None


def _date(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return normalize_date(str(v)) if v not in (None, "") else None


def _rate(v) -> str | None:
    d = _dec(v)
    if d is None:
        return None
    if Decimal("0") < d < 1:  # 0.05 written as a fraction
        d *= 100
    return str(d.normalize())


def parse_register(data: bytes, filename: str) -> tuple[list[dict], dict]:
    """Return (invoice dicts, info) where info explains the column mapping and any skipped rows."""
    rows = read_rows(data, filename)
    h, mapping = _find_header(rows)
    headers = rows[h]
    invoices: dict[str, dict] = {}
    skipped = 0
    for r in rows[h + 1:]:
        cell = {f: (r[j] if j < len(r) else None) for j, f in mapping.items()}
        num = str(cell.get("invoice_number") or "").strip()
        if num.endswith(".0") and num[:-2].isdigit():
            num = num[:-2]
        if not num or _norm(num) in ("total", "grand total", "الإجمالي"):
            skipped += any(c not in (None, "") for c in r)
            continue
        inv = invoices.setdefault(num, {
            "invoice_number": num, "issue_date": _date(cell.get("date")), "due_date": _date(cell.get("due_date")),
            "payment_means": None, "seller": {},
            "buyer": {"name": (str(cell.get("customer")).strip() or None) if cell.get("customer") else None,
                      "trn": re.sub(r"\D", "", str(cell.get("customer_trn") or "")) or None,
                      "address": (str(cell.get("customer_address")).strip() or None) if cell.get("customer_address") else None},
            "lines": [], "_payment_text": cell.get("payment"),
            "net_total": Decimal("0"), "vat_total": Decimal("0"), "gross_total": Decimal("0"), "_has": set(),
        })
        if inv["buyer"]["address"]:
            inv["buyer"]["city"] = inv["buyer"]["address"].split(",")[-1].strip()
        qty, price, amount = _dec(cell.get("quantity")), _dec(cell.get("unit_price")), _dec(cell.get("amount"))
        vat_amt, total, rate = _dec(cell.get("vat_amount")), _dec(cell.get("total")), _rate(cell.get("vat_rate"))
        if amount is None and qty is not None and price is not None:
            amount = (qty * price).quantize(Decimal("0.01"))
        if amount is None and total is not None and vat_amt is not None:
            amount = total - vat_amt
        if rate is None and amount and vat_amt is not None:
            rate = str((vat_amt / amount * 100).quantize(Decimal("1")))
        if qty is None and price is None and amount is not None:
            qty, price = Decimal("1"), amount  # one row per invoice: a single summary line
        desc = cell.get("description") or ("Invoice total" if "description" not in mapping.values() else None)
        if amount is not None or desc:
            inv["lines"].append({"description": str(desc).strip() if desc else None,
                                 "quantity": str(qty) if qty is not None else None,
                                 "unit_price": str(price) if price is not None else None,
                                 "vat_rate": rate, "line_total": str(amount) if amount is not None else None})
        for key, v in (("net_total", amount), ("vat_total", vat_amt), ("gross_total", total)):
            if v is not None:
                inv[key] += v
                inv["_has"].add(key)
    out = []
    from .agent import parse_payment_means
    for inv in invoices.values():
        has = inv.pop("_has")
        for key in ("net_total", "vat_total", "gross_total"):
            inv[key] = str(inv[key]) if key in has else None
        text = inv.pop("_payment_text")
        if text:
            try:
                inv["payment_means"] = parse_payment_means(str(text))
            except ValueError:
                pass
        inv["source_file"] = filename
        out.append(inv)
    info = {"headerRow": h + 1, "invoices": len(out), "skippedRows": skipped,
            "columns": {str(headers[j]): f for j, f in mapping.items()},
            "unmapped": [str(c) for j, c in enumerate(headers) if c not in (None, "") and j not in mapping]}
    return out, info
