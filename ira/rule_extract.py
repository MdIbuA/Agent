"""Zero-cost, offline extractor for OCR text (no LLM, no API key).

Role in the agent: (1) the free fallback when no LLM key is set or the free tier is
rate-limited, and (2) a cross-check -- if the LLM and the rules disagree on the total
or date, the agent asks the owner instead of guessing.

Benchmarked on real scanned receipts (SROIE) by benchmarks/sroie_bench.py.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# Dates. Same separator twice (backreference) and no letter/dash glued on the left, so
# product codes (HD03-04-06) and IDs (SP-NULL-18/06/04) are not read as dates.
_L = r"(?<![\w\-/.#])"
_NUM_DATE = re.compile(_L + r"(\d{1,2})([/\-.])(\d{1,2})\2(\d{4}|\d{2})(?![\d/\-])")
_ISO_DATE = re.compile(_L + r"(20\d{2})([/\-.])(\d{1,2})\2(\d{1,2})(?![\d/\-])")
_COMPACT = re.compile(r"DATE[^0-9\n]{0,12}(20\d{2})(\d{2})(\d{2})(?!\d)")
_TXT_DATE = re.compile(_L + r"(\d{1,2})[\s\-/]*([A-Z]{3})[A-Z]*[\s\-/,]*(\d{4}|\d{2})(?!\d)")
_TXT_DATE_US = re.compile(r"\b([A-Z]{3})[A-Z]*[\s\-/.]*(\d{1,2})[\s,]+(\d{4})(?!\d)")
# Modern OCR (RapidOCR) glues tokens: "25/12/20188:13:39PM", "100021911/03/2018".
_GLUED_TIME = re.compile(r"([/\-.]\d{4})(\d{1,2}:\d{2})")
_NUM_DATE_GLUED = re.compile(r"(?<=\d{3})(\d{1,2})([/\-.])(\d{1,2})\2(\d{4})(?![\d/\-])")
# Date glued straight onto its label by OCR: "DateofIssue05/01/2026", "DueOn03/07/2026".
_LABELLED_DATE = re.compile(r"(?:DATE|[I1L]SSUE|DUE|ON|BY|DATED)\s*[:.]?\s*(\d{1,2})([/\-.])(\d{1,2})\2(\d{4}|\d{2})(?![\d/\-])")
_TIME_AFTER = re.compile(r"^\s*\d{1,2}:\d{2}")

_AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)\s?[.,]\s?(\d{2})(?!\d)")

# Ordered: earlier = stronger evidence that this line holds the amount payable.
_TOTAL_KEYS = [
    r"TOTAL\s*(?:AMOUNT\s*)?ROUNDED|ROUNDED\s*TOTAL|NET+\s*TOTAL\s*ROUNDED",  # payable after rounding
    r"GRAND\s*TOTAL", r"NET+\s*TOTAL", r"TOTAL\s*AMOUNT\s*DUE", r"AMOUNT\s*DUE",
    r"(?:TOTAL|AMOUNT|NET)\s*PAYABLE|BALANCE\s*DUE|TOTAL\s*\(?\s*INC(?:L|LUDING)?\.?\s*(?:VAT|TAX)",
    r"ROUND(?:ED|ING)?\s*TOTAL", r"TOTAL\s*(?:AMOUNT|AMT|PAYABLE|SALES?)?\s*(?:\(?\s*INC\w*)",
    r"TOTAL\s*(?:AMOUNT|AMT|PAYABLE|RM|AED)", r"\bTOTAL\b", r"\bJUMLAH\b",
]
# OCR confuses O/0, L/I/1 and drops letters: "Totai", "T0TAL", "Round:d". Make keywords tolerant.
_TOTAL_KEYS = [k.replace(r"\bTOTAL\b", r"\bT[O0]T[A4][LI1|]\b").replace("TOTAL", r"T[O0]T[A4][LI1|]")
               .replace("ROUNDED", r"ROUN\W?D?\W?(?:E?D)") for k in _TOTAL_KEYS]
_TOTAL_KEYS[0] += r"|ROUN\W?\w?\W?D\s*T[O0]T[A4][LI1|]"

_NOT_TOTAL = re.compile(
    r"SUB\s*-?\s*TOTAL|TOTAL\s*(?:QTY|QUANTITY|ITEMS?|DISC\w*|SAVING\w*|GST|TAX|VAT|EXCL\w*)"
    r"|(?:TAX|GST|VAT)\s*TOTAL|INCLUDED\s*IN\s*TOTAL|EXCLUDING|EXCL\.?\s*(?:GST|VAT|TAX)"
    r"|GST\s*SUMMARY|CHANGE|TENDER|CASH\b|ROUNDING\s*ADJ", re.I)

# Legal-entity suffixes (strong) vs business-type words (weak), Malaysia + UAE.
_LEGAL = re.compile(r"\b(SDN\.?\s*B[HN]D|S/B|BHD|BERHAD|PLT|LLC|L\.L\.C|FZE|FZCO|FZ-?LLC|DMCC)\b", re.I)
_BIZ = re.compile(r"\b(ENTERPRISE|TRADING|RESTAURANT|STORE|MART|HARDWARE|STATIONERY|"
                  r"SUPERMARKET|ELECTRICAL|BOOKS?|CO\.)", re.I)


def _valid(y: int, m: int, d: int) -> str | None:
    if y < 100:
        y += 2000
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    return dt.isoformat() if 2000 <= dt.year <= 2035 else None


def normalize_date(text: str) -> str | None:
    """Best date in `text` as ISO YYYY-MM-DD.

    Day-first (UAE/Malaysia) by default; month-first only when day-first is impossible.
    Candidates are scored: on a DATE line (+3), 4-digit year (+2), followed by a time (+1).
    """
    t = _GLUED_TIME.sub(r"\1 \2", text.upper())
    if re.fullmatch(r"\s*\d{8}\s*", t):  # bare label like 20180428 or 25032018
        d = t.strip()
        return _valid(int(d[:4]), int(d[4:6]), int(d[6:])) or _valid(int(d[4:]), int(d[2:4]), int(d[:2]))
    cands: list[tuple[int, int, str]] = []

    def add(m, iso, four_digit_year, penalty=0):
        if not iso:
            return
        line_start = t.rfind("\n", 0, m.start()) + 1
        line_end = t.find("\n", m.end())
        line = t[line_start: line_end if line_end != -1 else len(t)]
        score = 3 * ("DATE" in line or "TARIKH" in line) + 2 * four_digit_year \
            + bool(_TIME_AFTER.match(t[m.end():])) - penalty
        cands.append((-score, m.start(), iso))

    for m in _ISO_DATE.finditer(t):
        add(m, _valid(int(m[1]), int(m[3]), int(m[4])), True)
    for m in _NUM_DATE.finditer(t):
        d, mo, y = int(m[1]), int(m[3]), int(m[4])
        add(m, _valid(y, mo, d) or (_valid(y, d, mo) if mo > 12 else None), len(m[4]) == 4)
    for m in _NUM_DATE_GLUED.finditer(t):  # day glued to a preceding number: weaker evidence
        add(m, _valid(int(m[4]), int(m[3]), int(m[1])), True, penalty=2)
    for m in _LABELLED_DATE.finditer(t):
        d, mo, y = int(m[1]), int(m[3]), int(m[4])
        add(m, _valid(y, mo, d) or (_valid(y, d, mo) if mo > 12 else None), len(m[4]) == 4)
    for m in _COMPACT.finditer(t):
        add(m, _valid(int(m[1]), int(m[2]), int(m[3])), True)
    for m in _TXT_DATE.finditer(t):
        if m[2] in MONTHS:
            add(m, _valid(int(m[3]), MONTHS[m[2]], int(m[1])), len(m[3]) == 4)
    for m in _TXT_DATE_US.finditer(t):
        if m[1] in MONTHS:
            add(m, _valid(int(m[3]), MONTHS[m[1]], int(m[2])), True)
    return min(cands)[2] if cands else None


def _amounts(line: str) -> list[Decimal]:
    out = []
    for m in _AMOUNT.finditer(line):
        try:
            out.append(Decimal(f"{m[1].replace(',', '')}.{m[2]}"))
        except InvalidOperation:
            pass
    return out


_ROUND_ADJ = re.compile(r"ROUND(?:ING)?\s*(?:ADJ\w*)?", re.I)
_SIGNED = re.compile(r"(-)?\s*(?:RM|AED|\$)?\s*(-)?\s*(\d+[.,]\d{2})(?!\d)")


def _rounding_adjustment(lines: list[str]) -> Decimal | None:
    for ln in lines:
        if _ROUND_ADJ.search(ln) and not re.search(r"TOTAL", ln, re.I):
            m = None
            for m in _SIGNED.finditer(ln):
                pass
            if m:
                v = Decimal(m[3].replace(",", "."))
                return -v if (m[1] or m[2]) else v
    return None


def extract_total(lines: list[str]) -> Decimal | None:
    """Amount payable: keyword priority, then rounding adjustment, then a guarded fallback."""
    total, tier = _keyword_total(lines)
    if total is None:
        return None
    adj = _rounding_adjustment(lines)
    if adj and tier != 0:  # tier 0 = an explicit "TOTAL ROUNDED" line: already adjusted
        present = {a for ln in lines for a in _amounts(ln)}
        for cand in (total + adj, total - adj):
            if cand != total and cand in present:  # rounded payable printed elsewhere
                return cand
        if adj < 0 or any("-" in ln for ln in lines if _ROUND_ADJ.search(ln)):
            return total + adj
    return total


def _keyword_total(lines: list[str]) -> tuple[Decimal | None, int | None]:
    for tier, key in enumerate(_TOTAL_KEYS):
        rx = re.compile(key, re.I)
        found: list[Decimal] = []
        for i, line in enumerate(lines):
            if not rx.search(line) or _NOT_TOTAL.search(line):
                continue
            amts = _amounts(line)
            if not amts:  # amount often sits on the next OCR line
                for nxt in lines[i + 1:i + 3]:
                    if _NOT_TOTAL.search(nxt):
                        break
                    amts = _amounts(nxt)
                    if amts:
                        break
            amts = [x for x in amts if x > 0]  # a zero "total" is never the amount payable
            if amts:
                found.append(amts[-1])
        if found:
            return max(found), tier
    # Fallback: the payable amount is usually repeated (total, tendered, card slip).
    # Prefer the largest amount seen 2+ times; else the largest non-cash amount.
    from collections import Counter
    every = Counter(a for ln in lines for a in _amounts(ln))
    repeated = [a for a, c in every.items() if c >= 2 and a > 0]
    if repeated:
        return max(repeated), None
    pool = [a for ln in lines if not _NOT_TOTAL.search(ln) for a in _amounts(ln)]
    return (max(pool) if pool else None), None


_REG_NO = re.compile(r"\s*\(?\s*(?:CO\.?\s*(?:REG|NO)\.?\s*:?\s*)?\d{5,}\s*-\s*[A-Z]\s*\)?\s*$", re.I)


def _clean_company(name: str) -> str:
    return _REG_NO.sub("", name).strip(" ,.-")


_TAX_ID_LINE = re.compile(r"\b(TRN|VAT\s*REG|GST\s*(?:ID|REG|NO)|TAX\s*REG)", re.I)
_DOC_TITLE = re.compile(r"\s*(TAX\s*INVOICE|SIMPLIFIED\s*TAX\s*INVOICE|INVOICE|RECEIPT|فاتورة).*$", re.I)


def _respace(name: str) -> str:
    """OCR often drops spaces: 'BlueDhowMarineSuppliesFZE' -> 'Blue Dhow Marine Supplies FZE'."""
    out = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    out = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", out)
    return re.sub(r"(?<=[a-z]),(?=[A-Za-z])", ", ", out)


def _company_lines(lines: list[str]) -> list[str]:
    """Header lines above the buyer section, with merged document titles cut off."""
    out = []
    for ln in lines[:8]:
        # The seller's name sits above the buyer section and above the seller's own tax ID line.
        if _BUYER_SECTION.search(ln) or (out and _TAX_ID_LINE.search(ln)):
            break
        cut = _DOC_TITLE.sub("", ln) if not _DOC_TITLE.match(ln) else ""
        out.append(cut.strip())
    return out


def extract_company(lines: list[str]) -> str | None:
    """Seller name sits near the top. Prefer a legal suffix (SDN BHD, LLC, FZE) and join a
    name wrapped over several lines; else a business-type word; else the first text line."""
    top = [_respace(ln) for ln in _company_lines(lines) if len(re.sub(r"[^A-Za-z]", "", ln)) >= 4]

    def fragment(prev: str) -> bool:  # does `prev` look like the start of a wrapped name?
        return (not re.search(r"\d", prev)) and (
            prev.rstrip().endswith(("&", "(", ",")) or prev.count("(") > prev.count(")")
            or bool(_BIZ.search(prev)))

    for i, ln in enumerate(top[:6]):
        if _LEGAL.search(ln):
            start = i
            while start > 0 and i - start < 3 and fragment(top[start - 1]):
                start -= 1
            return _clean_company(" ".join(top[start:i + 1]))
    for i, ln in enumerate(top[:6]):
        if _BIZ.search(ln):
            nxt = top[i + 1] if i + 1 < len(top) else ""
            if ln.rstrip().endswith("&") and nxt and not re.search(r"\d", nxt):
                return _clean_company(f"{ln} {nxt}")
            return _clean_company(ln)
    return _clean_company(top[0]) if top else None


# UAE TRN: 15 digits, starts with 1, ends with 03 (PINT-AE ibr-132-ae). Printed with spaces/dashes.
_TRN_LOOSE = re.compile(r"(?<!\d)1(?:[\s\-]?\d){12}[\s\-]?0[\s\-]?3(?!-?\d)")
_BUYER_SECTION = re.compile(r"\b(BILL(?:ED)?\s*TO|SOLD\s*TO|CUSTOMER|BUYER|CLIENT|RECIPIENT)\b|العميل|المشتري", re.I)
_INV_NO = re.compile(
    r"(?:(?:TAX\s+)?[I1l]NV(?:OICE)?\.?\s*(?:NO\.?|NUMBER|NUM|#|REF(?:ERENCE)?\.?|ID)"
    r"|BILL\s*(?:NO\.?|NUMBER|#)|DOCUMENT\s*(?:NO\.?|NUMBER|#)|REF(?:ERENCE)?\s*(?:NO\.?|NUMBER|#))"
    r"\s*[:#.]?\s*([A-Z0-9][A-Z0-9/\-_.]{1,30})"
    r"|رقم\s+الفاتورة\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-_.]{1,30})", re.I)
# Explicit phrases also match when OCR glues words ("PaymentDue05/02/2026"), where \bDUE can't.
_DUE_LINE = re.compile(r"(PAYMENT\s*DUE|DUE\s*DATE|DUE\s*ON|\bDUE|PAY(?:ABLE|MENT)?\s*BY|PAYMENT\s*TERMS)"
                       r"|تاريخ\s+الاستحقاق", re.I)


def extract_trns(text: str) -> dict:
    """Seller/buyer TRNs by position: TRNs after a 'Bill to'/'Customer' heading are the buyer's."""
    found = [(m.start(), re.sub(r"\D", "", m.group(0))) for m in _TRN_LOOSE.finditer(text)]
    seen, uniq = set(), []
    for pos, trn in found:
        if trn not in seen:
            seen.add(trn)
            uniq.append((pos, trn))
    buyer_at = next((m.start() for m in _BUYER_SECTION.finditer(text)), None)
    seller = next((t for p, t in uniq if buyer_at is None or p < buyer_at), None)
    buyer = next((t for p, t in uniq if buyer_at is not None and p > buyer_at and t != seller), None)
    if buyer is None and len(uniq) > 1 and buyer_at is None:
        buyer = uniq[1][1]
    return {"seller_trn": seller, "buyer_trn": buyer}


