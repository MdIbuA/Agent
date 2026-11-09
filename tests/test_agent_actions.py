"""Agent memory (answer once, applied to the same party), customer requests, readiness report."""
import random
import unittest

from ira.service import Workspace, outreach, report
from ira.synth import clean_invoice


def invoices_same_seller(n=3, drop=("legal_id",)):
    rng, out = random.Random(8), []
    while len(out) < n:
        d = clean_invoice(rng, len(out) + 1)
        if out and d["seller"]["name"] != out[0]["seller"]["name"]:
            continue
        for f in drop:
            d["seller"][f] = None
        out.append(d)
    return out


class TestAgentMemory(unittest.TestCase):
    def test_seller_fact_applied_to_all_invoices_of_that_seller(self):
        ws = Workspace()
        ids = [i["id"] for i in ws.add_dicts(invoices_same_seller(3), "sample")]
        r = ws.answer(ids[0], "seller.legal_id", "784512")
        self.assertEqual(sorted(r["appliedTo"]), sorted(ids[1:]))
        for rid in ids[1:]:
            rec = ws.get(rid)
            self.assertEqual(rec.invoice.seller.legal_id, "784512")
            self.assertEqual(rec.learned, {"seller.legal_id": ids[0]})

    def test_never_overwrites_and_never_copies_per_invoice_fields(self):
        ws = Workspace()
        docs = invoices_same_seller(2)
        docs[1]["seller"]["legal_id"] = "111111"
        docs[0]["due_date"] = docs[1]["due_date"] = None
        a, b = [i["id"] for i in ws.add_dicts(docs, "sample")]
        self.assertEqual(ws.answer(a, "seller.legal_id", "222222")["appliedTo"], [])
        self.assertEqual(ws.get(b).invoice.seller.legal_id, "111111")
        self.assertEqual(ws.answer(a, "due_date", "01/12/2026")["appliedTo"], [])
        self.assertIsNone(ws.get(b).invoice.due_date)


class TestOutreachAndReport(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        docs = []
        rng = random.Random(3)
        while len(docs) < 3:
            d = clean_invoice(rng, len(docs) + 1)
            if docs and d["buyer"]["name"] != docs[0]["buyer"]["name"]:
                continue
            d["buyer"]["trn"] = None
            docs.append(d)
        self.ws.add_dicts(docs, "sample")

    def test_one_bilingual_request_per_customer(self):
        reqs = outreach(self.ws)
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual(len(r["invoices"]), 3)
        self.assertEqual(r["needs"], ["buyer.trn"])
        self.assertIn("Tax Registration Number", r["messageEn"])
        self.assertIn("رقم التسجيل الضريبي", r["messageAr"])

    def test_report_exposure_is_capped_per_month(self):
        r = report(self.ws)
        self.assertEqual(r["notReady"], 3)
        months = r["exposureByMonth"]
        expected = sum(min(100 * n, 5000) for n in months.values())
        self.assertEqual(r["exposureAed"], expected)
        self.assertEqual(r["topIssues"][0]["code"], "MISSING_BUYER_TRN")
        self.assertEqual(r["customerRequests"], 1)


if __name__ == "__main__":
    unittest.main()
