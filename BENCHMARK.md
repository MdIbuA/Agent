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

Generated documents now include **credit notes** (official reason codes, reference to the
original invoice): 100/100 pass (80 invoices + 20 credit notes).

### Does the agent's own validator agree with the official rules? (`benchmarks/agreement.py`)

The agent validates invoices itself (so it can ask the owner plain-language questions), so it
must neither block valid UAE invoices nor wave through invalid ones.

| Test | Result |
|---|---|
| False alarms on the 12 official example documents (standard, zero-rated, reverse charge, export in USD, free zone, e-commerce, margin scheme, summary, out-of-scope, 2 credit notes) | **0** |
| 120 mutants: each official invoice with one injected error (12 error types) | **100% agreement**, 100% recall, never stricter than official |

Getting there exposed real UAE rules the agent had wrong: reverse-charge and margin-scheme
lines carry 5% but no VAT is charged by the seller; VAT is computed per category after
document-level discounts and charges (not per line); foreign and unregistered buyers have no
TRN; the official payment-means list (cheque yes, generic "bank card" no); emirate must be
stated in e-invoice XML, never inferred; credit notes need an official reason code
(Art. 61 cases) and a reference to the original invoice. Code lists (ISO 4217, ISO 3166,
UN/ECE Rec 20, payment means, credit reasons, transaction flags) are extracted from the
official bundle into `ira/codelists.py`.

Scope: the agent *validates* all official document types, and *generates* standard,
zero-rated invoices and credit notes. Generating reverse-charge, export, free-zone and
margin-scheme documents is not implemented yet.

## 2. UAE tax-invoice PDFs: digital and scanned (`benchmarks/uae_invoice_pdfs.py`)

No public set of labelled UAE invoice PDFs exists, so fictional invoices are rendered as
realistic bilingual "Tax Invoice / فاتورة ضريبية" PDFs (headless Chromium), plus scanned
variants (150 dpi, ±1.5° rotation, blur) saved as image-only PDFs. 11 fields are scored.

| Set | Fields at 100% | Lowest field |
|---|---|---|
| Tuned layouts (3), digital, 60 docs | **11 / 11** | — |
| Tuned layouts, scanned | date, due date, total, company, both TRNs, seller address | invoice no. 83% (OCR letter case), line items 98% |
| **Held-out layout #1, first run (before any fix)** | dates, company, TRNs, parties, lines | **invoice no. 0%, due date 0%, total 53%** |
| **Held-out layout #2 (fresh), digital** | **11 / 11** (incl. an LPO-number distractor) | — |
| Held-out layout #2, scanned | date, due, total, TRNs, parties | invoice no. 77%, company 93%, lines 97% |

What the held-out run taught: the first rule vocabulary was overfitted to my own templates
("Invoice Ref.", "Amount Payable", "Payment Terms: due" were unknown, and the pre-VAT total
was picked in 47% of cases). After broadening the vocabulary with common real-world labels,
a *second, fresh* held-out layout scored 100% digital. Rule-based extraction will still meet
unseen wordings in the wild; the LLM extractor (`ira/extract.py`) is the generalising path,
with the rules kept as a free fallback and cross-check. Wrong totals are not silently
accepted: the validator recomputes VAT and totals from the line items.

Scanned-specific fixes: deskewing OCR boxes by their median angle (scanned line items 25% →
98%), deriving a dropped single-digit quantity exactly (amount ÷ price, whole numbers only),
labels tolerant of OCR I/l confusion, buyer block anchored on the buyer TRN when the heading
is lost, document titles cut from merged header rows. The 626-receipt benchmark below was
re-run after these changes: no regression beyond one receipt (total 87.1% → 86.9%).

## 2b. Rules vs AI vs hybrid on an unseen layout (`benchmarks/llm_vs_rules.py`)

Held-out layout #3 (20 invoices), written for this comparison with unusual wording ("Our
Invoice", "Dt.", TRN printed with dots, "Credit terms: payable before", "BALANCE (AED)") and
a quotation-number distractor. Neither the rules nor the AI prompt were tuned on it.

| Field | Digital: rules | Digital: AI (gemini-3.5-flash, text) | Scanned: rules (OCR) | Scanned: AI (gemini-3.5-flash-lite, vision) |
|---|---|---|---|---|
| Invoice number | 0% | **100%** | 0% | **100%** |
| Issue date | 100% | **100%** | 0% | **100%** |
| Due date | 0% | **100%** | 0% | **100%** |
| Total | 50% | **100%** | 50% | **100%** |
| Seller / buyer TRN | 0% / 0% | **100% / 100%** | 0% / 0% | **100% / 100%** |
| Company, parties, addresses, line items | 100% | **100%** | 0–100% | **100%** |

**Hybrid** (auto-accept where rules and AI agree, otherwise ask the owner with the AI value
pre-filled): auto-accepted 55% (digital) / 33% (scanned) of fields, **100% of those correct**;
every final value correct after confirmation.

How the agent uses this (opt-in, `QAID_LLM=1`): rules first; the AI is called **only when the
rules miss a key field** (invoice number, date, total, seller, a valid seller TRN, or line
items). On familiar layouts the rules score 100%, so most invoices cost no AI call. Any AI
failure (quota, offline, bad reply) falls back to rules-only.

Caveats: 20 documents per set; one rendered layout; model behaviour changes over time (model
names recorded in `benchmarks/results/`). The Gemini free tier allowed **20 requests per day
per model** when this was run, enough for a demo, not for production volumes. With AI on,
unclear invoices are sent to Google; the UI says so.

## 2c. Real UAE business names (official Ajman DED licence register)

45 invoices rendered with **real Ajman licence holders** as seller and buyer (names are ALL CAPS,
abbreviated, often without a legal suffix, sometimes long enough to wrap). Rules-only vs rules +
register-based correction (`--register`): OCR-tolerant matching against the 61,901 registered
trade names and official area names.

| Field | Digital: rules | Digital: + register | Scanned: rules | Scanned: + register |
|---|---|---|---|---|
| Seller name | 100% | 100% | 93.3% | **95.6%** |
| Buyer name | 97.8% | **100%** | 86.7% | **97.8%** |
| Seller address | 100% | 100% | 53.3% | **95.6%** |
| Buyer address | 100% | 100% | 64.4% | **100%** |
| Dates, total, TRNs, line items | 98–100% | 98–100% | 98–100% | 98–100% |
| Invoice number | 97.8% | 97.8% | 80% | 80% (OCR letter case → owner confirms) |

Real names exposed real issues, all fixed: the official CSV export starts with a byte-order mark,
so the full register loaded **0** licences (tests now cover the full file); long trade names wrap
onto a second line ("… L.L.C (SOLE" / "PROPRIETORSHIP)") and are now joined, but never with an
address, tax-ID or date line (OCR turned a real "{L.L.C" into "(L.L.C" and glued on the address).

# 3. Real-data benchmark: 626 scanned receipts, $0, fully offline

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
