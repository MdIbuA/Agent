"""Advisory licence check against real Ajman DED open-data records (bundled sample)."""
import random
import unittest

from ira.models import invoice_from_dict
from ira.registry import check_seller_licence, register_size
from ira.synth import clean_invoice
from ira.validate import validate

AUTH = "Ajman Department of Economic Development"


class TestAjmanRegister(unittest.TestCase):
    def test_sample_is_loaded(self):
        self.assertGreaterEqual(register_size(), 3)

    def test_registered_name_matches_english_or_arabic(self):
        self.assertIsNone(check_seller_licence("73210", AUTH, "Ghazal Almadinh General Maint Cont"))
        self.assertIsNone(check_seller_licence("73210", AUTH, "غزال المدينة لمقاولات الصيانة العامة"))

    def test_mismatch_and_unknown_are_flagged(self):
        self.assertEqual(check_seller_licence("73210", AUTH, "Falcon Tech Repairs")[0], "LICENCE_NAME_MISMATCH")
        self.assertEqual(check_seller_licence("99999999", AUTH, "Anyone")[0], "LICENCE_NOT_IN_REGISTER")

    def test_other_emirates_not_checked(self):
        self.assertIsNone(check_seller_licence("73210", "Dubai Department of Economy and Tourism", "Anyone"))

    def test_warning_not_blocking(self):
        d = clean_invoice(random.Random(4), 4)
        d["seller"].update(legal_id="73210", legal_authority=AUTH)  # name differs from register
        issues = validate(invoice_from_dict(d))
        hit = [i for i in issues if i.code == "LICENCE_NAME_MISMATCH"]
        self.assertEqual([i.severity for i in hit], ["warning"])
        self.assertFalse([i for i in issues if i.severity == "error"])


class TestFullRegister(unittest.TestCase):
    """Runs only when the full register has been fetched (scripts/fetch_ajman_licences.py)."""

    def setUp(self):
        from ira.registry import DATA
        if not (DATA / "ajman_licences.csv").exists():
            self.skipTest("full register not downloaded")

    def test_full_register_loads(self):  # regression: the official export starts with a BOM
        self.assertGreater(register_size(), 50000)

    def test_ocr_garbled_names_resolve(self):
        from ira.registry import match_registered_name
        rec = match_registered_name("ALDAMMAMELECT.&SANIT.WARETRADING-Branch O1")
        self.assertEqual(rec["tradenameen"].strip(), "AL DAMMAM ELECT. & SANIT. WARE TRADING - Branch 01")
        self.assertIsNone(match_registered_name("Falcon Tech Repairs"))  # fictional


if __name__ == "__main__":
    unittest.main()
