"""Does the agent know when it might be wrong?

Two independent free OCR engines read each scan. If they extract the same value, the
agent auto-accepts it; if they disagree, it asks the owner to confirm. This script
measures the trade-off on real receipts:
  coverage  = % of receipts auto-accepted (no question needed)
  precision = % of auto-accepted values that are actually correct
A compliance product should prefer high precision: a wrong total sent to the tax
authority is far worse than one extra question.

Run after sroie_bench has filled both OCR caches:
  python3 -m benchmarks.confidence /path/to/sroie/data --out bench_out
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.sroie_bench import norm_company, to_dec
from ira.rule_extract import extract, normalize_date


def same(field: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if field == "total":
        return to_dec(a) == to_dec(b)
    if field == "company":
        return norm_company(a) == norm_company(b)
    return a == b


def correct(field: str, pred, truth: dict) -> bool:
    if field == "total":
        return pred is not None and to_dec(pred) == to_dec(truth.get("total"))
    if field == "date":
        return pred == (normalize_date(truth.get("date", "")) or truth.get("date"))
    return norm_company(pred) == norm_company(truth.get("company"))


def run(data: Path, out: Path) -> dict:
    caches = {e: out / f"ocr_cache_{e}" for e in ("tesseract", "rapidocr")}
    ids = sorted(p.stem for p in caches["rapidocr"].glob("*.txt")
                 if (caches["tesseract"] / p.name).exists())
    res = {}
    for field in ("total", "date", "company"):
        n = agree = agree_ok = rapid_ok = either_ok = 0
        for i in ids:
            truth = json.loads((data / "key" / f"{i}.json").read_text(errors="replace"))
            et = extract((caches["tesseract"] / f"{i}.txt").read_text())
            er = extract((caches["rapidocr"] / f"{i}.txt").read_text())
            pt, pr = et[field], er[field]
            # Same auto-accept rule as ira/agent.py: totals must come from a TOTAL-type line.
            strong = field != "total" or et["total_source"] == er["total_source"] == "keyword"
            n += 1
            ok_r, ok_t = correct(field, pr, truth), correct(field, pt, truth)
            rapid_ok += ok_r
            either_ok += ok_r or ok_t
            if same(field, pt, pr) and strong:
                agree += 1
                agree_ok += ok_r
        res[field] = {
            "receipts": n,
            "rapidocr_alone_accuracy": round(100 * rapid_ok / n, 1),
            "auto_accept_coverage": round(100 * agree / n, 1),
            "auto_accept_precision": round(100 * agree_ok / max(agree, 1), 1),
            "oracle_either_engine": round(100 * either_ok / n, 1),
        }
    (out / "confidence.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--out", type=Path, default=Path("bench_out"))
    a = ap.parse_args()
    for f, r in run(a.data, a.out).items():
        print(f, r)
