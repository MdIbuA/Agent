"""Agent loop: ingest -> extract -> validate -> ask owner to repair -> output XML + report.

Run:
    python -m ira.agent data/synthetic_invoices.json          # synthetic, no LLM needed
    python -m ira.agent path/to/invoices_folder --llm         # real files via free LLM tier
    python -m ira.agent path/to/scans --ocr rapidocr          # real scans, offline, no API key
    python -m ira.agent path/to/scans --ocr both              # two engines cross-check each other
    python -m ira.agent ... --interactive                     # owner answers repair questions
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from .models import invoice_from_dict, to_decimal
from .ubl import to_ubl_xml
from .validate import Issue, normalize_trn, readiness_score, validate

# Which answers the agent can apply automatically after asking the owner.
_FIELD_SETTERS = {
    "invoice_number": lambda inv, v: setattr(inv, "invoice_number", v),
    "issue_date": lambda inv, v: setattr(inv, "issue_date", v),
    "seller.trn": lambda inv, v: setattr(inv.seller, "trn", normalize_trn(v)),
    "buyer.trn": lambda inv, v: setattr(inv.buyer, "trn", normalize_trn(v)),
    "seller.address": lambda inv, v: setattr(inv.seller, "address", v),
    "buyer.address": lambda inv, v: setattr(inv.buyer, "address", v),
    "seller.name": lambda inv, v: setattr(inv.seller, "name", v),
    "buyer.name": lambda inv, v: setattr(inv.buyer, "name", v),
    "seller.emirate": lambda inv, v: setattr(inv.seller, "emirate", parse_emirate(v)),
    "buyer.emirate": lambda inv, v: setattr(inv.buyer, "emirate", parse_emirate(v)),
    "seller.legal_id": lambda inv, v: setattr(inv.seller, "legal_id", v.strip()),
    "seller.legal_authority": lambda inv, v: setattr(inv.seller, "legal_authority", v.strip()),
    "due_date": lambda inv, v: setattr(inv, "due_date", v),
    "payment_means": lambda inv, v: setattr(inv, "payment_means", parse_payment_means(v)),
    "credit_reason": lambda inv, v: setattr(inv, "credit_reason", parse_credit_reason(v)),
    "preceding_invoice": lambda inv, v: setattr(inv, "preceding_invoice", v.strip()),
}


def parse_credit_reason(value: str) -> str:
    from .codelists import CREDIT_REASONS
    v = value.strip().upper()
    if v in CREDIT_REASONS:
        return v
    if f"DL8.61.1.{v}" in CREDIT_REASONS:  # allow the short letter "D"
        return f"DL8.61.1.{v}"
    raise ValueError("Choose an official reason: " + "; ".join(CREDIT_REASONS.values()))


def parse_emirate(value: str) -> str:
    """Accept 'DXB', 'dubai', 'Abu Dhabi' ... -> PINT-AE code. Raises ValueError if unknown."""
    from .models import EMIRATES, emirate_from_text
    v = value.strip().upper()
    code = v if v in EMIRATES else emirate_from_text(v)
    if not code:
        raise ValueError("Use an emirate name or code: " + ", ".join(EMIRATES))
    return code


# Order matters: more specific phrases first.
_PAYMENT_WORDS = [("DIRECT DEBIT", "49"), ("DEBIT CARD", "55"), ("CREDIT CARD", "54"), ("DRAFT", "21"),
                  ("CHEQUE", "20"), ("CHECK", "20"), ("PDC", "20"), ("ONLINE", "68"), ("LINK", "68"),
                  ("TRANSFER", "30"), ("BANK", "30"), ("WIRE", "30"), ("CASH", "10"), ("CARD", "54")]


def parse_payment_means(value: str) -> str:
    """Accept a UNCL4461 code or words like 'bank transfer', 'cash', 'card'."""
    from .validate import PAYMENT_MEANS
    v = value.strip().upper()
    if v in PAYMENT_MEANS:
        return v
    for word, code in _PAYMENT_WORDS:
        if word in v:
            return code
    raise ValueError("Say how the buyer pays, e.g. bank transfer, cheque, cash or card.")


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


# Fields read from a document that the owner may be asked to confirm.
OCR_FIELDS = ("invoice_number", "date", "due_date", "total", "company", "seller_trn", "buyer_trn")
REGISTER_FIELDS = ("company", "buyer_name", "seller_licence")  # corrected/suggested from the official register


def _norm(v) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(v or "").upper())


def _to_invoice_dict(found: dict, unconfirmed: list[str], source_file: str, via: str) -> dict:
    """Rule-extraction output -> invoice dict. Unread fields stay None so the validator asks for them."""
    seller = {"name": found.get("company"), "trn": found.get("seller_trn"), "address": found.get("seller_address"),
              "legal_id": found.get("seller_licence"), "legal_authority": found.get("seller_licence_authority")}
    buyer = {"name": found.get("buyer_name"), "trn": found.get("buyer_trn"), "address": found.get("buyer_address")}
    for party in (seller, buyer):  # city/emirate only from an explicit address
        if party["address"]:
            party["city"] = party["address"].split(",")[-1].strip()
    return {
        "_unconfirmed": [f for f in dict.fromkeys(unconfirmed) if found.get(f) not in (None, "")],
        "_via": via,
        "invoice_number": found.get("invoice_number"),
        "issue_date": found.get("date"),
        "due_date": found.get("due_date"),
        "seller": seller,
        "buyer": buyer,
        "lines": found.get("lines") or [],
        "gross_total": found.get("total"),
        "source_file": source_file,
    }


def _ocr_extract(path: Path, engine: str) -> dict:
    """Image -> OCR -> rule extraction. With engine="both", fields the two independent engines
    agree on are auto-accepted; everything else read by OCR is put to the owner to confirm.
    (On 626 real receipts: agreed dates 100% correct; agreed keyword totals 90.3% strict,
    ~97% excluding Malaysia's 5-sen cash rounding. See BENCHMARK.md.)"""
    from .ocr import ENGINES
    from .rule_extract import extract as rule_extract
    if engine != "both":
        return _to_invoice_dict(rule_extract(ENGINES[engine](path)), list(OCR_FIELDS), path.name, "ocr")
    a = rule_extract(ENGINES["rapidocr"](path))
    b = rule_extract(ENGINES["tesseract"](path))
    found, unconfirmed = dict(a), []
    for f in OCR_FIELDS:
        strong = f != "total" or (a["total_source"] == b["total_source"] == "keyword")
        if not (a.get(f) and _norm(a.get(f)) == _norm(b.get(f)) and strong):
            unconfirmed.append(f)
            found[f] = a.get(f) or b.get(f)  # RapidOCR is the stronger engine
    return _to_invoice_dict(found, unconfirmed, path.name, "ocr-2")


KEY_FIELDS = ("invoice_number", "date", "total", "company", "seller_trn")


def llm_enabled() -> bool:
    """AI extraction is opt-in (QAID_LLM=1). Without it the agent is fully offline and free."""
    return os.environ.get("QAID_LLM", "").strip().lower() in ("1", "true", "on", "gemini")


def _rules_incomplete(found: dict) -> bool:
    """Call the AI only when the free rules missed something important (keeps AI calls rare)."""
    from .validate import TRN_RE
    return (any(not found.get(f) for f in KEY_FIELDS) or not found.get("lines")
            or not TRN_RE.match(found.get("seller_trn") or ""))


def _with_llm(found: dict, unconfirmed: list[str], text: str, image: Path | None) -> tuple[dict, list[str], str]:
    """Rules first; AI only if needed. Agreement between the two independent readers is accepted,
    disagreements go to the owner. Any AI failure (quota, offline, bad reply) falls back to rules."""
    if not llm_enabled() or not _rules_incomplete(found):
        return found, unconfirmed, "rules"
    from .extract import LLMError, hybrid, llm_extract_image, llm_extract_text
    try:
        llm = llm_extract_image(image) if image is not None else llm_extract_text(text)
    except LLMError:
        return found, unconfirmed, "rules (AI unavailable)"
    merged, disagreements = hybrid(found, llm)
    return merged, [f for f in disagreements if f in OCR_FIELDS], "rules + AI"


def _with_register(found: dict, unconfirmed: list[str], by: str) -> tuple[dict, list[str], str]:
    """Correct OCR-garbled party names to their form in the official Ajman licence register and
    suggest the seller's licence number. Every change is put to the owner to confirm."""
    from .registry import snap_parties
    found, changed = snap_parties(found)
    if not changed:
        return found, unconfirmed, by
    return found, list(unconfirmed) + changed, f"{by} + Ajman licence register"


def _render_first_page(pdf: Path, out: Path) -> Path:
    import pypdfium2 as pdfium
    pdfium.PdfDocument(str(pdf))[0].render(scale=150 / 72).to_pil().save(out)
    return out


def document_extract(path: Path, engine: str | None) -> dict:
    """Images and PDFs. Digital PDFs are read from their text layer (exact, auto-accepted);
    scanned PDFs and images go through OCR and their fields are confirmed by the owner.
    With QAID_LLM=1, the AI is consulted only when the rules leave gaps."""
    import tempfile
    from .rule_extract import extract as rule_extract
    if path.suffix.lower() == ".pdf":
        from .ocr import ENGINES
        from .pdf import pdf_to_text
        ocr = ENGINES["rapidocr" if engine in ("both", "rapidocr") else engine] if engine else None
        if ocr is None:
            def ocr(_img):
                raise ValueError("This PDF is a scan and no OCR engine is installed.")
        text, mode = pdf_to_text(path, ocr)
        found = rule_extract(text)
        unconfirmed = [] if mode == "text-layer" else list(OCR_FIELDS)
        with tempfile.TemporaryDirectory() as td:
            image = None if mode == "text-layer" else _render_first_page(path, Path(td) / "p1.png")
            found, unconfirmed, by = _with_llm(found, unconfirmed, text, image)
        found, unconfirmed, by = _with_register(found, unconfirmed, by)
        d = _to_invoice_dict(found, unconfirmed, path.name, mode)
        d["_extractor"] = by
        return d
    if engine is None:
        raise ValueError("No OCR engine installed (pip install rapidocr_onnxruntime).")
    d = _ocr_extract(path, engine)
    if llm_enabled():
        from .ocr import ENGINES
        from .rule_extract import extract as rx
        found = rx(ENGINES["rapidocr" if engine in ("both", "rapidocr") else engine](path))
        merged, unconfirmed, by = _with_llm(found, d["_unconfirmed"], "", path)
        if by == "rules + AI":
            d = _to_invoice_dict(merged, unconfirmed, path.name, d["_via"])
        d["_extractor"] = by
    else:
        d["_extractor"] = "rules"
    return d


def _load(source: Path, use_llm: bool, ocr: str | None = None) -> list[dict]:
    if source.is_file() and source.suffix == ".json":
        data = json.loads(source.read_text())
        return data if isinstance(data, list) else [data]
    if ocr:
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES | {".pdf"})
        return [document_extract(p, ocr) for p in files]
    if not use_llm:
        raise SystemExit("Folder input needs --ocr {rapidocr,tesseract,both} or --llm "
                         "(set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL).")
    from .extract import extract
    files = sorted(p for p in source.iterdir() if p.is_file())
    return [extract(p) for p in files]


