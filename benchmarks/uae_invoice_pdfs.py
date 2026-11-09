"""Render synthetic UAE tax invoices as PDFs (3 layouts, English + Arabic labels) with
ground truth, then benchmark PDF extraction: digital text layer and scanned (image-only).

    python -m benchmarks.uae_invoice_pdfs make  --out bench_pdf --count 60   # needs Node + Playwright
    python -m benchmarks.uae_invoice_pdfs score --out bench_pdf [--scanned]

Invoices are fictional (ira/synth.py). Layout variety (label wording, Arabic labels, table
styles, TRN formatting) guards against tuning the extractor to a single template.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import subprocess
from decimal import Decimal
from pathlib import Path

from ira.synth import clean_invoice

LAYOUTS = [
    dict(title="TAX INVOICE", ar="فاتورة ضريبية", no="Invoice No:", date="Invoice Date:", due="Due Date:",
         trn="TRN:", bill="Bill To", total="Total Amount Due (AED)", sub="Subtotal", vat="VAT 5%",
         trn_fmt=lambda t: f"{t[:3]} {t[3:7]} {t[7:11]} {t[11:]}", accent="#0f766e"),
    dict(title="Tax Invoice", ar="فاتورة ضريبية", no="Inv #", date="Date of Issue", due="Payment Due",
         trn="VAT Reg. No.", bill="Customer", total="Grand Total AED", sub="Taxable Amount", vat="VAT @ 5%",
         trn_fmt=lambda t: t, accent="#1d4ed8"),
    dict(title="TAX INVOICE / فاتورة ضريبية", ar="", no="رقم الفاتورة Invoice Number", date="Date", due="Due On",
         trn="TRN", bill="Sold To / العميل", total="TOTAL (AED)", sub="Net Amount", vat="VAT Amount",
         trn_fmt=lambda t: f"{t[:4]}-{t[4:8]}-{t[8:12]}-{t[12:]}", accent="#7c2d12"),
]


# Held-out layout: never used while tuning the extractor. Report its score as-is.
HOLDOUT_LAYOUT = dict(title="INVOICE (TAX)", ar="فاتورة ضريبية", no="Invoice Ref.", date="Issued On",
                      due="Payment Terms: due", trn="Tax Registration Number", bill="Customer Details:",
                      total="Amount Payable AED", sub="Total excl. VAT", vat="VAT (5%)",
                      trn_fmt=lambda t: f"{t[:5]} {t[5:10]} {t[10:]}", accent="#4338ca")


# Second held-out layout, written after the vocabulary fix; includes an LPO number distractor.
HOLDOUT2_LAYOUT = dict(title="Tax Invoice", ar="فاتورة ضريبية", no="Tax Invoice No.", date="Dated",
                       due="Due Date", trn="Supplier TRN", bill="Customer", total="Net Amount Payable",
                       sub="Sub Total", vat="Add: VAT 5%", trn_fmt=lambda t: t, accent="#065f46",
                       buyer_trn="Customer TRN", lpo=True)


# Third held-out layout, written for the rules-vs-LLM comparison; unusual wording on purpose.
HOLDOUT3_LAYOUT = dict(title="VAT INVOICE", ar="فاتورة ضريبية", no="Our Invoice", date="Dt.",
                       due="Credit terms: payable before", trn="Tax Reg. #", bill="Ship & Bill to",
                       total="BALANCE (AED)", sub="Amount before tax", vat="Output VAT",
                       trn_fmt=lambda t: f"{t[:3]}.{t[3:9]}.{t[9:]}", accent="#9d174d", quote=True)


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def render_html(inv: dict, layout: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(l['description'])}</td><td class=r>{l['quantity']}</td><td class=r>{l['unit_price']}</td>"
        f"<td class=r>{Decimal(l['vat_rate']):.0f}%</td><td class=r>{l['line_total']}</td></tr>" for l in inv["lines"])
    s, b, L = inv["seller"], inv["buyer"], layout
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{font-family:'DejaVu Sans',sans-serif;font-size:11px;color:#111;margin:36px}}
h1{{color:{L['accent']};font-size:20px;margin:0}} .ar{{font-size:16px;color:{L['accent']}}}
.hdr{{display:flex;justify-content:space-between;border-bottom:2px solid {L['accent']};padding-bottom:10px}}
table{{width:100%;border-collapse:collapse;margin-top:18px}} th,td{{border-bottom:1px solid #ccc;padding:6px;text-align:left}}
th{{background:#f3f4f6}} .r{{text-align:right}} .tot td{{border:0}} .grand{{font-weight:bold;font-size:13px}}
.box{{margin-top:16px;padding:10px;background:#fafafa;border:1px solid #eee;width:55%}}
</style></head><body>
<div class=hdr><div><strong style="font-size:15px">{e(s['name'])}</strong><br>{e(s['address'])}<br>
{e(L['trn'])} {L['trn_fmt'](s['trn'])}<br>Trade Licence {e(s['legal_id'])}</div>
<div style="text-align:right"><h1>{e(L['title'])}</h1><div class=ar>{L['ar']}</div>
{('LPO No. 45' + inv['invoice_number'][-4:] + '<br>') if L.get('lpo') else ''}{('Quotation Ref Q-2026-' + inv['invoice_number'][-3:] + '7<br>') if L.get('quote') else ''}{e(L['no'])} {e(inv['invoice_number'])}<br>{e(L['date'])} {_dmy(inv['issue_date'])}<br>
{e(L['due'])} {_dmy(inv['due_date'])}</div></div>
<div class=box><strong>{e(L['bill'])}</strong><br>{e(b['name'])}<br>{e(b['address'])}<br>
{e(L.get('buyer_trn', L['trn']))} {L['trn_fmt'](b['trn'])}</div>
<table><tr><th>Description</th><th class=r>Qty</th><th class=r>Unit Price</th><th class=r>VAT</th><th class=r>Amount (AED)</th></tr>
{rows}</table>
<table class=tot style="width:45%;margin-left:auto">
<tr><td>{e(L['sub'])}</td><td class=r>{inv['net_total']}</td></tr>
<tr><td>{e(L['vat'])}</td><td class=r>{inv['vat_total']}</td></tr>
<tr class=grand><td>{e(L['total'])}</td><td class=r>{inv['gross_total']}</td></tr></table>
<p style="margin-top:30px;color:#666">Payment by bank transfer. Thank you for your business.</p>
</body></html>"""


