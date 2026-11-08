"""PDF extraction on a rendered (fictional) UAE tax invoice with an LPO-number distractor."""
import json
import unittest
from decimal import Decimal
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

try:
    import pypdfium2  # noqa: F401
except ImportError:  # pragma: no cover
    pypdfium2 = None


@unittest.skipIf(pypdfium2 is None, "pip install pypdfium2")
class TestPdf(unittest.TestCase):
    def test_digital_pdf_full_extraction(self):
        from ira.agent import document_extract
        truth = json.loads((FIX / "uae-tax-invoice-digital.json").read_text())
        d = document_extract(FIX / "uae-tax-invoice-digital.pdf", engine=None)  # no OCR needed
        self.assertEqual(d["_via"], "text-layer")
        self.assertEqual(d["_unconfirmed"], [])
        self.assertEqual(d["invoice_number"], truth["invoice_number"])  # not the LPO number
        self.assertEqual((d["issue_date"], d["due_date"]), (truth["date"], truth["due_date"]))
        self.assertEqual((d["seller"]["trn"], d["buyer"]["trn"]), (truth["seller_trn"], truth["buyer_trn"]))
        self.assertEqual(Decimal(d["gross_total"]), Decimal(truth["total"]))
        self.assertEqual([[Decimal(l["quantity"]), Decimal(l["unit_price"])] for l in d["lines"]],
                         [[Decimal(q), Decimal(p)] for q, p, _ in truth["lines"]])

    def test_pdf_upload_asks_only_what_the_pdf_lacks(self):
        try:
            from fastapi.testclient import TestClient
            from ira.server import app, ws
        except ImportError:
            self.skipTest("web extras not installed")
        ws.clear()
        c = TestClient(app)
        pdf = (FIX / "uae-tax-invoice-digital.pdf").read_bytes()
        r = c.post("/api/invoices/upload", files=[("files", ("inv.pdf", pdf, "application/pdf"))]).json()
        self.assertEqual(r["errors"], [])
        item = r["items"][0]
        self.assertEqual(item["source"], "pdf")
        fields = {q["field"] for q in item["issues"]}
        # Everything printed on the PDF is read; only what isn't printed is asked.
        self.assertFalse(fields & {"invoice_number", "issue_date", "seller.trn", "buyer.trn", "lines"})
        self.assertTrue({"payment_means", "seller.legal_authority"} & fields)


if __name__ == "__main__":
    unittest.main()
