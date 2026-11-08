"""Benchmark extraction on REAL scanned receipts (ICDAR-2019 SROIE, 626 labelled scans).

Two runs separate the error sources:
  gold : extractor on the dataset's human-checked OCR text -> measures extraction LOGIC
  ocr  : extractor on free Tesseract OCR of the images     -> measures END-TO-END pipeline

Usage:
  git clone --depth 1 --filter=blob:none --sparse https://github.com/zzzDavid/ICDAR-2019-SROIE.git sroie
  (cd sroie && git sparse-checkout set data)
  python3 -m benchmarks.sroie_bench /path/to/sroie/data --out bench_out
Needs: tesseract-ocr (apt). No API keys, $0.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from ira.layout import rows_from_boxes
from ira.ocr import ENGINES
from ira.rule_extract import extract, normalize_date


def gold_text(box_file: Path) -> str:
    """Dataset's human-checked word boxes (x1,y1,...,x4,y4,TEXT) -> visual rows."""
    boxes = []
    for raw in box_file.read_text(errors="replace").splitlines():
        parts = raw.split(",", 8)
        if len(parts) != 9:
            continue
        try:
            xs, ys = [int(v) for v in parts[0:8:2]], [int(v) for v in parts[1:8:2]]
        except ValueError:
            continue
        boxes.append((min(ys), max(ys), min(xs), parts[8]))
    return rows_from_boxes(boxes)


def ocr_text(engine: str, img: Path, cache: Path) -> str:
    out = cache / f"{img.stem}.txt"
    if not out.exists():
        out.write_text(ENGINES[engine](img))
    return out.read_text()


def norm_company(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def to_dec(s) -> Decimal | None:
    """Parse labels like '$8.20', 'RM 9.00', '1,250.00'. Empty label -> None."""
    cleaned = re.sub(r"[^0-9.\-]", "", str(s or ""))
    try:
        return Decimal(cleaned) if cleaned else None
    except InvalidOperation:
        return None


def score(pred: dict, truth: dict) -> dict:
    t_date = normalize_date(truth.get("date", "")) or truth.get("date")
    ratio = SequenceMatcher(None, norm_company(pred["company"]), norm_company(truth.get("company"))).ratio()
    return {
        "date": pred["date"] == t_date,
        "total": pred["total"] is not None and to_dec(pred["total"]) == to_dec(truth.get("total")),
        "company_exact": norm_company(pred["company"]) == norm_company(truth.get("company")),
        "company_fuzzy": ratio >= 0.9,
    }


def run(data: Path, out: Path, workers: int, engine: str):
    out.mkdir(parents=True, exist_ok=True)
    cache = out / f"ocr_cache_{engine}"
    cache.mkdir(exist_ok=True)
    ids = sorted(p.stem for p in (data / "key").glob("*.json")
                 if (data / "img" / f"{p.stem}.jpg").exists() and (data / "box" / f"{p.stem}.csv").exists())
    # tesseract: parallel subprocesses. rapidocr: onnxruntime already uses all cores.
    w = workers if engine == "tesseract" else 1
    with ThreadPoolExecutor(w) as ex:
        ocr = dict(zip(ids, ex.map(lambda i: ocr_text(engine, data / "img" / f"{i}.jpg", cache), ids)))

    results = {"gold": [], "ocr": []}
    errors = []
    for i in ids:
        truth = json.loads((data / "key" / f"{i}.json").read_text(errors="replace"))
        for mode, text in (("gold", gold_text(data / "box" / f"{i}.csv")), ("ocr", ocr[i])):
            pred = extract(text)
            s = score(pred, truth)
            results[mode].append(s)
            if mode == "ocr" and not (s["date"] and s["total"]):
                errors.append({"id": i, "truth": truth, "pred": pred, "ok": s})

    summary = {"receipts": len(ids)}
    for mode, rows in results.items():
        n = len(rows)
        summary[mode] = {k: round(100 * sum(r[k] for r in rows) / n, 1) for k in rows[0]}
        summary[mode]["date_and_total"] = round(100 * sum(r["date"] and r["total"] for r in rows) / n, 1)
    (out / f"summary_{engine}.json").write_text(json.dumps(summary, indent=2))
    (out / f"errors_{engine}.json").write_text(json.dumps(errors, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--out", type=Path, default=Path("bench_out"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--engine", choices=sorted(ENGINES), default="rapidocr")
    a = ap.parse_args()
    s = run(a.data, a.out, a.workers, a.engine)
    print(f"Receipts: {s['receipts']}")
    print(f"{'field':<16}{'gold text %':>12}{a.engine + ' %':>14}")
    for k in s["gold"]:
        print(f"{k:<16}{s['gold'][k]:>12}{s['ocr'][k]:>14}")


if __name__ == "__main__":
    main()
