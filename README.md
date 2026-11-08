# Invoice Readiness Agent (UAE e-invoicing, PINT-AE)

[![CI](https://github.com/MdIbuA/Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/MdIbuA/Agent/actions/workflows/ci.yml)

**100/100 generated invoices pass the official OpenPeppol PINT AE v1.0.3 Schematron** (checked in CI).

An AI agent that turns messy SME invoices (photos, PDFs, Excel, text) into validated,
structured UBL invoices ready to hand to an Accredited Service Provider (ASP) before
the UAE's 2027 e-invoicing mandate.

**Design principle:** the LLM only *extracts*. Deterministic Python does every
calculation and compliance check, so hallucinated numbers can't reach the output.

```
ingest -> extract (LLM) -> validate (rules) -> ask owner to repair -> re-validate -> UBL XML + report
```

## Web app

A full web UI: upload scans or exports, see workspace readiness, answer the agent's
questions inline, and download PINT-AE UBL XML or an ASP hand-off ZIP.

```bash
pip install -r requirements.txt
(cd web && npm ci && npm run build)     # React + TypeScript UI -> web/dist
python3 -m ira.server                   # http://127.0.0.1:8000  · API docs at /docs
```

UI development with hot reload: run `python3 -m ira.server` and, in another terminal,
`cd web && npm run dev` (http://127.0.0.1:5173, proxies `/api` to the server).

| Layer | Stack |
|---|---|
| UI | React 19, TypeScript (strict), Vite, hand-built design system (light/dark, responsive, keyboard accessible) |
| API | FastAPI: typed endpoints, upload limits, OpenAPI docs |
| Agent | Python: OCR, extraction, deterministic validation, UBL generation |

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
| `benchmarks/pint_ae_check.py` | Validates XML with the official OpenPeppol PINT AE Schematron |
| `ira/agent.py` | Orchestrator, human-in-the-loop repair, readiness report |
| `ira/service.py` | Workspace: stores invoices, applies owner answers, re-validates |
| `ira/server.py` | FastAPI app: REST API + serves the built web UI |
| `web/` | React + TypeScript frontend |
| `ira/synth.py` | Synthetic invoices with known injected faults |
| `ira/eval.py` | Accuracy harness |

## Status / TODO before submission

- Generated XML passes the official PINT AE Schematron for standard tax invoices; credit notes,
  reverse charge, exports, free-zone and margin-scheme variants are not generated yet.
- Validate XML output against the OASIS UBL 2.1 XSD.
- Exempt supplies, reverse charge, credit notes and non-AED currency need full handling.
- Add PDF/XLSX ingest, Arabic samples, TRN memory (SQLite), Streamlit UI.

This tool prepares data; it does not transmit to Peppol. Only accredited ASPs may do that.
