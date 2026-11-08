"""UAE-specific rules taken from the official OpenPeppol PINT AE v1.0.3 Schematron."""
import random
import unittest

from ira.agent import parse_emirate, parse_payment_means
from ira.models import invoice_from_dict
from ira.synth import clean_invoice
from ira.ubl import to_ubl_xml
from ira.validate import validate


def codes(d):
    return {i.code for i in validate(invoice_from_dict(d))}


class TestUaeRules(unittest.TestCase):
    def setUp(self):
        self.d = clean_invoice(random.Random(11), 1)

    def test_clean_invoice_passes(self):
        self.assertEqual({c for c in codes(self.d)}, set())

    def test_trn_must_start_1_and_end_03(self):  # ibr-132-ae
        self.d["seller"]["trn"] = "100123456789012"   # 15 digits but ends 12
        self.assertIn("BAD_SELLER_TRN", codes(self.d))
        self.d["seller"]["trn"] = "200123456789003"   # starts with 2
        self.assertIn("BAD_SELLER_TRN", codes(self.d))
        self.d["seller"]["trn"] = "100 1234 5678 9003"
        self.assertNotIn("BAD_SELLER_TRN", codes(self.d))

    def test_emirate_required_and_inferred_only_when_written(self):  # ibr-128/143/144-ae
        self.d["buyer"].update(address="Warehouse 4", city="Industrial Area", emirate=None)
        self.assertIn("MISSING_BUYER_EMIRATE", codes(self.d))
        self.d["buyer"]["city"] = "Abu Dhabi"
        self.assertEqual(invoice_from_dict(self.d).buyer.emirate, "AUH")

    def test_due_date_and_payment_means_required(self):  # ibr-127-ae, ibr-191-ae
        self.d["due_date"] = None
        self.d["payment_means"] = None
        self.assertTrue({"MISSING_DUE_DATE", "MISSING_PAYMENT_MEANS"} <= codes(self.d))

    def test_trade_licence_and_authority(self):  # ibr-150-ae, ibr-172-ae
        self.d["seller"]["legal_authority"] = None
        self.assertIn("MISSING_SELLER_LICENSE_AUTHORITY", codes(self.d))
        self.d["seller"]["legal_id"] = None
        self.assertIn("MISSING_SELLER_LICENSE", codes(self.d))

    def test_answer_parsers(self):
        self.assertEqual(parse_emirate("dubai"), "DXB")
        self.assertEqual(parse_emirate(" RAK "), "RAK")
        self.assertEqual(parse_payment_means("Bank transfer"), "30")
        self.assertEqual(parse_payment_means("cash"), "10")
        with self.assertRaises(ValueError):
            parse_emirate("Doha")

    def test_xml_has_pint_ae_essentials(self):
        xml = to_ubl_xml(invoice_from_dict(self.d))
        for needle in ("<cbc:ProfileExecutionID>00000000<", "<cbc:UUID>", "<cbc:DueDate>",
                       'schemeID="0235"', "<cbc:CountrySubentity>", "<cbc:PaymentMeansCode>",
                       "<cac:ItemPriceExtension>", 'schemeAgencyID="TL"'):
            self.assertIn(needle, xml)
        self.assertEqual(xml, to_ubl_xml(invoice_from_dict(self.d)), "export must be deterministic")


if __name__ == "__main__":
    unittest.main()
