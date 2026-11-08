"""AI extraction path with a mocked model: no network, no quota."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

FIX = Path(__file__).parent / "fixtures"

try:
    import pypdfium2  # noqa: F401
except ImportError:  # pragma: no cover
    pypdfium2 = None


def truth_as_llm(name: str) -> dict:
    t = json.loads((FIX / name).read_text())
    return {**{k: t[k] for k in ("invoice_number", "date", "due_date", "company", "seller_trn",
                                 "seller_address", "buyer_name", "buyer_trn", "buyer_address", "total")},
            "lines": [{"description": "x", "quantity": q, "unit_price": p, "vat_rate": "5", "line_total": a}
                      for q, p, a in t["lines"]]}


@unittest.skipIf(pypdfium2 is None, "pip install pypdfium2")
class TestHybrid(unittest.TestCase):
    def extract(self, pdf: str, llm_enabled: bool, llm=None, error=None):
        from ira import agent, extract
        env = {"QAID_LLM": "1" if llm_enabled else ""}
        fake = mock.Mock(side_effect=error) if error else mock.Mock(return_value=llm)
        with mock.patch.dict(os.environ, env), mock.patch.object(extract, "llm_extract_text", fake):
            return agent.document_extract(FIX / pdf, engine=None), fake

    def test_ai_off_never_calls(self):
        d, fake = self.extract("uae-tax-invoice-unseen-layout.pdf", llm_enabled=False)
        self.assertEqual((d["_extractor"], fake.call_count), ("rules", 0))

    def test_complete_rules_skip_the_ai(self):
        d, fake = self.extract("uae-tax-invoice-digital.pdf", llm_enabled=True, llm={})
        self.assertEqual((d["_extractor"], fake.call_count), ("rules", 0))

    def test_unseen_layout_ai_fills_gaps_and_flags_disagreements(self):
        llm = truth_as_llm("uae-tax-invoice-unseen-layout.json")
        d, fake = self.extract("uae-tax-invoice-unseen-layout.pdf", llm_enabled=True, llm=llm)
        t = json.loads((FIX / "uae-tax-invoice-unseen-layout.json").read_text())
        self.assertEqual((d["_extractor"], fake.call_count), ("rules + AI", 1))
        self.assertEqual((d["invoice_number"], d["seller"]["trn"], d["due_date"]),
                         (t["invoice_number"], t["seller_trn"], t["due_date"]))
        # Fields the rules missed are filled by the AI but still confirmed by the owner.
        self.assertIn("invoice_number", d["_unconfirmed"])
        self.assertNotIn("company", d["_unconfirmed"])  # both readers agreed -> accepted

    def test_ai_failure_falls_back_to_rules(self):
        from ira.extract import LLMError
        d, fake = self.extract("uae-tax-invoice-unseen-layout.pdf", llm_enabled=True,
                               error=LLMError("429 quota"))
        self.assertEqual((d["_extractor"], fake.call_count), ("rules (AI unavailable)", 1))


class TestHybridMerge(unittest.TestCase):
    def test_agreement_accepted_disagreement_flagged(self):
        from ira.extract import hybrid
        merged, unconfirmed = hybrid({"total": "105.00", "date": "2026-01-02", "company": None},
                                     {"total": "105", "date": "2026-02-01", "company": "ACME LLC"})
        self.assertEqual(merged["total"], "105.00")
        self.assertEqual(set(unconfirmed), {"date", "company"})
        self.assertEqual((merged["date"], merged["company"]), ("2026-02-01", "ACME LLC"))

    def test_parse_reply_with_trailing_text(self):
        from ira.extract import _parse_json
        self.assertEqual(_parse_json('Sure! {"a": 1} {"b": 2}'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
