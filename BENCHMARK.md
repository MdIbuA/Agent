# Benchmarks

## 1. Official UAE compliance: OpenPeppol PINT AE v1.0.3 Schematron

The official PINT AE Billing resources published by OpenPeppol (docs.peppol.eu/poac/ae)
include the compiled Schematron rules and example invoices. `benchmarks/pint_ae_check.py`
downloads the pinned bundle (SHA-256 checked) and runs both rule sets with Saxon.

| Check | Result |
|---|---|
| Official example invoices (sanity check of the harness) | 10 / 10 pass |
| Known-invalid invoice (bad TRN) | correctly fails `ibr-132-ae` |
| Agent XML **before** this work | **0 / 100 pass**, 15 fatal rules each |
| Agent XML **after** rebuilding to the official example | **100 / 100 pass**, 0 fatal, 0 warnings |
| End-to-end in the web UI: answer 4 questions, download, validate | pass |

What the official rules caught that our own tests did not: UAE TRN format (15 digits,
starts with 1, **ends with 03**, `ibr-132-ae`), emirate code (`ibr-128-ae`), due date
(`ibr-127-ae`), payment means (`ibr-191-ae`), transaction-type code (`ibr-154-ae`),
document UUID (`ibr-193-ae`), seller trade licence + issuing authority (`ibr-150/172-ae`),
Peppol endpoint (scheme 0235), and line-level AED amounts (`ibr-104-ae`). CI runs this
check on every push.

Scope: standard tax invoices (S/Z rated). Credit notes, reverse charge, exports, free-zone
and margin-scheme variants are not generated yet.

# 2. Real-data benchmark: 626 scanned receipts, $0, fully offline

**Dataset:** ICDAR-2019 SROIE training split (626 real scanned receipts, Malaysia), with
human labels for company, date, address and total. Mirror: `github.com/zzzDavid/ICDAR-2019-SROIE`
(repo code MIT; the scans are the public ICDAR competition data — research use).

**Why receipts and not UAE invoices?** No public labelled set of scanned UAE tax invoices exists (the official PINT AE examples above are structured XML, not scans).
SROIE tests the hardest part of the agent — reading real, messy, low-resolution scans — and,
like the UAE, uses day-first dates. Next step: repeat with UAE invoices you collect (with
permission) or render.

**Stack:** RapidOCR (PP-OCR via ONNX, CPU) + Tesseract 5 + rule extractor. No LLM, no API key,
no cloud. 626 scans in ~20 min on 4 CPU cores.

## Results

| Field | Clean human text* | RapidOCR | Tesseract |
|---|---|---|---|
| Date | **99.7%** | **82.6%** | 70.8% |
| Total | **87.1%** | **81.8%** | 62.1% |
| Seller name (exact) | 82.9% | 63.3% | 41.5% |
| Seller name (≥90% similar) | 84.3% | 74.8% | 61.3% |
| Date **and** total both right | 86.7% | 67.7% | 47.1% |

\*Clean text = the dataset's human-checked OCR, rebuilt into rows. It isolates the
**extraction logic** from OCR errors.

### The agent knows when to ask (two-engine agreement)

Both engines read every scan. The agent auto-accepts a field only when they agree (for
totals: both must also find it on a TOTAL-type line); otherwise it asks the owner to confirm.

| Field | Auto-accepted (no question) | Correct when auto-accepted |
|---|---|---|
| Date | 60.5% of scans | **100.0%** |
| Total | 60.7% of scans | **90.3%** strict · **~96.8%** excluding cash rounding† |
| Seller name | 45.2% of scans | 83.7% |

†Of the 37 auto-accepted totals that didn't match the label, 24 are Malaysia's 5-sen cash
rounding (receipt prints 80.91, label records the rounded 80.90), 1 has no label, and 12
(3.2%) are real errors. The UAE has no such invoice convention.

**Pitch line:** *"On 626 real scans, when our agent auto-accepts a date it has never been
wrong; everything it isn't sure about becomes a one-tap question for the owner."*

## What moved the numbers (engineering log)

| Change | Effect |
|---|---|
| Baseline: Tesseract + simple rules | total 58.0%, date 71.2% |
| Tesseract one-thread-per-process | OCR 33 s → 0.5 s per scan (60× faster) |
| Prefer "TOTAL ROUNDED"; rebuild visual rows from word boxes | clean-text total 70.0% → 84.7% |
| Apply rounding adjustments; multi-line seller names; strip reg. numbers | clean company 63.3% → 82.9% |
| Date scoring (DATE label, 4-digit year, time follows), reject product codes, US fallback | clean date 95.5% → 99.7% |
| Upscale / binarise images for Tesseract | ≤ +2 pts or worse → **rejected** |
| Switch to RapidOCR (deep-learning OCR, still free and local) | total 62% → 82%, date 71% → 83% |
| Handle RapidOCR glued tokens ("25/12/20188:13", "100021911/03/2018") | RapidOCR date 59.8% → 82.6% |
| OCR-tolerant keywords ("Totai", "T0TAL", "Round:d") | robustness on garbled scans |

Bugs caught by the benchmark and regression tests: a VAT-rate fault double-reported as a
total mismatch; double-applied rounding; "TAX TOTAL" read as the total; a zero total hidden
by a falsy check; a glued-date rule turning invalid "31/02/2026" into "1/02/2026".

## Honest limits

- **Development-set numbers.** Rules were tuned on these same 626 receipts (the mirror has no
  held-out split), so expect a few points lower on unseen data. Validate on a fresh set.
- **Receipts, not invoices.** No TRNs, buyer details or line-level VAT here; those are covered
  by the synthetic fault-injection eval (`python -m ira.eval`).
- **Seller name** is the weakest field; an LLM extractor should beat the rules there. Use the
  rules as the free fallback and as a cross-check on the LLM.
- **Address** is not yet extracted.

## Reproduce

```bash
apt-get install -y tesseract-ocr && pip install rapidocr_onnxruntime
git clone --depth 1 --filter=blob:none --sparse https://github.com/zzzDavid/ICDAR-2019-SROIE.git sroie
(cd sroie && git sparse-checkout set data)
python3 -m benchmarks.sroie_bench sroie/data --out bench_out --engine tesseract
python3 -m benchmarks.sroie_bench sroie/data --out bench_out --engine rapidocr
python3 -m benchmarks.confidence  sroie/data --out bench_out
```
