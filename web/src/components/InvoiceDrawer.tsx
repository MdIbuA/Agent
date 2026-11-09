import { Check, Download, Info, PartyPopper, Pencil, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, fieldHint, fmtDate, fmtMoney, type Invoice, type Issue } from "../lib/api";
import { ScoreRing, StatusChip } from "./ui";
import { hintText, messageText, questionText, useI18n } from "../lib/i18n";

// Client-side checks mirror the server rules so the owner gets instant feedback.
function check(field: string, v: string): string | null {
  const s = v.trim();
  if (!s) return "Enter or choose a value.";
  if (field.endsWith(".trn") && !/^1\d{12}03$/.test(s.replace(/[\s-]/g, "")))
    return "A UAE TRN has 15 digits, starts with 1 and ends with 03.";
  if (field === "gross_total" && !/^\d+(\.\d{1,2})?$/.test(s.replace(/,/g, ""))) return "Enter an amount like 1250.00.";
  return null;
}

function Question({ issue, invoiceId, onUpdated }: {
  issue: Issue; invoiceId: string; onUpdated: (inv: Invoice, msg: string) => void;
}) {
  const { t, lang } = useI18n();
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
      onUpdated(item, t("toastSaved"));
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
      onUpdated(item, t("yesCorrect"));
    } finally {
      setBusy(false);
    }
  };

  const id = `q-${invoiceId}-${issue.code}`;
  return (
    <div className="question" data-severity={issue.severity}>
      <label htmlFor={id} className="question-text">{questionText(issue, lang)}</label>
      {hint.hint && editing && <div className="question-hint">{hintText(issue.field, hint.hint, lang)}</div>}
      {editing ? (
        <form className="answer-row" onSubmit={submit} noValidate>
          {hint.options ? (
            <select id={id} className="input" value={value} aria-invalid={!!error}
              aria-describedby={error ? `${id}-err` : undefined}
              onChange={(e) => { setValue(e.target.value); setError(null); }}>
              <option value="" disabled>{hint.placeholder}</option>
              {hint.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ) : (
            <input id={id} className="input" value={value} placeholder={hint.placeholder} inputMode={hint.inputMode}
              autoComplete="off" aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
              onChange={(e) => { setValue(e.target.value); setError(null); }} />
          )}
          <button className="btn btn-primary" disabled={busy}>{busy ? <span className="spinner" /> : t("save")}</button>
        </form>
      ) : (
        <div className="answer-row">
          <button className="btn btn-primary btn-sm" onClick={confirm} disabled={busy}><Check size={14} />{t("yesCorrect")}</button>
          <button className="btn btn-sm" onClick={() => setEditing(true)} disabled={busy}><Pencil size={14} />{t("correctIt")}</button>
        </div>
      )}
      {error && <div id={`${id}-err`} className="field-error" role="alert">{error}</div>}
    </div>
  );
}