def extract_invoice_number(text: str) -> str | None:
    for m in _INV_NO.finditer(text):
        val = (m.group(1) or m.group(2) or "").strip(" .:")
        if val and any(ch.isdigit() for ch in val) and not _TRN_LOOSE.fullmatch(val):
            return val
    return None


_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_LINE_ROW = re.compile(
    rf"^(?P<desc>[A-Za-z][^\n]*?)\s+(?P<qty>{_NUM})\s+(?P<price>{_NUM})\s+(?P<vat>\d{{1,2}}(?:\.\d+)?)\s?%\s+(?P<amt>{_NUM})\s*$")
# OCR often drops an isolated single-digit quantity: "Delivery charge 75.00 5% 375.00".
_LINE_ROW_NOQTY = re.compile(
    rf"^(?P<desc>[A-Za-z][^\n]*?)\s+(?P<price>{_NUM})\s+(?P<vat>\d{{1,2}}(?:\.\d+)?)\s?%\s+(?P<amt>{_NUM})\s*$")
_ADDRESS_HINT = re.compile(r"\b(DUBAI|ABU\s*DHABI|SHARJAH|AJMAN|UMM\s*AL\s*QUWAIN|RAS\s*AL\s*KHAIMAH|FUJAIRAH|"
                           r"P\.?\s*O\.?\s*BOX|STREET|ROAD|AREA|ZONE|BUILDING|OFFICE|FLOOR)\b", re.I)


