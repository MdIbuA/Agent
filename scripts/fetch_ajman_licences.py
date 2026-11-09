"""Download the official Ajman DED business-licence register (UAE open data, CC BY 4.0).

    python scripts/fetch_ajman_licences.py          # -> data/uae_open_data/ajman_licences.csv

Source: Ajman Department of Economic Development, dataset "license-in-ajman-area" on the
Ajman Open Data portal. ~62k licences: number, trade name (EN/AR), legal form, licence type,
area, start date. Attribution required (CC BY 4.0): "Contains data from Ajman Open Data
(data.ajman.ae), Department of Economic Development - Ajman, CC BY 4.0."

Polite by design: one CSV export request, retried with growing pauses. Some networks
(e.g. cloud data centres) are refused by the portal; run it from a normal connection.
"""
from __future__ import annotations

import csv
import hashlib
import io
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

URL = ("https://data.ajman.ae/api/explore/v2.1/catalog/datasets/license-in-ajman-area/exports/csv"
       "?delimiter=%2C&select=licensenumber,tradenameen,tradenamear,legalformen,legalformar,"
       "licensetypeen,areaen,startdate")
OUT = Path(__file__).resolve().parent.parent / "data" / "uae_open_data" / "ajman_licences.csv"


def main() -> int:
    for attempt in range(1, 7):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "qaid-invoice-agent/0.1 (open-data fetch)"})
            data = urllib.request.urlopen(req, timeout=300).read()
            rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
            if len(rows) < 1000:
                raise ValueError(f"only {len(rows)} rows returned")
            OUT.write_bytes(data)
            print(f"Saved {len(rows):,} licences to {OUT}")
            print(f"Retrieved {date.today()}  sha256 {hashlib.sha256(data).hexdigest()}")
            return 0
        except Exception as e:  # noqa: BLE001 - report and back off on any network/parse failure
            wait = 10 * attempt
            print(f"attempt {attempt} failed: {e}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print("Could not download the register from this network.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
