import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from ira.eval import evaluate
from ira.models import invoice_from_dict, to_decimal
from ira.synth import clean_invoice
from ira.ubl import to_ubl_xml
from ira.validate import validate
import random


def codes(d):
    return {i.code for i in validate(invoice_from_dict(d))}


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.d = clean_invoice(random.Random(1), 1)

    def test_clean_invoice_has_no_errors(self):
        errs = [i for i in validate(invoice_from_dict(self.d)) if i.severity == "error"]
        self.assertEqual(errs, [])

    def test_trn_with_spaces_is_accepted(self):
        t = self.d["seller"]["trn"]
        self.d["seller"]["trn"] = f"{t[:3]} {t[3:7]}-{t[7:]}"
        self.assertNotIn("BAD_SELLER_TRN", codes(self.d))

    def test_short_trn_rejected(self):
        self.d["buyer"]["trn"] = "12345"
        self.assertIn("BAD_BUYER_TRN", codes(self.d))

    def test_ten_percent_vat_rejected(self):
        self.d["lines"][0]["vat_rate"] = "10"
        self.assertIn("BAD_VAT_RATE", codes(self.d))

    def test_line_math(self):
        self.d["lines"][0]["line_total"] = "1.00"
        self.assertIn("LINE_MATH_MISMATCH", codes(self.d))

    def test_messy_amounts_parse(self):
        self.assertEqual(to_decimal("AED 1,250.50"), Decimal("1250.50"))
        self.assertIsNone(to_decimal("n/a"))

    def test_same_trn(self):
        self.d["buyer"]["trn"] = self.d["seller"]["trn"]
        self.assertIn("SAME_TRN", codes(self.d))


class TestUBL(unittest.TestCase):
    def test_xml_totals_match_stated(self):
        d = clean_invoice(random.Random(3), 3)
        root = ET.fromstring(to_ubl_xml(invoice_from_dict(d)))
        ns = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
              "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
        payable = root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", ns).text
        self.assertEqual(Decimal(payable), Decimal(d["gross_total"]))
        self.assertEqual(root.find("cac:TaxTotal/cbc:TaxAmount", ns).text, f"{Decimal(d['vat_total']):.2f}")


class TestEval(unittest.TestCase):
    def test_validator_catches_all_injected_faults(self):
        r = evaluate(count=200)
        self.assertEqual(r["recall"], 1.0, r)
        self.assertEqual(r["precision"], 1.0, r)
        self.assertEqual(r["clean_pass_rate"], 1.0, r)


if __name__ == "__main__":
    unittest.main()