def _dec(v: str) -> Decimal:
    return Decimal(v.replace(",", ""))


def extract_lines(lines: list[str]) -> list[dict]:
    """Table rows 'Description Qty UnitPrice VAT% Amount'. A row is kept only if qty x price
    equals the amount, so OCR noise can't produce a plausible-looking but wrong line."""
    out = []
    for ln in lines:
        m = _LINE_ROW.match(ln.strip())
        if m:
            qty, price, amt = _dec(m["qty"]), _dec(m["price"]), _dec(m["amt"])
            if abs(qty * price - amt) > Decimal("0.01"):
                m = None
        if not m:
            m = _LINE_ROW_NOQTY.match(ln.strip())
            if not m or _NOT_TOTAL.search(ln) or re.search(r"TOTAL|AMOUNT|VAT\s*@", ln, re.I):
                continue
            price, amt = _dec(m["price"]), _dec(m["amt"])
            if not price:
                continue
            qty = amt / price  # derived exactly; only whole quantities are accepted
            if qty != qty.to_integral_value() or qty < 1:
                continue
            qty = qty.to_integral_value()
        out.append({"description": _respace(m["desc"].strip()), "quantity": str(qty),
                    "unit_price": f"{price:.2f}", "vat_rate": m["vat"], "line_total": f"{amt:.2f}"})
    return out


