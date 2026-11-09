"""HTTP API + web app server.

    pip install fastapi uvicorn python-multipart
    python -m ira.server            # http://127.0.0.1:8000  (API docs at /docs)

The React app in web/ is built to web/dist and served from "/".
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import IMAGE_SUFFIXES
from .service import Workspace, outreach, report
from .synth import demo_batch, generate
from .ubl_import import parse_ubl

MAX_FILES = 25
MAX_BYTES = 15 * 1024 * 1024  # per file
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="Qaid API", version="0.1.0",
              description="UAE e-invoicing readiness agent: ingest, validate, repair, export UBL.")
# Persist to SQLite so work survives restarts. QAID_DB="" keeps everything in memory.
ws = Workspace(os.environ.get("QAID_DB", str(Path.home() / ".qaid" / "workspace.db")) or None)


def ocr_engine() -> str | None:
    """Best available free OCR setup on this machine."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        rapid = True
    except ImportError:
        rapid = False
    tess = shutil.which("tesseract") is not None
    return "both" if rapid and tess else "rapidocr" if rapid else "tesseract" if tess else None


class Answer(BaseModel):
    field: str = Field(..., max_length=64)
    value: str = Field(..., max_length=500)


class Confirm(BaseModel):
    field: str = Field(..., max_length=64)


def _state() -> dict:
    return {"summary": ws.summary(), "items": ws.list()}


@app.get("/api/health")
def health():
    from .agent import llm_enabled
    from .extract import DEFAULT_MODEL
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL) if llm_enabled() else None
    return {"ok": True, "ocr": ocr_engine(), "ai": llm_enabled(), "aiModel": model}


@app.get("/api/invoices")
def list_invoices():
    return _state()


@app.post("/api/invoices/sample")
def load_sample(count: int = Query(12, ge=1, le=100), seed: int = Query(42),
                kind: str = Query("demo", pattern="^(demo|random)$")):
    """kind=demo: one SME's realistic batch (shows agent memory and customer requests)."""
    docs = demo_batch() if kind == "demo" else generate(count=count, seed=seed)
    ws.add_dicts(docs, source="sample")
    return _state()


@app.post("/api/invoices/upload")
async def upload(files: list[UploadFile] = File(...)):
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Upload at most {MAX_FILES} files at a time.")
    errors: list[dict] = []
    engine = ocr_engine()
    with tempfile.TemporaryDirectory() as td:
        for f in files:
            name = Path(f.filename or "upload").name  # strip any client path
            data = await f.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                errors.append({"file": name, "error": "File is larger than 15 MB."})
                continue
            suffix = Path(name).suffix.lower()
            try:
                if suffix == ".json":
                    payload = json.loads(data.decode("utf-8"))
                    items = payload if isinstance(payload, list) else [payload]
                    if not all(isinstance(i, dict) for i in items):
                        raise ValueError("JSON must be an invoice object or a list of them.")
                    for i in items:
                        i.setdefault("source_file", name)
                    ws.add_dicts(items, source="json")
                elif suffix == ".xml":
                    item = parse_ubl(data.decode("utf-8"))
                    item["source_file"] = name
                    ws.add_dicts([item], source="xml")
                elif suffix in IMAGE_SUFFIXES or suffix == ".pdf":
                    path = Path(td) / f"upload{suffix}"
                    path.write_bytes(data)
                    rec = ws.add_scan(path, engine)
                    ws.get(rec["id"]).invoice.source_file = name
                else:
                    raise ValueError("Use PDF, invoice images (JPG, PNG, TIFF, WEBP), UBL/PINT AE XML or JSON.")
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                errors.append({"file": name, "error": str(e)})
    return {**_state(), "errors": errors}


def _get_or_404(rid: str):
    try:
        return ws.get(rid)
    except KeyError:
        raise HTTPException(404, "Invoice not found.")


@app.post("/api/invoices/{rid}/answer")
def answer(rid: str, body: Answer):
    _get_or_404(rid)
    try:
        item = ws.answer(rid, body.field, body.value)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"item": item, "summary": ws.summary()}


@app.get("/api/outreach")
def get_outreach():
    return {"requests": outreach(ws)}


@app.get("/api/report")
def get_report():
    return report(ws)


@app.post("/api/invoices/{rid}/confirm")
def confirm(rid: str, body: Confirm):
    _get_or_404(rid)
    return {"item": ws.confirm(rid, body.field), "summary": ws.summary()}


@app.delete("/api/invoices/{rid}")
def delete(rid: str):
    ws.delete(rid)
    return _state()


@app.delete("/api/invoices")
def clear():
    ws.clear()
    return _state()


@app.get("/api/invoices/{rid}/xml")
def xml(rid: str):
    rec = _get_or_404(rid)
    try:
        body = ws.xml(rid)
    except ValueError as e:
        raise HTTPException(409, str(e))
    name = (rec.invoice.invoice_number or rid).replace("/", "-")
    return Response(body, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xml"'})


@app.get("/api/export.zip")
def export_zip():
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for item in ws.list():
            try:
                body = ws.xml(item["id"])
            except ValueError:
                continue
            z.writestr(f"{(item['invoiceNumber'] or item['id']).replace('/', '-')}.xml", body)
            count += 1
        z.writestr("readiness_report.json", json.dumps(_state(), indent=2))
    if count == 0:
        return JSONResponse({"detail": "No invoices are ready to export yet."}, status_code=409)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="asp-handoff.zip"'})


# --- Web app (built React SPA) ----------------------------------------------
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST in target.parents:
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")


def main():
    import uvicorn
    uvicorn.run("ira.server:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
