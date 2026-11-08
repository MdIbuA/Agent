"""Free, local OCR engines (no API keys, no per-page cost).

rapidocr  : PP-OCR models via ONNX, CPU-only, models bundled in the pip wheel. Best accuracy.
tesseract : classic OCR (apt install tesseract-ocr). Faster, much weaker on low-res scans.
Benchmarked on 626 real scanned receipts in benchmarks/sroie_bench.py.
"""
from __future__ import annotations

import math
import os
import statistics
import subprocess
from functools import lru_cache
from pathlib import Path

from .layout import rows_from_boxes


@lru_cache(maxsize=1)
def _rapid():
    from rapidocr_onnxruntime import RapidOCR  # pip install rapidocr_onnxruntime
    return RapidOCR()


def _skew(result) -> float:
    """Median text-line angle (radians) from the top edges of wide OCR boxes."""
    angles = []
    for quad, text, _conf in result:
        (x0, y0), (x1, y1) = quad[0], quad[1]
        if x1 - x0 > 60:  # short boxes give noisy angles
            angles.append(math.atan2(y1 - y0, x1 - x0))
    return statistics.median(angles) if len(angles) >= 3 else 0.0


def ocr_rapid(img: Path) -> str:
    result, _ = _rapid()(str(img))
    result = result or []
    # Deskew: rotate box coordinates by the page's text angle so rows line up even on
    # slightly rotated scans (a 1.5 degree tilt shifts a wide table row by ~15 px).
    a = -_skew(result)
    cos, sin = math.cos(a), math.sin(a)
    boxes = []
    for quad, text, _conf in result:
        pts = [(x * cos - y * sin, x * sin + y * cos) for x, y in quad]
        ys, xs = [p[1] for p in pts], [p[0] for p in pts]
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
