"""Free, local OCR engines (no API keys, no per-page cost).

rapidocr  : PP-OCR models via ONNX, CPU-only, models bundled in the pip wheel. Best accuracy.
tesseract : classic OCR (apt install tesseract-ocr). Faster, much weaker on low-res scans.
Benchmarked on 626 real scanned receipts in benchmarks/sroie_bench.py.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .layout import rows_from_boxes


@lru_cache(maxsize=1)
def _rapid():
    from rapidocr_onnxruntime import RapidOCR  # pip install rapidocr_onnxruntime
    return RapidOCR()


def ocr_rapid(img: Path) -> str:
    result, _ = _rapid()(str(img))
    boxes = []
    for quad, text, _conf in result or []:
        ys, xs = [p[1] for p in quad], [p[0] for p in quad]
        boxes.append((min(ys), max(ys), min(xs), text))
    return rows_from_boxes(boxes)


def ocr_tesseract(img: Path) -> str:
    r = subprocess.run(["tesseract", str(img), "stdout", "--psm", "4"],
                       capture_output=True, text=True, timeout=120,
                       # One thread per process: parallel tesseracts with default OpenMP
                       # threading thrash the CPU (measured ~60x slower).
                       env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return r.stdout


ENGINES = {"rapidocr": ocr_rapid, "tesseract": ocr_tesseract}
