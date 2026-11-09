"""Official business-licence register lookups (UAE open data).

Source: Ajman Department of Economic Development, "License in Ajman (Area)" dataset on the
Ajman Open Data portal (data.ajman.ae), CC BY 4.0. See data/uae_open_data/SOURCES.md.

The full register (~62k licences) is fetched with scripts/fetch_ajman_licences.py into
data/uae_open_data/ajman_licences.csv; without it a small real sample is used. Results are
advisory: registers lag behind new licences, so a miss is a warning, never a blocking error.
"""
from __future__ import annotations

import csv
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "uae_open_data"
AJMAN_AUTHORITY = re.compile(r"\bAJMAN\b|عجمان", re.I)


def _norm(name: str) -> str:
    """Compare trade names ignoring case, punctuation and common legal-form words."""
    s = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    s = re.sub(r"\b(LLC|L L C|FZE|FZCO|EST|ESTABLISHMENT|CO|COMPANY|TRADING|CONT|CONTRACTING)\b", " ", s)
    return " ".join(s.split())


@lru_cache(maxsize=1)
def ajman_register() -> dict[str, dict]:
    path = Path(os.environ.get("QAID_AJMAN_LICENCES", DATA / "ajman_licences.csv"))
    if not path.exists():
        path = DATA / "ajman_licences_sample.csv"
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:  # official export starts with a BOM
        for row in csv.DictReader(f):
            num = re.sub(r"\.0$", "", (row.get("licensenumber") or "").strip())
            if num:
                out[num] = row
    return out


def register_size() -> int:
    return len(ajman_register())


def check_seller_licence(licence_no: str | None, authority: str | None, seller_name: str | None):
    """Return None if not applicable or consistent; otherwise (code, message)."""
    if not licence_no or not authority or not AJMAN_AUTHORITY.search(authority):
        return None
    reg = ajman_register()
    rec = reg.get(re.sub(r"\D", "", licence_no))
    if rec is None:
        return ("LICENCE_NOT_IN_REGISTER",
                f"Licence {licence_no} was not found in the Ajman DED open-data register "
                f"({len(reg):,} licences loaded). It may be new or mistyped.")
    names = [rec.get("tradenameen") or "", rec.get("tradenamear") or ""]
    if seller_name and not any(
            n and SequenceMatcher(None, _norm(seller_name), _norm(n)).ratio() >= 0.8 for n in names) \
            and seller_name.strip() not in names:
        return ("LICENCE_NAME_MISMATCH",
                f"Ajman licence {licence_no} is registered to '{names[0] or names[1]}', "
                f"not '{seller_name}'.")
    return None


# ---- Register-assisted name correction ----------------------------------------
# OCR drops spaces, confuses O/0 and I/1/l, and truncates long names. Matching on a
# confusion-normalised key against the official register recovers the registered name.
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper()).translate(_CONFUSABLE)


@lru_cache(maxsize=1)
def _name_index() -> tuple[dict[str, list[dict]], list[str]]:
    idx: dict[str, list[dict]] = {}
    for rec in ajman_register().values():
        k = _key(rec.get("tradenameen") or "")
        if len(k) >= 6:
            idx.setdefault(k, []).append(rec)
    return idx, sorted(idx)


def match_registered_name(name: str | None) -> dict | None:
    """The single register entry whose trade name matches `name` despite OCR noise, else None.
    Exact key match first; then a unique key that starts with a long truncated read."""
    k = _key(name or "")
    if len(k) < 10:
        return None
    idx, keys = _name_index()
    hits = idx.get(k)
    if hits is None and len(k) >= 15:
        import bisect
        i = bisect.bisect_left(keys, k)
        pref = []
        while i < len(keys) and keys[i].startswith(k) and len(pref) < 2:
            pref.append(keys[i])
            i += 1
        hits = idx[pref[0]] if len(pref) == 1 else None
    return hits[0] if hits and len(hits) == 1 else None


def snap_parties(found: dict) -> tuple[dict, list[str]]:
    """Replace OCR-garbled seller/buyer names with their registered form and suggest the
    seller's licence. Returns (updated, fields_changed) so the agent can ask to confirm."""
    out, changed = dict(found), []
    for field in ("company", "buyer_name"):
        rec = match_registered_name(found.get(field))
        if rec and rec["tradenameen"].strip() != (found.get(field) or "").strip():
            out[field] = " ".join(rec["tradenameen"].split())
            changed.append(field)
        if rec and field == "company" and not found.get("seller_licence"):
            out["seller_licence"] = rec["licensenumber"].split(".")[0]
            out["seller_licence_authority"] = "Ajman Department of Economic Development"
            changed.append("seller_licence")
    for field in ("seller_address", "buyer_address"):
        if found.get(field):
            out[field] = snap_address(found[field])
    return out, changed


@lru_cache(maxsize=1)
def _area_index() -> dict[str, str]:
    """Official Ajman area names (from the register), keyed for OCR-tolerant matching."""
    out: dict[str, str] = {}
    for rec in ajman_register().values():
        area = " ".join((rec.get("areaen") or "").split())
        if area and area != "NULL":
            out.setdefault(_key(area), area)
    return out


def snap_address(address: str | None) -> str | None:
    """'Rashideyal, Ajman' -> 'Rashideya1, Ajman' when the area is an official Ajman area."""
    if not address or not re.search(r"AJMAN", address, re.I):
        return address
    parts = [p.strip() for p in address.split(",")]
    fixed = [_area_index().get(_key(p), p) if len(_key(p)) >= 4 else p for p in parts]
    return ", ".join(fixed)
