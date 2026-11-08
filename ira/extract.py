"""LLM extraction: messy invoice (text or image) -> structured JSON.

Uses any OpenAI-compatible chat endpoint, so you can switch between free tiers
(Gemini, Groq, OpenRouter) with env vars and zero code changes:

    LLM_BASE_URL  e.g. https://generativelanguage.googleapis.com/v1beta/openai
                       https://api.groq.com/openai/v1
    LLM_API_KEY   your free-tier key
    LLM_MODEL     e.g. a Gemini Flash model for images, a Groq model for text

Design rule: the LLM only EXTRACTS. It never computes totals or judges compliance --
validate.py does that deterministically, so hallucinated maths can't slip through.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.request
from pathlib import Path

SYSTEM_PROMPT = """You extract data from UAE tax invoices (English or Arabic).
Return ONLY a JSON object with this exact shape:
{"invoice_number": str|null, "issue_date": "YYYY-MM-DD"|null, "currency": str|null,
 "seller": {"name": str|null, "trn": str|null, "address": str|null, "city": str|null},
 "buyer":  {"name": str|null, "trn": str|null, "address": str|null, "city": str|null},
 "lines": [{"description": str|null, "quantity": str|null, "unit_price": str|null,
            "vat_rate": str|null, "line_total": str|null}],
 "net_total": str|null, "vat_total": str|null, "gross_total": str|null}
Rules:
- Copy values exactly as printed. Do NOT calculate, correct or guess anything.
- If a value is not visible, use null. Never invent a TRN.
- vat_rate is the percentage number only, e.g. "5".
- Translate Arabic labels, but keep names in their original script.
- Numbers as plain strings without currency symbols or thousands separators."""


def _chat(messages: list[dict]) -> str:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    body = json.dumps({
        "model": os.environ["LLM_MODEL"],
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def extract(path: str | Path) -> dict:
    """Extract one invoice file. Supports .txt/.csv/.json text and .png/.jpg images."""
    path = Path(path)
    mime, _ = mimetypes.guess_type(path.name)
    if mime and mime.startswith("image/"):
        b64 = base64.b64encode(path.read_bytes()).decode()
        user = [{"type": "text", "text": "Extract this invoice."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
    else:
        user = f"Extract this invoice:\n\n{path.read_text(errors='replace')[:20000]}"
    raw = _chat([{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": user}])
    data = json.loads(raw)
    data["source_file"] = path.name
    return data
