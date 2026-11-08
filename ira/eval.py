"""Measure fault-detection accuracy on synthetic invoices with known injected faults.

This prints the numbers that go on your pitch slide:
precision (no false alarms), recall (no missed faults), and clean-invoice pass rate.
Later, run the same harness on LLM-extracted versions of rendered invoices to measure
end-to-end accuracy (extraction + validation).
"""
from __future__ import annotations

from collections import Counter

from .models import invoice_from_dict
from .synth import generate
from .validate import validate


def evaluate(count: int = 200, seed: int = 7) -> dict:
    tp = fp = fn = 0
    clean_total = clean_pass = 0
    missed: Counter = Counter()
    deferred = 0  # faults intentionally held back behind a root-cause fault
    false_alarms: Counter = Counter()
    for d in generate(count=count, seed=seed):
        expected = set(d["_expected"])
        found = {i.code for i in validate(invoice_from_dict(d)) if i.severity == "error"}
        # VAT_TOTAL_MISMATCH injection also breaks the gross total -- a true consequence.
        cascades = {"GROSS_TOTAL_MISMATCH"} if "VAT_TOTAL_MISMATCH" in expected else set()
        # A bad VAT rate masks the VAT-total check until the owner fixes the rate;
        # the repair loop re-validates, so this is deferred, not missed.
        if "BAD_VAT_RATE" in found and "VAT_TOTAL_MISMATCH" in expected - found:
            expected.discard("VAT_TOTAL_MISMATCH")
            deferred += 1
        tp += len(expected & found)
        fn += len(expected - found)
        missed.update(expected - found)
        extra = found - expected - cascades
        fp += len(extra)
        false_alarms.update(extra)
        if not expected:
            clean_total += 1
            clean_pass += not found
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "invoices": count,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "clean_pass_rate": round(clean_pass / clean_total, 3) if clean_total else None,
        "deferred_until_repair": deferred,
        "missed": dict(missed),
        "false_alarms": dict(false_alarms),
    }


if __name__ == "__main__":
    for k, v in evaluate().items():
        print(f"{k:>16}: {v}")
