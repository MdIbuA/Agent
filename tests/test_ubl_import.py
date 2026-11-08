import random
import unittest

from ira.models import invoice_from_dict
from ira.synth import clean_invoice
from ira.ubl import to_ubl_xml
from ira.ubl_import import parse_ubl
from ira.validate import validate


class TestUblImport(unittest.TestCase):
    def test_round_trip_is_lossless(self):
        """Generate XML, read it back, regenerate: identical, and still valid."""
        for seed in range(20):
            inv = invoice_from_dict(clean_invoice(random.Random(seed), seed))
            xml = to_ubl_xml(inv)
            back = invoice_from_dict(parse_ubl(xml))
            self.assertEqual([i.code for i in validate(back) if i.severity == "error"], [])
            self.assertEqual(to_ubl_xml(back), xml)

    def test_rejects_unsafe_or_wrong_documents(self):
        with self.assertRaises(ValueError):
            parse_ubl('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Invoice/>')
        with self.assertRaises(ValueError):
            parse_ubl("<Order xmlns='urn:x'/>")
        with self.assertRaises(ValueError):
            parse_ubl("<Invoice")


if __name__ == "__main__":
    unittest.main()
