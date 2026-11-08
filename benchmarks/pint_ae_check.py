"""Validate generated invoices against the OFFICIAL OpenPeppol PINT AE Schematron.

The official resources (Schematron compiled to XSLT, examples, code lists) are published
by OpenPeppol at https://docs.peppol.eu/poac/ae/ . They are not vendored here; this script
downloads the pinned bundle and verifies its SHA-256 before use.

    pip install saxonche
    python -m benchmarks.pint_ae_check                    # download + check 100 generated invoices
    python -m benchmarks.pint_ae_check --resources DIR    # use an already-unzipped bundle
    python -m benchmarks.pint_ae_check --xml a.xml b.xml  # check specific files

Exit code 1 if any invoice has a fatal rule failure.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import random
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

BUNDLE_URL = "https://docs.peppol.eu/poac/ae/v1.0.3/pint-ae/resources.zip"
BUNDLE_SHA256 = "47756033c9b70be166973ff97298a948e5fe2434d063a5ce781127e727c29258"
SHEETS = ("PINT-UBL-validation-preprocessed", "PINT-jurisdiction-aligned-rules")
_FAIL = re.compile(r'<svrl:failed-assert[^>]*?id="([^"]+)"[^>]*?flag="([^"]+)"[^>]*>.*?<svrl:text>(.*?)</svrl:text>', re.S)


def fetch_bundle(dest: Path) -> Path:
    if (dest / "trn-invoice").exists():
        return dest
    data = urllib.request.urlopen(BUNDLE_URL, timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != BUNDLE_SHA256:
        raise SystemExit(f"Checksum mismatch for {BUNDLE_URL}: {digest}")
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    return dest


class Checker:
    def __init__(self, resources: Path):
        from saxonche import PySaxonProcessor
        self._proc = PySaxonProcessor(license=False)
        xslt = self._proc.new_xslt30_processor()
        base = resources / "trn-invoice" / "schematron"
        self._sheets = [xslt.compile_stylesheet(stylesheet_file=str(base / f"{n}.xslt")) for n in SHEETS]

    def check(self, xml_text: str) -> list[tuple[str, str, str]]:
        """Return (flag, rule_id, message) for every failed assertion."""
        node = self._proc.parse_xml(xml_text=xml_text)
        out = []
        for sheet in self._sheets:
            svrl = sheet.transform_to_string(xdm_node=node)
            out += [(m[2], m[1], " ".join(m[3].split())) for m in _FAIL.finditer(svrl)]
        return out


def generated_invoices(count: int, seed: int):
    from ira.models import invoice_from_dict
    from ira.synth import clean_invoice
    from ira.ubl import to_ubl_xml
    from ira.validate import validate
    rng = random.Random(seed)
    for n in range(1, count + 1):
        inv = invoice_from_dict(clean_invoice(rng, n))
        assert not [i for i in validate(inv) if i.severity == "error"], "clean invoice must validate"
        yield f"generated-{n:03d}", to_ubl_xml(inv)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resources", type=Path, default=Path(".cache/pint-ae-1.0.3"))
    ap.add_argument("--xml", nargs="*", type=Path)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()

    checker = Checker(fetch_bundle(a.resources))
    docs = ([(p.name, p.read_text(encoding="utf-8")) for p in a.xml] if a.xml
            else list(generated_invoices(a.count, a.seed)))
    fatal_docs, rules = 0, {}
    for name, xml in docs:
        fails = checker.check(xml)
        fatal = [f for f in fails if f[0] == "fatal"]
        fatal_docs += bool(fatal)
        for flag, rid, msg in fails:
            rules.setdefault((flag, rid), msg)
        if fatal and a.xml:
            print(f"FAIL {name}: " + "; ".join(r for _, r, _ in fatal))
    print(f"Official PINT AE v1.0.3 Schematron: {len(docs) - fatal_docs}/{len(docs)} invoices pass "
          f"(no fatal errors)")
    for (flag, rid), msg in sorted(rules.items()):
        print(f"  {flag:7} {rid}: {msg[:160]}")
    return 1 if fatal_docs else 0


if __name__ == "__main__":
    sys.exit(main())