function ConfirmAll({ invoiceId, fields, onUpdated }: {
  invoiceId: string; fields: string[]; onUpdated: (inv: Invoice, msg: string) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      let last: Invoice | null = null;
      for (const f of fields) last = (await api.confirm(invoiceId, f)).item;
      if (last) onUpdated(last, `${t("allCorrect")} (${fields.length})`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn btn-sm" onClick={run} disabled={busy}>
      {busy ? <span className="spinner" /> : <Check size={14} />}{t("allCorrect")} ({fields.length})
    </button>
  );
}

function Val({ v }: { v: string | null | undefined }) {
  const { t } = useI18n();
  return v ? <>{v}</> : <span className="missing">{t("missing")}</span>;
}

export function InvoiceDrawer({ invoice, onClose, onUpdated, onDelete }: {
  invoice: Invoice; onClose: () => void; onUpdated: (inv: Invoice, msg: string) => void; onDelete: (id: string) => void;
}) {
  const { t, lang } = useI18n();
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
    { title: t("checkRead"), items: questions.filter(isOcr) },
    { title: questions.some(isOcr) ? t("addMissing") : "", items: questions.filter((q) => !isOcr(q)) },
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
            <h3 className="section-title" id="sec-q">{t("questionsForYou")} <span className="count">{questions.length}</span></h3>
            {questions.length === 0 ? (
              <div className="done-state"><PartyPopper size={18} aria-hidden />
                {invoice.status === "ready" ? t("allSet") : t("nothingToAnswer")}
              </div>
            ) : groups.map((g) => (
              <div key={g.title} style={{ marginBottom: 14 }}>
                {g.title && (
                  <div className="group-head">
                    <span className="cell-sub" style={{ fontWeight: 550 }}>{g.title}</span>
                    {g.items.length > 1 && g.items.every((q) => q.code.startsWith("UNCONFIRMED")) && (
                      <ConfirmAll invoiceId={invoice.id} fields={g.items.map((q) => q.field)} onUpdated={onUpdated} />
                    )}
                  </div>
                )}
                {g.items.map((q) => <Question key={q.code + q.field} issue={q} invoiceId={invoice.id} onUpdated={onUpdated} />)}
              </div>
            ))}
          </section>

          {other.length > 0 && (
            <section aria-labelledby="sec-o">
              <h3 className="section-title" id="sec-o">{t("fixInSource")} <span className="count">{other.length}</span></h3>
              <div className="card" style={{ padding: "4px 14px", boxShadow: "none" }}>
                {other.map((o) => (
                  <div className="info-item" key={o.code + o.field}>
                    <Info size={15} color={o.severity === "error" ? "var(--err)" : "var(--warn)"} style={{ flex: "none", marginTop: 2 }} aria-hidden />
                    <span>{messageText(o, lang)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="sec-p">
            <h3 className="section-title" id="sec-p">{t("parties")}</h3>
            {invoice.learned.length > 0 && (
              <div className="learned"><Sparkles size={14} aria-hidden />{t(invoice.learnedFromProfile ? "learnedProfile" : "learnedNote")}</div>
            )}
            <dl className="kv">
              <div><dt>{t("seller")}</dt><dd><Val v={seller.name} /></dd></div>
              <div><dt>{t("buyer")}</dt><dd><Val v={buyer.name} /></dd></div>
              <div><dt>{t("sellerTrn")}</dt><dd className="mono"><Val v={seller.trn} /></dd></div>
              <div><dt>{t("buyerTrn")}</dt><dd className="mono"><Val v={buyer.trn} /></dd></div>
              <div><dt>{t("issueDate")}</dt><dd><bdi><Val v={fmtDate(invoice.issueDate)} /></bdi></dd></div>
              <div><dt>{t("source")}</dt><dd>{t(`src_${invoice.source}`)}{invoice.extractor && <div className="cell-sub">{t("readBy")} {invoice.extractor.replace("AI", "AI (Gemini)")}</div>}</dd></div>
            </dl>
          </section>

          <section aria-labelledby="sec-l">
            <h3 className="section-title" id="sec-l">{t("lineItems")} <span className="count">{invoice.lines.length}</span></h3>
            {invoice.lines.length === 0 ? <p className="cell-sub" style={{ margin: 0 }}>{t("noLines")}</p> : (
              <table className="lines">
                <thead><tr><th>{t("description")}</th><th className="right">{t("qty")}</th><th className="right">{t("price")}</th><th className="right">{t("vat")}</th></tr></thead>
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
              <div><span>{t("net")}</span><span>{fmtMoney(invoice.totals.net, invoice.currency) ?? "—"}</span></div>
              <div><span>{t("vat")}</span><span>{fmtMoney(invoice.totals.vat, invoice.currency) ?? "—"}</span></div>
              <div><span>{t("total")}</span><span>{fmtMoney(invoice.totals.gross, invoice.currency) ?? "—"}</span></div>
            </div>
          </section>
        </div>

        <footer className="drawer-foot">
          <button className="btn btn-ghost btn-danger btn-sm" onClick={() => onDelete(invoice.id)}><Trash2 size={14} />{t("remove")}</button>
          {invoice.readyForAsp && invoice.lines.length > 0 ? (
            <a className="btn btn-primary" href={api.xmlUrl(invoice.id)} download><Download size={16} />{t("downloadXml")}</a>
          ) : (
            <button className="btn btn-primary" disabled title="Answer the blocking questions first"><Download size={16} />{t("downloadXml")}</button>
          )}
        </footer>
      </aside>
    </>
  );
}
