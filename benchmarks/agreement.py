"""How often does the agent's validator agree with the OFFICIAL PINT AE rules?

Uses only official OpenPeppol PINT AE v1.0.3 data:
  1. the 12 official example documents (all valid)  -> agent must raise no errors
  2. mutants: each official invoice with ONE realistic error injected
     -> run the agent AND the official Schematron, compare verdicts

    python -m benchmarks.agreement [--resources DIR]

Reports agreement, the agent's recall on officially-invalid documents, and false alarms.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from benchmarks.pint_ae_check import Checker, fetch_bundle
from ira.models import invoice_from_dict
from ira.ubl_import import parse_ubl
from ira.validate import validate


def _sub(pattern: str, repl: str, count: int = 1):
    return lambda t: re.sub(pattern, repl, t, count=count, flags=re.S)


def _drop(tag: str):
    return _sub(rf"\s*<{tag}[^>]*>[^<]*</{tag}>", "")


# One realistic error per mutant. Each must change the document, or it is skipped.
MUTATIONS = {
    "seller TRN not ending 03": _sub(r"(<cac:AccountingSupplierParty>.*?<cac:PartyTaxScheme>\s*<cbc:CompanyID>\d{13})\d\d",
                                     r"\g<1>99"),
    "seller TRN 14 digits": _sub(r"(<cac:AccountingSupplierParty>.*?<cac:PartyTaxScheme>\s*<cbc:CompanyID>)\d", r"\1"),
    "invoice number missing": _drop("cbc:ID"),
    "impossible issue date": _sub(r"<cbc:IssueDate>[^<]+", "<cbc:IssueDate>2025-02-30"),
    "unknown currency": _sub(r"<cbc:DocumentCurrencyCode>[^<]+", "<cbc:DocumentCurrencyCode>XYZ"),
    "unknown country": _sub(r"(<cac:AccountingSupplierParty>.*?<cbc:IdentificationCode>)[^<]+", r"\1ZZ"),
    "unknown unit code": _sub(r'unitCode="[^"]+"', 'unitCode="BOX"'),
    "wrong specification ID": _sub(r"<cbc:CustomizationID>[^<]+", "<cbc:CustomizationID>urn:cen.eu:en16931:2017"),
    "emirate missing": _drop("cbc:CountrySubentity"),
    "VAT total tampered": _sub(r"(<cac:TaxTotal>\s*(?:<!--.*?-->\s*)*<cbc:TaxAmount[^>]*>)([\d.]+)",
                               lambda m: f"{m[1]}{float(m[2]) + 7:.2f}"),
    "line amount tampered": _sub(r"(<cac:InvoiceLine>.*?<cbc:LineExtensionAmount[^>]*>)([\d.]+)",
                                 lambda m: f"{m[1]}{float(m[2]) + 50:.2f}"),
    "payment due date missing": _drop("cbc:DueDate"),
}


def agent_flags(xml: str) -> list[str]:
    try:
        return [i.code for i in validate(invoice_from_dict(parse_ubl(xml))) if i.severity == "error"]
    except ValueError as e:  # unparseable counts as rejected
        return [f"PARSE_ERROR: {e}"]


def run(resources: Path) -> dict:
    checker = Checker(resources)
    docs = sorted((resources / "trn-invoice" / "example").glob("*.xml"))
    valid_docs = docs + sorted((resources / "trn-creditnote" / "example").glob("*.xml"))

    false_alarms = []
    for f in valid_docs:
        if agent_flags(f.read_text(encoding="utf-8")):
            false_alarms.append(f.name)

    matrix = Counter()
    per_mutation = {}
    for name, mutate in MUTATIONS.items():
        stats = Counter()
        for f in docs:
            original = f.read_text(encoding="utf-8")
            xml = mutate(original)
            if xml == original:
                continue
            official_bad = any(flag == "fatal" for flag, _, _ in checker.check(xml))
            agent_bad = bool(agent_flags(xml))
            stats[(official_bad, agent_bad)] += 1
            matrix[(official_bad, agent_bad)] += 1
        per_mutation[name] = stats

    both_bad, missed = matrix[(True, True)], matrix[(True, False)]
    extra, both_ok = matrix[(False, True)], matrix[(False, False)]
    total = sum(matrix.values())
    return {
        "official_examples": len(valid_docs),
        "false_alarms_on_official": false_alarms,
        "mutants": total,
        "agreement_pct": round(100 * (both_bad + both_ok) / total, 1) if total else None,
        "agent_recall_on_officially_invalid": round(100 * both_bad / max(both_bad + missed, 1), 1),
        "agent_stricter_than_official": extra,
        "per_mutation": {k: dict(caught=v[(True, True)], missed=v[(True, False)], stricter=v[(False, True)],
                                 both_ok=v[(False, False)]) for k, v in per_mutation.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resources", type=Path, default=Path(".cache/pint-ae-1.0.3"))
    r = run(fetch_bundle(ap.parse_args().resources))
    print(f"Official example documents: {r['official_examples']}, agent false alarms: "
          f"{len(r['false_alarms_on_official'])} {r['false_alarms_on_official'] or ''}")
    print(f"Mutants: {r['mutants']} | agreement with official rules: {r['agreement_pct']}% | "
          f"agent recall on officially-invalid: {r['agent_recall_on_officially_invalid']}% | "
          f"agent stricter: {r['agent_stricter_than_official']}")
    print(f"{'mutation':<28}{'caught':>8}{'missed':>8}{'stricter':>10}{'both ok':>9}")
    for k, v in r["per_mutation"].items():
        print(f"{k:<28}{v['caught']:>8}{v['missed']:>8}{v['stricter']:>10}{v['both_ok']:>9}")
    return r


if __name__ == "__main__":
    main()
