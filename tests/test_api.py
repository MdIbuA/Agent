"""API tests. Skipped automatically if the web extras aren't installed."""
import json
import unittest

try:
    from fastapi.testclient import TestClient
    from ira.server import app, ws
except ImportError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "pip install fastapi httpx python-multipart")
class TestAPI(unittest.TestCase):
    def setUp(self):
        ws.clear()
        self.c = TestClient(app)

    def test_sample_and_summary(self):
        r = self.c.post("/api/invoices/sample?count=10&kind=random").json()
        self.assertEqual(r["summary"]["invoices"], 10)
        self.assertEqual(len(r["items"]), 10)
        s = r["summary"]
        self.assertEqual(s["ready"] + s["review"] + s["blocked"], 10)

    def test_answer_fixes_missing_trn_and_enables_xml(self):
        from ira.synth import clean_invoice
        import random
        d = clean_invoice(random.Random(5), 1)
        d["buyer"]["trn"] = None
        up = self.c.post("/api/invoices/upload",
                         files=[("files", ("inv.json", json.dumps(d), "application/json"))]).json()
        item = up["items"][0]
        self.assertEqual(item["status"], "blocked")
        self.assertEqual(self.c.get(f"/api/invoices/{item['id']}/xml").status_code, 409)
        r = self.c.post(f"/api/invoices/{item['id']}/answer",
                        json={"field": "buyer.trn", "value": "100 2345 6789 0103"}).json()
        self.assertEqual(r["item"]["status"], "ready")
        x = self.c.get(f"/api/invoices/{item['id']}/xml")
        self.assertEqual(x.status_code, 200)
        self.assertIn("<cbc:CompanyID>100234567890103</cbc:CompanyID>", x.text)

    def test_rejects_bad_files_and_unknown_fields(self):
        r = self.c.post("/api/invoices/upload",
                        files=[("files", ("notes.txt", b"hello", "text/plain")),
                               ("files", ("bad.json", b"{not json", "application/json"))]).json()
        self.assertEqual(len(r["errors"]), 2)
        self.c.post("/api/invoices/sample?count=1&kind=random")
        rid = self.c.get("/api/invoices").json()["items"][0]["id"]
        self.assertEqual(self.c.post(f"/api/invoices/{rid}/answer",
                                     json={"field": "lines[1].vat_rate", "value": "5"}).status_code, 422)
        self.assertEqual(self.c.post("/api/invoices/nope/answer",
                                     json={"field": "buyer.trn", "value": "1"}).status_code, 404)

    def test_xml_upload_round_trip(self):
        from ira.synth import clean_invoice
        from ira.models import invoice_from_dict
        from ira.ubl import to_ubl_xml
        import random
        xml = to_ubl_xml(invoice_from_dict(clean_invoice(random.Random(9), 9)))
        r = self.c.post("/api/invoices/upload", files=[("files", ("erp.xml", xml, "application/xml"))]).json()
        self.assertEqual(r["errors"], [])
        item = r["items"][0]
        self.assertEqual((item["source"], item["status"]), ("xml", "ready"))
        self.assertEqual(self.c.get(f"/api/invoices/{item['id']}/xml").text, xml)

    def test_demo_story_memory_requests_report(self):
        items = self.c.post("/api/invoices/sample").json()["items"]
        self.assertEqual(len(items), 12)
        r = self.c.post(f"/api/invoices/{items[0]['id']}/answer",
                        json={"field": "seller.legal_id", "value": "784512"}).json()
        self.assertEqual(len(r["item"]["appliedTo"]), 11)
        reqs = self.c.get("/api/outreach").json()["requests"]
        self.assertEqual([len(x["invoices"]) for x in reqs], [4])
        rep = self.c.get("/api/report").json()
        self.assertGreater(rep["exposureAed"], 0)
        self.assertEqual(rep["answersReusedByAgent"], 11)

    def test_export_zip(self):
        self.assertEqual(self.c.get("/api/export.zip").status_code, 409)
        self.c.post("/api/invoices/sample?count=20&kind=random")
        r = self.c.get("/api/export.zip")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")


if __name__ == "__main__":
    unittest.main()
