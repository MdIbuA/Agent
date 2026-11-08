"""Rebuild visual text rows from OCR word boxes.

OCR engines (RapidOCR, Textract, dataset labels) return boxes, not lines. Receipts and
invoices put labels and values in columns ("TOTAL ........ 9.00"), so we group boxes
whose vertical centres overlap into one row and order them left-to-right.
"""
from __future__ import annotations


def rows_from_boxes(boxes: list[tuple[float, float, float, str]]) -> str:
    """boxes: (top_y, bottom_y, left_x, text) -> newline-joined rows."""
    rows: list[list] = []
    for top, bot, x, text in sorted(boxes):
        mid = (top + bot) / 2
        if rows and abs(mid - rows[-1][0]) <= max(4, (bot - top) * 0.5):
            rows[-1][1].append((x, text))
        else:
            rows.append([mid, [(x, text)]])
    return "\n".join(" ".join(t for _, t in sorted(r[1])) for r in rows)