def repair(inv, issues, interactive: bool):
    """Human-in-the-loop: ask only what's missing, apply answers, re-validate."""
    if not interactive:
        return inv, issues
    for issue in issues:
        setter = _FIELD_SETTERS.get(issue.field)
        if not setter or issue.severity != "error":
            continue
        answer = input(f"[{inv.invoice_number or inv.source_file}] {issue.question} > ").strip()
        if answer:
            setter(inv, answer)
    return inv, validate(inv)


def run(source: Path, out_dir: Path, use_llm: bool, interactive: bool, ocr: str | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for raw in _load(source, use_llm, ocr):
        inv = invoice_from_dict(raw)
        issues = validate(inv)
        labels = {"date": ("issue_date", "issue date"), "total": ("gross_total", "total"),
                  "company": ("seller.name", "seller name")}
        for f in raw.get("_unconfirmed", []):
            field, label = labels[f]
            value = {"date": inv.issue_date, "total": inv.stated_gross_total, "company": inv.seller.name}[f]
            if value in (None, ""):
                issues.append(Issue(f"MISSING_{f.upper()}", "error", field,
                                    f"Could not read the {label} from the scan.",
                                    f"What is the {label} on this invoice?"))
            else:
                issues.append(Issue(f"UNCONFIRMED_{f.upper()}", "warning", field,
                                    f"OCR engines disagree on the {label}; read as '{value}'.",
                                    f"Please confirm the {label}: is it '{value}'?"))
        inv, issues = repair(inv, issues, interactive)
        ready = not any(i.severity == "error" for i in issues)
        name = inv.invoice_number or Path(inv.source_file or "unknown").stem
        if ready:
            (out_dir / f"{name}.xml").write_text(to_ubl_xml(inv))
        report.append({
            "invoice": name,
            "ready_for_asp": ready,
            "score": readiness_score(issues),
            "extracted": {"date": inv.issue_date, "seller": inv.seller.name,
                          "total": None if inv.stated_gross_total is None else str(inv.stated_gross_total)},
            "issues": [{"code": i.code, "severity": i.severity, "message": i.message,
                        "ask_owner": i.question} for i in issues],
        })
    ready_n = sum(r["ready_for_asp"] for r in report)
    summary = {
        "invoices": len(report),
        "ready_for_asp": ready_n,
        "readiness_pct": round(100 * ready_n / len(report), 1) if report else 0.0,
        "avg_score": round(sum(r["score"] for r in report) / len(report), 1) if report else 0.0,
        "details": report,
    }
    (out_dir / "readiness_report.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser(description="UAE e-invoicing readiness agent")
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--llm", action="store_true", help="extract real files with an LLM")
    ap.add_argument("--interactive", action="store_true", help="ask owner to fix errors")
    ap.add_argument("--ocr", choices=["rapidocr", "tesseract", "both"], help="offline OCR for image folders")
    a = ap.parse_args()
    s = run(a.source, a.out, a.llm, a.interactive, a.ocr)
    print(f"{s['ready_for_asp']}/{s['invoices']} invoices ready for ASP "
          f"({s['readiness_pct']}%), avg score {s['avg_score']}. Report: {a.out}/readiness_report.json")


if __name__ == "__main__":
    main()
