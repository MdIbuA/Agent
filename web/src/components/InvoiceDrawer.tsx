import { Check, Download, Info, PartyPopper, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, fieldHint, fmtDate, fmtMoney, type Invoice, type Issue } from "../lib/api";
import { ScoreRing, StatusChip } from "./ui";

// Client-side checks mirror the server rules so the owner gets instant feedback.
function check(field: string, v: string): string | null {
  const s = v.trim();
  if (!s) return "Enter a value.";
  if (field.endsWith(".trn") && !/^\d{15}$/.test(s.replace(/[\s-]/g, ""))) return "A TRN has exactly 15 digits.";
  if (field === "gross_total" && !/^\d+(\.\d{1,2})?$/.test(s.replace(/,/g, ""))) return "Enter an amount like 1250.00.";
  return null;
}

function Question({ issue, invoiceId, onUpdated }: {
  issue: Issue; invoiceId: string; onUpdated: (inv: Invoice, msg: string) => void;
}) {
  const unconfirmed = issue.code.startsWith("UNCONFIRMED");
  const [editing, setEditing] = useState(!unconfirmed);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hint = fieldHint[issue.field] ?? { placeholder: "" };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const problem = check(issue.field, value);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      const { item } = await api.answer(invoiceId, issue.field, issue.field === "gross_total" ? value.replace(/,/g, "") : value);
      onUpdated(item, "Answer saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const { item } = await api.confirm(invoiceId, issue.field);
      onUpdated(item, "Confirmed");
    } finally {
      setBusy(false);
    }
  };

  const id = `q-${invoiceId}-${issue.code}`;
  return (
    <div className="question" data-severity={issue.severity}>
      <label htmlFor={id} className="question-text">{issue.question}</label>
      {hint.hint && editing && <div className="question-hint">{hint.hint}</div>}
      {editing ? (
        <form className="answer-row" onSubmit={submit} noValidate>
          <input id={id} className="input" value={value} placeholder={hint.placeholder} inputMode={hint.inputMode}
            autoComplete="off" aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
            onChange={(e) => { setValue(e.target.value); setError(null); }} />
          <button className="btn btn-primary" disabled={busy}>{busy ? <span className="spinner" /> : "Save"}</button>
        </form>
      ) : (
        <div className="answer-row">
          <button className="btn btn-primary btn-sm" onClick={confirm} disabled={busy}><Check size={14} />Yes, correct</button>
          <button className="btn btn-sm" onClick={() => setEditing(true)} disabled={busy}><Pencil size={14} />Correct it</button>
        </div>
      )}
      {error && <div id={`${id}-err`} className="field-error" role="alert">{error}</div>}
    </div>
  );
}

const Val = ({ v }: { v: string | null | undefined }) => (v ? <>{v}</> : <span className="missing">Missing</span>);