RENDER_JS = r"""
const { chromium } = require('playwright');
const dir = process.argv[2];
(async () => {
  const fs = require('fs'), path = require('path');
  const b = await chromium.launch(); const p = await b.newPage();
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
    await p.goto('file://' + path.resolve(dir, f));
    await p.pdf({ path: path.resolve(dir, f.replace('.html', '.pdf')), format: 'A4', printBackground: true });
  }
  await b.close();
})();
"""


def _real_parties(rng: random.Random):
    """Seller/buyer from the official Ajman DED licence register (data/uae_open_data)."""
    import csv
    path = Path(__file__).resolve().parent.parent / "data" / "uae_open_data" / "ajman_licences.csv"
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig"))
            if r["tradenameen"] and r["tradenameen"] != "NULL" and r["areaen"] and r["areaen"] != "NULL"]

    def party(r):
        return {"name": " ".join(r["tradenameen"].split()), "address": f"{' '.join(r['areaen'].split())}, Ajman",
                "legal_id": r["licensenumber"].split(".")[0],
                "legal_authority": "Ajman Department of Economic Development"}
    while True:
        a, b = rng.sample(rows, 2)
        yield party(a), party(b)


def make(out: Path, count: int, seed: int, holdout: int = 0, real_names: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    truth = {}
    parties = _real_parties(random.Random(seed + 1)) if real_names else None
    for n in range(1, count + 1):
        inv = clean_invoice(rng, n)
        if parties:
            sp, bp = next(parties)
            inv["seller"].update(sp)
            inv["buyer"].update({k: bp[k] for k in ("name", "address")})
        name = f"uae-{n:03d}"
        layout = {1: HOLDOUT_LAYOUT, 2: HOLDOUT2_LAYOUT, 3: HOLDOUT3_LAYOUT}.get(holdout) or LAYOUTS[n % len(LAYOUTS)]
        (out / f"{name}.html").write_text(render_html(inv, layout), encoding="utf-8")
        truth[name] = {"invoice_number": inv["invoice_number"], "date": inv["issue_date"],
                       "due_date": inv["due_date"], "total": inv["gross_total"], "company": inv["seller"]["name"],
                       "seller_trn": inv["seller"]["trn"], "buyer_trn": inv["buyer"]["trn"],
                       "buyer_name": inv["buyer"]["name"], "seller_address": inv["seller"]["address"],
                       "buyer_address": inv["buyer"]["address"],
                       "lines": [[l["quantity"], l["unit_price"], l["line_total"]] for l in inv["lines"]],
                       "layout": f"holdout{holdout}" if holdout else n % len(LAYOUTS),
                       "seller_licence": inv["seller"]["legal_id"]}
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    js = out / "render.cjs"
    js.write_text(RENDER_JS)
    subprocess.run(["node", str(js), str(out)], check=True)
    for f in out.glob("*.html"):
        f.unlink()
    js.unlink()
    # Scanned variants: rasterise, rotate slightly, add blur/noise, save as image-only PDF.
    import pypdfium2 as pdfium
    from PIL import ImageFilter
    scan_dir = out / "scanned"
    scan_dir.mkdir(exist_ok=True)
    for pdf in sorted(out.glob("uae-*.pdf")):
        img = pdfium.PdfDocument(str(pdf))[0].render(scale=150 / 72).to_pil().convert("L")
        img = img.rotate(rng.uniform(-1.5, 1.5), expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
        img.save(scan_dir / pdf.name, "PDF", resolution=150)


FIELDS = ("invoice_number", "date", "due_date", "total", "company", "seller_trn", "buyer_trn",
          "buyer_name", "seller_address", "buyer_address", "lines")


def score(out: Path, scanned: bool, register: bool = False) -> dict:
    from ira.ocr import ENGINES
    from ira.pdf import pdf_to_text
    from ira.rule_extract import extract
    truth = json.loads((out / "truth.json").read_text())
    folder = out / "scanned" if scanned else out
    hits = {f: 0 for f in FIELDS}
    modes, per_layout = {}, {}
    misses = []
    for name, t in truth.items():
        text, mode = pdf_to_text(folder / f"{name}.pdf", ENGINES["rapidocr"])
        modes[mode] = modes.get(mode, 0) + 1
        got = extract(text)
        if register:  # correct party names against the official Ajman licence register
            from ira.registry import snap_parties
            got, _ = snap_parties(got)
        for f in FIELDS:
            if f == "total":
                ok = bool(got[f]) and Decimal(got[f]) == Decimal(t[f])
            elif f == "lines":  # every line item found with exact quantity, price and amount
                ok = [[Decimal(a), Decimal(b), Decimal(c)] for a, b, c in t["lines"]] == \
                     [[Decimal(l["quantity"]), Decimal(l["unit_price"]), Decimal(l["line_total"])] for l in got["lines"]]
            elif f in ("company", "buyer_name", "seller_address", "buyer_address"):  # ignore spacing/punctuation
                norm = lambda v: re.sub(r"[^A-Z0-9]", "", (v or "").upper())
                ok = norm(got[f]) == norm(t[f])
            else:
                ok = got.get(f) == t[f]
            hits[f] += ok
            per_layout.setdefault(t["layout"], {}).setdefault(f, 0)
            per_layout[t["layout"]][f] += ok
            if not ok:
                misses.append((name, f, t[f], got.get(f)))
    n = len(truth)
    return {"documents": n, "mode": modes, "accuracy_pct": {f: round(100 * h / n, 1) for f, h in hits.items()},
            "all_fields_pct": None, "misses": misses[:25]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "score"])
    ap.add_argument("--out", type=Path, default=Path("bench_pdf"))
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--seed", type=int, default=971)
    ap.add_argument("--scanned", action="store_true")
    ap.add_argument("--holdout", type=int, default=0, choices=[0, 1, 2, 3], help="render a held-out layout")
    ap.add_argument("--real-names", action="store_true", help="sellers/buyers from the Ajman licence register")
    ap.add_argument("--register", action="store_true", help="score with register-based name correction")
    a = ap.parse_args()
    if a.cmd == "make":
        make(a.out, a.count, a.seed, a.holdout, a.real_names)
        print(f"wrote {a.count} PDFs (+ scanned variants) to {a.out}")
    else:
        r = score(a.out, a.scanned, a.register)
        print(json.dumps({k: v for k, v in r.items() if k != "misses"}, indent=1))
        for m in r["misses"]:
            print("  miss", m)


if __name__ == "__main__":
    main()
