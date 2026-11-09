"""Business profile (set once, applied everywhere) and Excel/CSV register import."""
import unittest
from pathlib import Path

from ira.service import Workspace
from ira.spreadsheet import parse_register
from ira.synth import demo_batch

FIX = Path(__file__).parent / "fixtures"
PROFILE = {"name": "Al Noor Building Materials LLC", "trn": None, "legal_id": "784512",
           "legal_authority": "Dubai Department of Economy and Tourism", "address": "Deira, Dubai",
           "emirate": "Dubai", "payment_means": "bank transfer", "payment_terms_days": "30"}


class TestRegisters(unittest.TestCase):
    def test_english_lines_with_title_rows_and_excel_dates(self):
        invs, info = parse_register((FIX / "register_lines_en.xlsx").read_bytes(), "register_lines_en.xlsx")
        self.assertEqual((info["headerRow"], info["invoices"]), (3, 2))
        a = invs[0]
        self.assertEqual((a["invoice_number"], a["issue_date"], a["buyer"]["trn"]), ("AN-201", "2026-03-05", "100465234127103"))
        self.assertEqual([(l["quantity"], l["vat_rate"]) for l in a["lines"]], [("10", "5"), ("1", "5")])

    def test_arabic_headers_one_row_per_invoice(self):
        invs, info = parse_register((FIX / "register_invoices_ar.csv").read_bytes(), "register_invoices_ar.csv")
        self.assertEqual(info["columns"]["رقم الفاتورة"], "invoice_number")
        self.assertEqual([(i["invoice_number"], i["payment_means"]) for i in invs], [("INV-7", "30"), ("INV-8", "20")])
        self.assertEqual(invs[0]["lines"][0]["unit_price"], "1000.00")

    def test_informal_headers_and_totals_row_skipped(self):
        invs, info = parse_register((FIX / "register_informal.csv").read_bytes(), "register_informal.csv")
        self.assertEqual([i["invoice_number"] for i in invs], ["S-1001", "S-1002"])
        self.assertEqual(info["skippedRows"], 1)
        self.assertEqual(invs[0]["gross_total"], "1260.00")

    def test_sheet_without_invoice_column_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_register(b"Name,Phone\nA,1\n", "contacts.csv")


class TestProfile(unittest.TestCase):
    def test_profile_fills_own_register_and_due_dates(self):
        ws = Workspace()
        ws.set_profile(PROFILE)
        invs, _ = parse_register((FIX / "register_lines_en.xlsx").read_bytes(), "x.xlsx")
        rec = ws.get(ws.add_dicts(invs, "spreadsheet")[0]["id"])
        self.assertEqual((rec.invoice.seller.name, rec.invoice.seller.legal_id, rec.invoice.seller.emirate),
                         ("Al Noor Building Materials LLC", "784512", "DXB"))
        self.assertEqual((rec.invoice.payment_means, rec.invoice.due_date), ("30", "2026-04-04"))
        self.assertEqual(rec.learned.get("seller.legal_id"), "profile")

    def test_profile_applies_to_existing_invoices_and_never_overwrites(self):
        ws = Workspace()
        ids = [i["id"] for i in ws.add_dicts(demo_batch(), "sample")]
        r = ws.set_profile(PROFILE)
        self.assertEqual(r["updatedInvoices"], 12)
        self.assertEqual(ws.summary()["readinessPct"] > 0, True)
        rec = ws.get(ids[0])
        self.assertEqual(rec.invoice.seller.address, "Deira, Dubai")  # already there: kept, not overwritten
        self.assertEqual(rec.invoice.seller.legal_id, "784512")

    def test_scanned_purchase_invoice_from_another_seller_untouched(self):
        ws = Workspace()
        ws.set_profile(PROFILE)
        rid = ws.add_dicts([{"invoice_number": "X1", "seller": {"name": "Some Supplier LLC"}, "buyer": {}, "lines": []}], "scan")[0]["id"]
        self.assertIsNone(ws.get(rid).invoice.seller.legal_id)

    def test_address_answer_fills_emirate(self):
        ws = Workspace()
        invs, _ = parse_register((FIX / "register_lines_en.xlsx").read_bytes(), "x.xlsx")
        rid = ws.add_dicts(invs[:1], "spreadsheet")[0]["id"]
        ws.answer(rid, "buyer.address", "Al Khalidiyah, Abu Dhabi")
        self.assertEqual(ws.get(rid).invoice.buyer.emirate, "AUH")
        self.assertNotIn("MISSING_BUYER_EMIRATE", [i.code for i in ws.get(rid).issues()])

    def test_profile_emirate_inferred_from_address(self):
        r = Workspace().set_profile({"name": "X Trading LLC", "address": "Al Nahda, Sharjah"})
        self.assertEqual(r["profile"]["emirate"], "SHJ")

    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):
            Workspace().set_profile({**PROFILE, "trn": "123"})


if __name__ == "__main__":
    unittest.main()
