"""Rules vs LLM vs hybrid on UAE invoice PDFs (use a HELD-OUT layout for a fair test).

    python -m benchmarks.uae_invoice_pdfs make --holdout 3 --out bench_h3 --count 20
    python -m benchmarks.llm_vs_rules --out bench_h3            # digital: text layer
    python -m benchmarks.llm_vs_rules --out bench_h3 --scanned  # scanned: OCR vs LLM vision

Hybrid = auto-accept fields where rules and LLM agree; disagreements go to the owner.
Reported: accuracy of each extractor, hybrid auto-accept coverage and precision.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from decimal import Decimal
from pathlib import Path

from ira.extract import FIELDS, hybrid, llm_extract_image, llm_extract_text

SCORED = ("invoice_number", "date", "due_date", "total", "company", "seller_trn", "buyer_trn",
          "buyer_name", "seller_address", "buyer_address", "lines")


def correct(field, got, truth) -> bool:
    g = got.get(field)
    if field == "lines":
        try:
            return sorted((Decimal(l["quantity"]), Decimal(l["unit_price"])) for l in g or []) == \
                   sorted((Decimal(q), Decimal(p)) for q, p, _ in truth["lines"])
        except Exception:
            return False
    if g in (None, ""):
        return False
    if field == "total":
        return Decimal(str(g)) == Decimal(truth["total"])
    norm = lambda v: re.sub(r"[^A-Z0-9]", "", str(v).upper())
    return norm(g) == norm(truth[field]) if field in ("company", "buyer_name", "seller_address",
                                                      "buyer_address") else str(g) == str(truth[field])


def run(out: Path, scanned: bool) -> dict:
    import pypdfium2 as pdfium
    from ira.ocr import ENGINES
    from ira.pdf import pdf_to_text
    from ira.rule_extract import extract as rule_extract
    truth = json.loads((out / "truth.json").read_text())
    folder = out / "scanned" if scanned else out
    acc = {k: {f: 0 for f in SCORED} for k in ("rules", "llm", "hybrid")}
    agreed = agreed_ok = 0
    for name, t in truth.items():
        pdf = folder / f"{name}.pdf"
        text, _ = pdf_to_text(pdf, ENGINES["rapidocr"])
        rules = rule_extract(text)
        if scanned:  # LLM reads the page image itself (vision), independent of our OCR
            with tempfile.TemporaryDirectory() as td:
                img = Path(td) / "page.png"
                pdfium.PdfDocument(str(pdf))[0].render(scale=150 / 72).to_pil().save(img)
                llm = llm_extract_image(img)
        else:
            llm = llm_extract_text(text)
        merged, unconfirmed = hybrid(rules, llm)
        for f in SCORED:
            acc["rules"][f] += correct(f, rules, t)
            acc["llm"][f] += correct(f, llm, t)
            acc["hybrid"][f] += correct(f, merged, t)
        for f in FIELDS:
            if f in SCORED and f not in unconfirmed and merged.get(f):
                agreed += 1
                agreed_ok += correct(f, merged, t)
    n = len(truth)
    return {"documents": n, "scanned": scanned,
            **{k: {f: round(100 * v / n, 1) for f, v in d.items()} for k, d in acc.items()},
            "hybrid_auto_accepted_fields": agreed,
            "hybrid_auto_accept_precision_pct": round(100 * agreed_ok / max(agreed, 1), 1),
            "hybrid_auto_accept_coverage_pct": round(100 * agreed / (n * len([f for f in FIELDS if f in SCORED])), 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scanned", action="store_true")
    a = ap.parse_args()
    r = run(a.out, a.scanned)
    print(f"{'field':<16}{'rules':>8}{'LLM':>8}{'hybrid':>8}")
    for f in SCORED:
        print(f"{f:<16}{r['rules'][f]:>8}{r['llm'][f]:>8}{r['hybrid'][f]:>8}")
    print(f"hybrid auto-accepts {r['hybrid_auto_accept_coverage_pct']}% of fields, "
          f"{r['hybrid_auto_accept_precision_pct']}% of those correct ({r['hybrid_auto_accepted_fields']} fields)")
    (a.out / f"llm_vs_rules_{'scanned' if a.scanned else 'digital'}.json").write_text(json.dumps(r, indent=1))
