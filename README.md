# Invoice Readiness Agent (UAE e-invoicing, PINT-AE)

An AI agent that turns messy SME invoices (photos, PDFs, Excel, text) into validated,
structured UBL invoices ready to hand to an Accredited Service Provider (ASP) before
the UAE's 2027 e-invoicing mandate.

**Design principle:** the LLM only *extracts*. Deterministic Python does every
calculation and compliance check, so hallucinated numbers can't reach the output.

```
ingest -> extract (LLM) -> validate (rules) -> ask owner to repair -> re-validate -> UBL XML + report
```

## Quick start (no API key needed)

```bash
python3 -m unittest                                  # run tests
python3 -m ira.synth                                 # create 50 synthetic messy invoices
python3 -m ira.agent data/synthetic_invoices.json    # validate + emit XML + readiness report
python3 -m ira.agent data/synthetic_invoices.json --interactive   # owner fixes errors live
python3 -m ira.eval                                  # precision / recall on injected faults
```

## Real scans, fully offline (no API key, $0)

```bash
apt-get install -y tesseract-ocr && pip install rapidocr_onnxruntime
python3 -m ira.agent path/to/scans --ocr both --interactive
```

Two independent OCR engines read every scan. Fields they agree on are auto-accepted;
fields they disagree on become a confirmation question for the owner. See
[BENCHMARK.md](BENCHMARK.md) for accuracy on 626 real scanned receipts.

## With a free LLM tier (real files)

```bash
export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai   # or Groq/OpenRouter
export LLM_API_KEY=...        # free key
export LLM_MODEL=...          # a vision-capable model for photos
python3 -m ira.agent path/to/invoices/ --llm --interactive
```

Use **synthetic invoices only** on free tiers (they may log data).

## Layout

| File | Role |
|---|---|
| `ira/models.py` | Invoice data model (Decimal money) + lenient parsing of messy values |
| `ira/validate.py` | Rule engine with stable codes, severities and owner-facing questions |
| `ira/ubl.py` | UBL 2.1 XML generator (VAT grouped by rate) |
| `ira/extract.py` | LLM extraction via any OpenAI-compatible endpoint |
| `ira/ocr.py` | Free local OCR engines: RapidOCR (PP-OCR/ONNX) and Tesseract |
| `ira/layout.py` | Rebuilds visual rows from OCR word boxes (label/value columns) |
| `ira/rule_extract.py` | Offline extractor for date / total / seller; LLM cross-check and fallback |
| `benchmarks/sroie_bench.py` | Accuracy on 626 real scanned receipts (ICDAR-2019 SROIE) |
| `benchmarks/confidence.py` | Two-engine agreement: auto-accept coverage vs precision |
| `ira/agent.py` | Orchestrator, human-in-the-loop repair, readiness report |
| `ira/synth.py` | Synthetic invoices with known injected faults |
| `ira/eval.py` | Accuracy harness |

## Status / TODO before submission

- Rules are a **core subset**. Map every rule to the official PINT-AE data dictionary and add the rest.
- Verify `CUSTOMIZATION_ID` / `PROFILE_ID` in `ira/ubl.py` against the official spec.
- Validate XML output against the OASIS UBL 2.1 XSD.
- Exempt supplies, reverse charge, credit notes and non-AED currency need full handling.
- Add PDF/XLSX ingest, Arabic samples, TRN memory (SQLite), Streamlit UI.

This tool prepares data; it does not transmit to Peppol. Only accredited ASPs may do that.
