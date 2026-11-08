import random
import tempfile
import unittest
from pathlib import Path

from ira.models import invoice_from_dict, invoice_to_dict
from ira.service import Workspace
from ira.synth import clean_invoice, credit_note_for
from ira.ubl import to_ubl_xml


class TestPersistence(unittest.TestCase):
    def test_invoice_dict_round_trip(self):
        for seed in range(15):
            d = clean_invoice(random.Random(seed), seed)
            if seed % 3 == 0:
                d = credit_note_for(d, random.Random(seed), seed)
            inv = invoice_from_dict(d)
            self.assertEqual(to_ubl_xml(invoice_from_dict(invoice_to_dict(inv))), to_ubl_xml(inv))

    def test_workspace_survives_restart_with_answers_and_confirmations(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ws.db"
            d = clean_invoice(random.Random(1), 1)
            d["buyer"]["trn"] = None
            d["_unconfirmed"] = ["date", "total"]
            ws = Workspace(db)
            rid = ws.add_dicts([d], "scan")[0]["id"]
            ws.answer(rid, "buyer.trn", "100 1111 2222 3303")
            ws.confirm(rid, "issue_date")
            before = ws.get(rid)

            again = Workspace(db)  # simulated restart
            after = again.get(rid)
            self.assertEqual(after.invoice.buyer.trn, "100111122223303")
            self.assertEqual(after.unconfirmed, {"total"})
            self.assertEqual(after.answered, before.answered)
            self.assertEqual([i.code for i in after.issues()], [i.code for i in before.issues()])

            again.delete(rid)
            self.assertEqual(Workspace(db).list(), [])

    def test_in_memory_by_default(self):
        ws = Workspace()
        ws.add_dicts([clean_invoice(random.Random(2), 2)], "sample")
        self.assertEqual(len(Workspace().list()), 0)


if __name__ == "__main__":
    unittest.main()