export function InvoiceDrawer({ invoice, onClose, onUpdated, onDelete }: {
  invoice: Invoice; onClose: () => void; onUpdated: (inv: Invoice, msg: string) => void; onDelete: (id: string) => void;
}) {
  const closeBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [invoice.id, onClose]);

  const questions = invoice.issues.filter((i) => i.answerable);
  // OCR read-backs first (one tap to confirm), then genuinely missing details.
  const OCR_CODES = ["UNCONFIRMED_", "MISSING_DATE", "MISSING_TOTAL", "MISSING_COMPANY"];
  const isOcr = (q: Issue) => OCR_CODES.some((c) => q.code.startsWith(c));
  const groups = [
    { title: "Check what we read", items: questions.filter(isOcr) },
    { title: questions.some(isOcr) ? "Add missing details" : "", items: questions.filter((q) => !isOcr(q)) },
  ].filter((g) => g.items.length);
  const other = invoice.issues.filter((i) => !i.answerable);
  const { seller, buyer } = invoice;

  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <header className="drawer-head">
          <ScoreRing value={invoice.score} size={52} stroke={5} />
          <div className="drawer-title">
            <h2 id="drawer-title">{invoice.invoiceNumber ?? invoice.file ?? "Invoice"}</h2>
            <StatusChip status={invoice.status} />
          </div>
          <button ref={closeBtn} className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close details"><X size={18} /></button>
        </header>

        <div className="drawer-body">
          <section aria-labelledby="sec-q">
            <h3 className="section-title" id="sec-q">Questions for you <span className="count">{questions.length}</span></h3>
            {questions.length === 0 ? (
              <div className="done-state"><PartyPopper size={18} aria-hidden />
                {invoice.status === "ready" ? "All set. This invoice is ready for your ASP." : "Nothing to answer here."}
              </div>
            ) : groups.map((g) => (
              <div key={g.title} style={{ marginBottom: 14 }}>
                {g.title && <div className="cell-sub" style={{ margin: "0 0 8px", fontWeight: 550 }}>{g.title}</div>}
                {g.items.map((q) => <Question key={q.code + q.field} issue={q} invoiceId={invoice.id} onUpdated={onUpdated} />)}
              </div>
            ))}
          </section>

          {other.length > 0 && (
            <section aria-labelledby="sec-o">
              <h3 className="section-title" id="sec-o">Fix in the source document <span className="count">{other.length}</span></h3>
              <div className="card" style={{ padding: "4px 14px", boxShadow: "none" }}>
                {other.map((o) => (
                  <div className="info-item" key={o.code + o.field}>
                    <Info size={15} color={o.severity === "error" ? "var(--err)" : "var(--warn)"} style={{ flex: "none", marginTop: 2 }} aria-hidden />
                    <span>{o.message}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="sec-p">
            <h3 className="section-title" id="sec-p">Parties</h3>
            <dl className="kv">
              <div><dt>Seller</dt><dd><Val v={seller.name} /></dd></div>
              <div><dt>Buyer</dt><dd><Val v={buyer.name} /></dd></div>
              <div><dt>Seller TRN</dt><dd className="mono"><Val v={seller.trn} /></dd></div>
              <div><dt>Buyer TRN</dt><dd className="mono"><Val v={buyer.trn} /></dd></div>
              <div><dt>Issue date</dt><dd><Val v={fmtDate(invoice.issueDate)} /></dd></div>
              <div><dt>Source</dt><dd>{invoice.source === "scan" ? "Scanned document (OCR)" : invoice.source === "json" ? "Uploaded data" : "Sample data"}</dd></div>
            </dl>
          </section>

          <section aria-labelledby="sec-l">
            <h3 className="section-title" id="sec-l">Line items <span className="count">{invoice.lines.length}</span></h3>
            {invoice.lines.length === 0 ? <p className="cell-sub" style={{ margin: 0 }}>No line items were found on this document.</p> : (
              <table className="lines">
                <thead><tr><th>Description</th><th className="right">Qty</th><th className="right">Price</th><th className="right">VAT</th></tr></thead>
                <tbody>
                  {invoice.lines.map((l, n) => (
                    <tr key={n}>
                      <td><Val v={l.description} /></td>
                      <td className="right num">{l.quantity ?? "—"}</td>
                      <td className="right num">{l.unitPrice ?? "—"}</td>
                      <td className="right num">{l.vatRate != null ? `${Number(l.vatRate)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="totals num">
              <div><span>Net</span><span>{fmtMoney(invoice.totals.net, invoice.currency) ?? "—"}</span></div>
              <div><span>VAT</span><span>{fmtMoney(invoice.totals.vat, invoice.currency) ?? "—"}</span></div>
              <div><span>Total</span><span>{fmtMoney(invoice.totals.gross, invoice.currency) ?? "—"}</span></div>
            </div>
          </section>
        </div>

        <footer className="drawer-foot">
          <button className="btn btn-ghost btn-danger btn-sm" onClick={() => onDelete(invoice.id)}><Trash2 size={14} />Remove</button>
          {invoice.readyForAsp && invoice.lines.length > 0 ? (
            <a className="btn btn-primary" href={api.xmlUrl(invoice.id)} download><Download size={16} />Download UBL XML</a>
          ) : (
            <button className="btn btn-primary" disabled title="Answer the blocking questions first"><Download size={16} />Download UBL XML</button>
          )}
        </footer>
      </aside>
    </>
  );
}
