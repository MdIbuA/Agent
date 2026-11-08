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
_TIME_AFTER = re.compile(r"^\s*\d{1,2}:\d{2}")

_AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)\s?[.,]\s?(\d{2})(?!\d)")

# Ordered: earlier = stronger evidence that this line holds the amount payable.
_TOTAL_KEYS = [
    r"TOTAL\s*(?:AMOUNT\s*)?ROUNDED|ROUNDED\s*TOTAL|NET+\s*TOTAL\s*ROUNDED",  # payable after rounding
    r"GRAND\s*TOTAL", r"NET+\s*TOTAL", r"TOTAL\s*AMOUNT\s*DUE", r"AMOUNT\s*DUE",
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


def extract_company(lines: list[str]) -> str | None:
    """Seller name sits near the top. Prefer a legal suffix (SDN BHD, LLC, FZE) and join a
    name wrapped over several lines; else a business-type word; else the first text line."""
    top = [ln.strip() for ln in lines[:8] if len(re.sub(r"[^A-Za-z]", "", ln)) >= 4]

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


def extract(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    total = extract_total(lines)
    return {
        "company": extract_company(lines),
        "date": normalize_date(text),
        "total": str(total) if total is not None else None,
        # "keyword" = found on a TOTAL-type line; "fallback" = best guess (repeated/largest amount)
        "total_source": "keyword" if _keyword_total(lines)[1] is not None else "fallback",
    }
