# Invoice Readiness Agent (UAE e-invoicing, PINT-AE)

[![CI](https://github.com/MdIbuA/Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/MdIbuA/Agent/actions/workflows/ci.yml)

**Checked against the official OpenPeppol PINT AE v1.0.3 rules in CI:** 100/100 generated
invoices and credit notes pass; 0 false alarms on the 12 official example documents; 100%
agreement with the official rules on 120 mutated invoices. See [BENCHMARK.md](BENCHMARK.md).

An AI agent that turns messy SME invoices (PDFs, scans, photos, e-invoice XML, JSON) into validated,
structured UBL invoices ready to hand to an Accredited Service Provider (ASP) before
the UAE's 2027 e-invoicing mandate.

**Design principle:** the LLM only *extracts*. Deterministic Python does every
calculation and compliance check, so hallucinated numbers can't reach the output.

```
ingest -> extract (LLM) -> validate (rules) -> ask owner to repair -> re-validate -> UBL XML + report
```

## What the agent does

1. **Reads** PDFs, scans, photos and ERP e-invoice XML (local OCR; optional Gemini only when needed).
2. **Checks** every invoice against the official UAE PINT AE rules and asks only what's missing.
3. **Remembers**: answer a fact about a business once (trade licence, emirate, address, TRN) and the
   agent fills it into every other invoice with that business. In the demo batch, 2 answers fill
   22 fields and lift readiness from 0% to 42%.
4. **Acts for you**: drafts one bilingual (Arabic / English) message per customer asking for all
   their missing details, ready to send by WhatsApp or email. You review and send.
5. **Reports in AED**: a one-page readiness report with indicative penalty exposure (AED 100 per
   invoice not issued electronically on time, capped at AED 5,000 per month) and what's blocking.
6. **Speaks Arabic**: full Arabic interface with right-to-left layout.
7. **Exports** PINT AE UBL XML for your Accredited Service Provider.

## Web app

A full web UI: upload PDFs, scans or ERP e-invoices, see workspace readiness, answer the
agent's questions inline (or confirm everything it read in one tap), and download PINT-AE UBL
XML or an ASP hand-off ZIP. Work is saved to SQLite (`~/.qaid/workspace.db`; set `QAID_DB` to
change it, or `QAID_DB=` to keep everything in memory).

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

## UAE public data

`data/uae_open_data/` holds official UAE open data with sources, checksums and attribution
([SOURCES.md](data/uae_open_data/SOURCES.md)):

- **Ajman DED business-licence register** (61,901 licences, CC BY 4.0): `python scripts/fetch_ajman_licences.py`.
  Used to verify a seller's licence, correct OCR-garbled business and area names, and as real
  names in benchmarks. Over 55% of Ajman licences are single-owner businesses.
- **FTA service activity 2025**: 90,893 VAT registrations and 227,263 Corporate Tax registrations
  processed in 2025 (service counts, not taxpayer totals).

## Optional AI assist (Gemini, free tier)

```bash
export QAID_LLM=1                      # off by default: fully offline without it
export LLM_API_KEY=...                 # Google AI Studio key (free tier)
export LLM_MODEL=gemini-3.5-flash      # default; any OpenAI-compatible endpoint via LLM_BASE_URL
python3 -m ira.server
```

Rules run first; the AI is consulted only when they miss a key field, and fields where rules
and AI agree are accepted while disagreements are confirmed by the owner. On an unseen invoice
layout the AI read 100% of fields where rules alone missed invoice numbers, TRNs and due dates
(see BENCHMARK.md). With AI on, unclear invoices are sent to Google, and the UI says so.

## Layout

| File | Role |
|---|---|
| `ira/models.py` | Invoice data model (Decimal money) + lenient parsing of messy values |
| `ira/validate.py` | Rule engine with stable codes, severities and owner-facing questions |
| `ira/ubl.py` | UBL 2.1 XML generator (VAT grouped by rate) |
| `ira/extract.py` | AI extraction (Gemini / any OpenAI-compatible API) + rules/AI hybrid merge |
| `ira/ubl_import.py` | Reads UBL / PINT AE invoices and credit notes (ERP output) |
| `ira/codelists.py` | Official PINT AE code lists (currencies, units, payment means, credit reasons) |
| `ira/registry.py` | Ajman DED licence register: licence check, name and area correction |
| `scripts/fetch_ajman_licences.py` | Downloads the official Ajman licence register (CC BY 4.0) |
| `ira/ocr.py` | Free local OCR engines: RapidOCR (PP-OCR/ONNX, with deskew) and Tesseract |
| `ira/pdf.py` | PDF text layer (digital) or page rendering for OCR (scanned) |
| `ira/layout.py` | Rebuilds visual rows from OCR word boxes (label/value columns) |
| `ira/rule_extract.py` | Offline extractor: invoice no., dates, TRNs, parties, line items, total |
| `benchmarks/sroie_bench.py` | Accuracy on 626 real scanned receipts (ICDAR-2019 SROIE) |
| `benchmarks/confidence.py` | Two-engine agreement: auto-accept coverage vs precision |
| `benchmarks/pint_ae_check.py` | Validates XML with the official OpenPeppol PINT AE Schematron |
| `benchmarks/agreement.py` | Agent validator vs official rules: official examples + 120 mutants |
| `benchmarks/uae_invoice_pdfs.py` | UAE tax-invoice PDFs (digital + scanned, held-out layouts) |
| `benchmarks/llm_vs_rules.py` | Rules vs AI vs hybrid on an unseen layout |
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
