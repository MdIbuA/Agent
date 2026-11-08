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
}


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def _ocr_extract(path: Path, engine: str) -> dict:
    """Offline path: OCR + rule extraction. Fields it can't see stay None, so the
    validator turns them into questions for the owner instead of guesses."""
    from .ocr import ENGINES
    from .rule_extract import extract as rule_extract
    unconfirmed: list[str] = []
    if engine == "both":
        # Two independent engines. Agreement = auto-accept; disagreement = ask the owner.
        # Totals also need both engines to have found a TOTAL-type line (not a guess).
        # On 626 real receipts: agreed dates 100% correct; agreed keyword totals 90.3%
        # strict, ~97% excluding Malaysia's 5-sen cash rounding (see BENCHMARK.md).
        a = rule_extract(ENGINES["rapidocr"](path))
        b = rule_extract(ENGINES["tesseract"](path))
        found = dict(a)
        for f in ("date", "total", "company"):
            same = (a[f] or "").replace(" ", "").upper() == (b[f] or "").replace(" ", "").upper()
            strong = f != "total" or (a["total_source"] == b["total_source"] == "keyword")
            if not (a[f] and same and strong):
                unconfirmed.append(f)
                found[f] = a[f] or b[f]  # RapidOCR is the stronger engine
    else:
        found = rule_extract(ENGINES[engine](path))
    return {
        "_unconfirmed": unconfirmed,
        "invoice_number": None,
        "issue_date": found["date"],
        "seller": {"name": found["company"]},
        "buyer": {},
        "lines": [],
        "gross_total": found["total"],
        "source_file": path.name,
    }


def _load(source: Path, use_llm: bool, ocr: str | None = None) -> list[dict]:
    if source.is_file() and source.suffix == ".json":
        data = json.loads(source.read_text())
        return data if isinstance(data, list) else [data]
    if ocr:
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        return [_ocr_extract(p, ocr) for p in files]
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