_EMIRATE_NAME = re.compile(r"(DUBAI|ABU\s*DHABI|SHARJAH|AJMAN|UMM\s*AL\s*QUWAIN|RAS\s*AL\s*KHAIMAH|FUJAIRAH)", re.I)


def _clean_address(addr: str) -> str:
    """Addresses end with the emirate; drop anything OCR merged in after it."""
    last = None
    for last in _EMIRATE_NAME.finditer(addr):
        pass
    return addr[:last.end()] if last else addr


def extract_parties(lines: list[str]) -> dict:
    """Seller address (header, before the seller's tax ID) and buyer name/address (after 'Bill to')."""
    header = _company_lines(lines)
    seller_addr = next((_clean_address(_respace(ln)) for ln in header[1:] if _ADDRESS_HINT.search(ln)), None)
    buyer_name = buyer_addr = None
    start = next((i for i, ln in enumerate(lines) if _BUYER_SECTION.search(ln)), None)
    if start is not None:
        block = []
        # "Bill To: Name" on one line. Without a colon, text after the heading is usually a
        # translated heading (e.g. Arabic OCR'd as Latin noise), not the name.
        m = re.search(r"(?:" + _BUYER_SECTION.pattern + r")\s*:\s*(.+)$", lines[start], re.I)
        if m and len(re.sub(r"[^A-Za-z]", "", m.group(m.lastindex))) >= 4:
            block.append(m.group(m.lastindex).strip())
        for ln in lines[start + 1:start + 5]:
            if _TAX_ID_LINE.search(ln) or _LINE_ROW.match(ln.strip()) or re.search(r"DESCRIPTION|\bQTY\b", ln, re.I):
                break
            block.append(ln.strip())
        block = [b for b in block if len(re.sub(r"[^A-Za-z]", "", b)) >= 4 and not _BUYER_SECTION.search(b)]
    else:
        # No 'Bill to' heading survived OCR: the buyer block is the lines just above the buyer's TRN.
        block = []
        trns = extract_trns("\n".join(lines))
        buyer_trn = trns.get("buyer_trn") or None
        if buyer_trn is None:
            found = [re.sub(r"\D", "", m.group(0)) for m in _TRN_LOOSE.finditer("\n".join(lines))]
            buyer_trn = next((t for t in found if t != trns.get("seller_trn")), None)
        idx = next((i for i, ln in enumerate(lines) if buyer_trn and buyer_trn in re.sub(r"\D", "", ln)), None)
        if idx is not None:
            for ln in reversed(lines[max(0, idx - 3):idx]):
                if re.search(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|LICEN[CS]E|INVOICE|\bINV\b|DATE|DUE", ln, re.I):
                    break
                block.insert(0, ln.strip())
        block = [b for b in block if len(re.sub(r"[^A-Za-z]", "", b)) >= 4]
    if block:
        buyer_name = _respace(block[0])
        buyer_addr = next((_clean_address(_respace(b)) for b in block[1:] if _ADDRESS_HINT.search(b)), None)
    return {"seller_address": seller_addr, "buyer_name": buyer_name, "buyer_address": buyer_addr}


def extract(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    total = extract_total(lines)
    # A merged OCR row can hold both dates ("Invoice Date 05/01/2026 Due Date 05/02/2026"):
    # the due date is what follows the DUE keyword, the issue date what precedes it.
    due_parts, issue_parts = [], []
    for ln in lines:
        m = None
        for m in _DUE_LINE.finditer(ln):
            pass
        if m:
            due_parts.append(ln[m.start():])
            issue_parts.append(ln[:m.start()])
        else:
            issue_parts.append(ln)
    due_lines = [d for d in due_parts if normalize_date(d)]
    issue_text = "\n".join(issue_parts)
    return {
        "company": extract_company(lines),
        "date": normalize_date(issue_text),
        "due_date": normalize_date("\n".join(due_lines)) if due_lines else None,
        "invoice_number": extract_invoice_number(text),
        **extract_trns(text),
        **extract_parties(lines),
        "lines": extract_lines(lines),
        "total": str(total) if total is not None else None,
        # "keyword" = found on a TOTAL-type line; "fallback" = best guess (repeated/largest amount)
        "total_source": "keyword" if _keyword_total(lines)[1] is not None else "fallback",
    }
