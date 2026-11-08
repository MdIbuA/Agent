import unittest
from decimal import Decimal

from ira.rule_extract import extract, extract_total, normalize_date


class TestDates(unittest.TestCase):
    def test_day_first_formats(self):
        self.assertEqual(normalize_date("Date: 25/12/2018 10:31"), "2018-12-25")
        self.assertEqual(normalize_date("02-01-19"), "2019-01-02")
        self.assertEqual(normalize_date("05.03.2026"), "2026-03-05")

    def test_text_month(self):
        self.assertEqual(normalize_date("12 JAN 2018"), "2018-01-12")
        self.assertEqual(normalize_date("Mar 8, 2017"), "2017-03-08")

    def test_iso_and_invalid(self):
        self.assertEqual(normalize_date("2026-11-05"), "2026-11-05")
        self.assertIsNone(normalize_date("31/02/2026"))
        self.assertIsNone(normalize_date("Tel 03-1234 5678"))


class TestTotal(unittest.TestCase):
    def test_prefers_grand_total_over_subtotal_and_cash(self):
        lines = ["SUBTOTAL 80.00", "GST 6% 4.80", "GRAND TOTAL 84.80", "CASH 100.00", "CHANGE 15.20"]
        self.assertEqual(extract_total(lines), Decimal("84.80"))

    def test_amount_on_next_line(self):
        self.assertEqual(extract_total(["TOTAL", "RM 9.00", "CASH 10.00"]), Decimal("9.00"))

    def test_ignores_total_qty(self):
        self.assertEqual(extract_total(["TOTAL QTY: 3", "TOTAL: 45.50"]), Decimal("45.50"))

    def test_tax_total_and_excluding_lines_ignored(self):
        lines = ["GST @ 6% INCLUDED IN TOTAL", "TAX TOTAL: 0.85", "Total Sales (Excluding GST) 60.91", "TOTAL 15.00"]
        self.assertEqual(extract_total(lines), Decimal("15.00"))

    def test_thousands_separator(self):
        self.assertEqual(extract_total(["Total Amount Due AED 1,250.00"]), Decimal("1250.00"))


class TestExtract(unittest.TestCase):
    def test_end_to_end(self):
        text = "TAN WOON YANN\nBOOK TA .K (TAMAN DAYA) SDN BHD\n789417-W\nDATE: 25/12/2018\nTOTAL: 9.00\nCASH 10.00"
        out = extract(text)
        self.assertEqual(out["company"], "BOOK TA .K (TAMAN DAYA) SDN BHD")
        self.assertEqual(out["date"], "2018-12-25")
        self.assertEqual(out["total"], "9.00")



class TestRealWorldFixes(unittest.TestCase):
    """Regression cases found by benchmarking on real SROIE receipts."""

    def test_rounding_adjustment_negative(self):
        self.assertEqual(extract_total(["TOTAL AMT ...... RM 60.31", "ROUNDING ADJ ...... -0.01", "RM 60.30"]),
                         Decimal("60.30"))

    def test_rounding_then_rounded_total_line(self):
        lines = ["TOTAL SALES(INCL GST 6%) RM 64.13", "ROUNDING ADJUSTMENT : RM 0.02", "TOTAL RM 64.15"]
        self.assertEqual(extract_total(lines), Decimal("64.15"))

    def test_total_rounded_beats_total(self):
        lines = ["TOTAL RM 33.92", "ROUNDING ADJUSTMENT -RM 0.02", "TOTAL ROUNDED RM 33.90", "CASH RM 50.00"]
        self.assertEqual(extract_total(lines), Decimal("33.90"))

    def test_multiline_company(self):
        out = extract("AIK HUAT HARDWARE\nENTERPRISE (SETIA\nALAM) SDN BHD\n822737-X\nTOTAL 15.00")
        self.assertEqual(out["company"], "AIK HUAT HARDWARE ENTERPRISE (SETIA ALAM) SDN BHD")

    def test_strip_registration_number(self):
        self.assertEqual(extract("99 SPEED MART S/B (519537-X)\nLOT 2811\nTOTAL 5.00")["company"], "99 SPEED MART S/B")


class TestDateRegressions(unittest.TestCase):
    """Date failures found on real SROIE receipts."""

    def test_number_before_date_not_eaten(self):
        self.assertEqual(normalize_date("ORD #50 -REG #19- 18/01/2018 10:27:03"), "2018-01-18")

    def test_product_codes_ignored(self):
        self.assertEqual(normalize_date("HD03-04-06 - 5/40/160\nDATE: 19-09-17"), "2017-09-19")
        self.assertEqual(normalize_date("INVOICE NO: SP-NULL-18/06/04-1016956\nDATE : 04/06/2018"), "2018-06-04")

    def test_us_format_when_day_first_impossible(self):
        self.assertEqual(normalize_date("DATE : 12/28/2017 10:17:32 PM"), "2017-12-28")

    def test_compact_date_after_label(self):
        self.assertEqual(normalize_date("DATE/TIME : 20180428/191204"), "2018-04-28")

    def test_glued_time_and_glued_order_number(self):
        self.assertEqual(normalize_date("Date: 25/12/20188:13:39PM"), "2018-12-25")
        self.assertEqual(normalize_date("Date : 22/12/201714:03"), "2017-12-22")
        self.assertEqual(normalize_date("Order No. 100021911/03/2018 06:20 PM"), "2018-03-11")

    def test_date_line_beats_earlier_candidate(self):
        self.assertEqual(normalize_date("11:59AM 567640 28-11-18\nDATE: 28-01-2018"), "2018-01-28")


if __name__ == "__main__":
    unittest.main()
