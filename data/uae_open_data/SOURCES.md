# UAE public data used by the agent

All files here come from official UAE government open-data publications. They are kept
verbatim or converted without changing values; conversions are reproducible from the
original file and checksum below.

## 1. FTA service activity 2025 — `fta_service_activity_2025.csv`

- **Publisher:** Federal Tax Authority (FTA), UAE — Open Data page `https://tax.gov.ae/en/open.data.aspx`
- **Original file:** `https://tax.gov.ae/Datafolder/Files/Pdf/2026/open-data/Open%20data%202025%20full%20year%20-%20final.xlsx`
- **Retrieved:** 2026-11-09 · SHA-256 of original: `bc75b05e88f94b9139eaead25ab71d738f77bab5ca34d39d5a33c9cf7542fb2a`
- **Content:** quarterly counts of FTA services processed in 2025 (VAT registration 90,893;
  VAT de-registration 12,045; Corporate Tax registration 227,263; …). Rows reconcile exactly
  to the workbook's grand total (354,874).
- **Caveat:** these are counts of **service transactions**, not the number of registered
  taxpayers, and not tax revenue.

## 2. Ajman business licences — `ajman_licences_sample.csv` (+ full register via script)

- **Publisher:** Department of Economic Development – Ajman, dataset `license-in-ajman-area`
  ("License in Ajman (Area)") on Ajman Open Data, `https://data.ajman.ae`
- **Licence:** CC BY 4.0 — *Contains data from Ajman Open Data (data.ajman.ae), Department of
  Economic Development – Ajman, CC BY 4.0.*
- **Size:** 61,901 licences (metadata modified 2026-09-28): licence number, trade name in English
  and Arabic, legal form, licence type, area, start date.
- **In this repo:** a small sample of real records returned by the official API (for tests).
  The full register is fetched by `python scripts/fetch_ajman_licences.py` into
  `ajman_licences.csv` (git-ignored, ~12 MB). Fetched successfully on 2026-11-09 (61,901
  licences, export SHA-256 `86ee05741d5228398f41539f1477b02b2f8387118f69dbf1cc441d9a997a5361`)
  after the portal first reset several connections; the script retries politely.
- **Profile (2026-11-09):** sole establishments 44.8%, LLC 40.5%, LLC (sole proprietorship) 10.7%
  → over 55% single-owner businesses; licence types: professional 53.8%, trade 42.4%,
  industrial 2.9%; 7,667 licences started in 2025.
- **Used for** (`ira/registry.py`):
  1. an advisory check: when the seller's licence was issued in Ajman, the number is looked
     up and the registered trade name compared with the invoice (warnings, never blocking);
  2. correcting OCR-garbled party names and area names to their registered form and
     suggesting the seller's licence number, always put to the owner to confirm;
  3. a real-names benchmark: invoices rendered with real Ajman licence holders as seller and
     buyer (`benchmarks/uae_invoice_pdfs.py --real-names`).

## Not usable from the development machine

- **Dubai Pulse** (`dubaipulse.gov.ae`, DET mainland licence master, ~189 MB): connections from
  the cloud machine were dropped during TLS, and the dataset also requires an access request
  (approval up to 14 days).
