import { BookOpen, Download, FileStack, LayoutGrid, Moon, Plus, Search, ShieldCheck, Sparkles, Sun, Trash2, Zap, Lock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dropzone } from "./components/Dropzone";
import { InvoiceDrawer } from "./components/InvoiceDrawer";
import { InvoiceTable } from "./components/InvoiceTable";
import { Kpis, KpisSkeleton } from "./components/Kpis";
import { useToast } from "./components/ui";
import { api, ApiError, type Invoice, type State } from "./lib/api";

type Theme = "light" | "dark";
const initialTheme = (): Theme =>
  (localStorage.getItem("qaid-theme") as Theme | null) ??
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const searchRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("qaid-theme", theme);
  }, [theme]);

  useEffect(() => {
    api.list().then(setState).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => { // "/" focuses search, like most productivity apps
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = async (fn: () => Promise<State>, msg?: (s: State) => string) => {
    setBusy(true); setError(null);
    try { const s = await fn(); setState(s); if (msg) toast(msg(s)); return s; }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const onFiles = async (files: File[]) => {
    const before = state?.summary.invoices ?? 0;
    setBusy(true); setError(null);
    try {
      const r = await api.upload(files);
      setState(r); setShowUpload(false);
      const added = r.summary.invoices - before;
      if (added) toast(`${added} invoice${added > 1 ? "s" : ""} added`);
      if (r.errors.length) setError(r.errors.map((x) => `${x.file}: ${x.error}`).join(" · "));
    } catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const onUpdated = useCallback((inv: Invoice, msg: string) => {
    setState((s) => {
      if (!s) return s;
      const items = s.items.map((i) => (i.id === inv.id ? inv : i));
      const ready = items.filter((i) => i.status === "ready").length;
      return {
        items,
        summary: {
          ...s.summary,
          ready, review: items.filter((i) => i.status === "review").length,
          blocked: items.filter((i) => i.status === "blocked").length,
          readinessPct: Math.round((1000 * ready) / items.length) / 10,
          avgScore: Math.round((10 * items.reduce((a, i) => a + i.score, 0)) / items.length) / 10,
          openQuestions: items.reduce((a, i) => a + i.issues.filter((q) => q.answerable).length, 0),
        },
      };
    });
    toast(inv.status === "ready" ? "Invoice is ready for your ASP" : msg);
  }, [toast]);

  const close = useCallback(() => setOpenId(null), []);
  const open = state?.items.find((i) => i.id === openId) ?? null;
  const empty = state && state.items.length === 0;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand"><span className="brand-mark"><ShieldCheck size={16} /></span>Qaid</div>
        <nav className="nav">
          <div className="nav-label">Workspace</div>
          <a className="nav-item" aria-current="page" href="#"><LayoutGrid size={16} />Readiness<span className="nav-count num">{state?.summary.invoices ?? ""}</span></a>
          <a className="nav-item" href={api.exportUrl}><FileStack size={16} />ASP hand-off pack</a>
          <a className="nav-item" href="/docs" target="_blank" rel="noreferrer"><BookOpen size={16} />API docs</a>
        </nav>
        <div className="sidebar-foot">
          <strong><Lock size={12} style={{ verticalAlign: -1 }} /> Runs on your machine</strong>
          Scans are read by local OCR. Invoices never leave this computer.
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <span className="brand-mark show-sm" aria-label="Qaid"><ShieldCheck size={16} /></span>
          <label className="search">
            <Search size={16} aria-hidden />
            <span className="sr-only">Search invoices</span>
            <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search invoice, seller, buyer or TRN" />
            <span className="kbd hide-sm" aria-hidden>/</span>
          </label>
          <div className="topbar-actions">
            <button className="btn btn-ghost btn-icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>

        <main className="page">
          <div className="page-head">
            <div>
              <h1>E-invoicing readiness</h1>
              <p>Get every invoice PINT-AE ready before it reaches your Accredited Service Provider.</p>
            </div>
            {!empty && state && (
              <div className="head-actions">
                <button className="btn btn-ghost" onClick={() => run(api.clear, () => "Workspace cleared")} disabled={busy}><Trash2 size={16} />Clear</button>
                <a className="btn" href={api.exportUrl} aria-disabled={state.summary.ready === 0}
                  onClick={(e) => { if (state.summary.ready === 0) { e.preventDefault(); setError("No invoices are ready to export yet."); } }}>
                  <Download size={16} />Export ready ({state.summary.ready})
                </a>
                <button className="btn btn-primary" onClick={() => setShowUpload((v) => !v)}><Plus size={16} />Add invoices</button>
              </div>
            )}
          </div>

          {error && <div className="banner" role="alert"><Zap size={16} style={{ flex: "none", marginTop: 2 }} />{error}</div>}

          {!state && !error && <KpisSkeleton />}

          {empty && (
            <section className="card empty">
              <div className="drop-icon"><Sparkles size={22} /></div>
              <h2>Check your invoices in minutes</h2>
              <p>Upload photos, scans or exports. Qaid reads them, checks them against UAE e-invoicing rules, and asks you only what's missing.</p>
              <Dropzone onFiles={onFiles} busy={busy} />
              <button className="btn btn-ghost" onClick={() => run(() => api.sample(12), (s) => `${s.summary.invoices} sample invoices loaded`)} disabled={busy}>
                <Sparkles size={16} />Or try it with sample invoices
              </button>
              <div className="trust">
                <span><ShieldCheck size={14} />Deterministic VAT and TRN checks</span>
                <span><Lock size={14} />Offline OCR, no cloud upload</span>
                <span><FileStack size={14} />UBL 2.1 XML output</span>
              </div>
            </section>
          )}

          {state && !empty && (
            <>
              {showUpload && <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}><Dropzone onFiles={onFiles} busy={busy} /></div>}
              <Kpis s={state.summary} />
              <InvoiceTable items={state.items} query={query} selectedId={openId} onOpen={setOpenId} />
            </>
          )}
        </main>
      </div>

      {open && (
        <InvoiceDrawer invoice={open} onClose={close} onUpdated={onUpdated}
          onDelete={(id) => { setOpenId(null); run(() => api.remove(id), () => "Invoice removed"); }} />
      )}
    </div>
  );
}
