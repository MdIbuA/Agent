import { BookOpen, Download, FileBarChart, FileStack, Languages, LayoutGrid, Lock, Moon, Plus, Search, ShieldCheck, Sparkles, Sun, Trash2, Users, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dropzone } from "./components/Dropzone";
import { InvoiceDrawer } from "./components/InvoiceDrawer";
import { InvoiceTable } from "./components/InvoiceTable";
import { Kpis, KpisSkeleton } from "./components/Kpis";
import { ReportView } from "./components/ReportView";
import { Requests } from "./components/Requests";
import { useToast } from "./components/ui";
import { api, ApiError, type Invoice, type State } from "./lib/api";
import { useI18n, type Key } from "./lib/i18n";

type Theme = "light" | "dark";
type View = "readiness" | "requests" | "report";
const initialTheme = (): Theme =>
  (localStorage.getItem("qaid-theme") as Theme | null) ??
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

export default function App() {
  const { t, lang, setLang } = useI18n();
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [view, setView] = useState<View>("readiness");
  const [refreshKey, setRefreshKey] = useState(0);
  const [ai, setAi] = useState<{ on: boolean; model: string | null }>({ on: false, model: null });
  const searchRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("qaid-theme", theme);
  }, [theme]);

  useEffect(() => {
    api.health().then((h) => setAi({ on: h.ai, model: h.aiModel })).catch(() => {});
  }, []);

  const reload = useCallback(() => api.list().then(setState).then(() => setRefreshKey((k) => k + 1))
    .catch((e) => setError(e instanceof ApiError ? e.message : String(e))), []);
  useEffect(() => { reload(); }, [reload]);

  useEffect(() => { // "/" focuses search, like most productivity apps
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = async (fn: () => Promise<State>, msg?: (s: State) => string) => {
    setBusy(true); setError(null);
    try { const s = await fn(); setState(s); setRefreshKey((k) => k + 1); if (msg) toast(msg(s)); return s; }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const onFiles = async (files: File[]) => {
    const before = state?.summary.invoices ?? 0;
    setBusy(true); setError(null);
    try {
      const r = await api.upload(files);
      setState(r); setShowUpload(false); setRefreshKey((k) => k + 1);
      const added = r.summary.invoices - before;
      if (added) toast(`+${added}`);
      if (r.errors.length) setError(r.errors.map((x) => `${x.file}: ${x.error}`).join(" · "));
    } catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const onUpdated = useCallback((inv: Invoice, msg: string) => {
    const applied = inv.appliedTo?.length ?? 0;
    if (applied) {
      reload();  // the agent filled the same fact into other invoices: refresh everything
      toast(t("toastApplied", { n: applied }));
      return;
    }
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
    setRefreshKey((k) => k + 1);
    toast(inv.status === "ready" ? t("toastReady") : msg);
  }, [toast, reload, t]);

  const close = useCallback(() => setOpenId(null), []);
  const open = state?.items.find((i) => i.id === openId) ?? null;
  const empty = state && state.items.length === 0;
  const nav: { id: View; icon: typeof LayoutGrid; label: Key; count?: number }[] = [
    { id: "readiness", icon: LayoutGrid, label: "navReadiness", count: state?.summary.invoices },
    { id: "requests", icon: Users, label: "navRequests" },
    { id: "report", icon: FileBarChart, label: "navReport" },
  ];
  const titles: Record<View, [Key, Key]> = {
    readiness: ["pageTitle", "pageSub"], requests: ["reqTitle", "reqSub"], report: ["repTitle", "repSub"],
  };

  return (
    <div className="shell">
      <aside className="sidebar no-print" aria-label="Main navigation">
        <div className="brand"><span className="brand-mark"><ShieldCheck size={16} /></span>Qaid <span className="brand-ar">قيد</span></div>
        <nav className="nav">
          <div className="nav-label">{t("workspace")}</div>
          {nav.map(({ id, icon: Icon, label, count }) => (
            <button key={id} className="nav-item" aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>
              <Icon size={16} />{t(label)}{count ? <span className="nav-count num">{count}</span> : null}
            </button>
          ))}
          <a className="nav-item" href={api.exportUrl}><FileStack size={16} />{t("navHandoff")}</a>
          <a className="nav-item" href="/docs" target="_blank" rel="noreferrer"><BookOpen size={16} />{t("navDocs")}</a>
        </nav>
        {/* Privacy notice must match reality: with AI assist on, unclear invoices go to Google. */}
        {ai.on ? (
          <div className="sidebar-foot sidebar-foot-ai">
            <strong><Sparkles size={12} style={{ verticalAlign: -1 }} /> {t("aiTitle")}</strong>
            {t("aiBody")}{ai.model ? ` (${ai.model})` : ""}
          </div>
        ) : (
          <div className="sidebar-foot">
            <strong><Lock size={12} style={{ verticalAlign: -1 }} /> {t("localTitle")}</strong>
            {t("localBody")}
          </div>
        )}
      </aside>

      <div className="main">
        <header className="topbar no-print">
          <span className="brand-mark show-sm" aria-label="Qaid"><ShieldCheck size={16} /></span>
          <label className="search">
            <Search size={16} aria-hidden />
            <span className="sr-only">{t("search")}</span>
            <input ref={searchRef} value={query} onChange={(e) => { setQuery(e.target.value); setView("readiness"); }} placeholder={t("search")} />
            <span className="kbd hide-sm" aria-hidden>/</span>
          </label>
          <div className="topbar-actions">
            <button className="btn btn-ghost" onClick={() => setLang(lang === "ar" ? "en" : "ar")} aria-label="Switch language">
              <Languages size={18} />{lang === "ar" ? "English" : "العربية"}
            </button>
            <button className="btn btn-ghost btn-icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>

        <main className="page">
          <div className="page-head no-print">
            <div>
              <h1>{t(titles[view][0])}</h1>
              <p>{t(titles[view][1])}</p>
            </div>
            {view === "readiness" && !empty && state && (
              <div className="head-actions">
                <button className="btn btn-ghost" onClick={() => run(api.clear)} disabled={busy}><Trash2 size={16} />{t("clear")}</button>
                <a className="btn" href={api.exportUrl} aria-disabled={state.summary.ready === 0}
                  onClick={(e) => { if (state.summary.ready === 0) { e.preventDefault(); setError("No invoices are ready to export yet."); } }}>
                  <Download size={16} />{t("exportReady")} ({state.summary.ready})
                </a>
                <button className="btn btn-primary" onClick={() => setShowUpload((v) => !v)}><Plus size={16} />{t("addInvoices")}</button>
              </div>
            )}
          </div>

          {error && <div className="banner" role="alert"><Zap size={16} style={{ flex: "none", marginTop: 2 }} />{error}</div>}

          {!state && !error && <KpisSkeleton />}

          {view === "readiness" && empty && (
            <section className="card empty">
              <div className="drop-icon"><Sparkles size={22} /></div>
              <h2>{t("emptyTitle")}</h2>
              <p>{t("emptyBody")}</p>
              <Dropzone onFiles={onFiles} busy={busy} />
              <button className="btn btn-ghost" onClick={() => run(() => api.sample(12))} disabled={busy}>
                <Sparkles size={16} />{t("trySample")}
              </button>
              <div className="trust">
                <span><ShieldCheck size={14} />{t("trust1")}</span>
                <span><Lock size={14} />{t("trust2")}</span>
                <span><FileStack size={14} />{t("trust3")}</span>
              </div>
            </section>
          )}

          {view === "readiness" && state && !empty && (
            <>
              {showUpload && <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}><Dropzone onFiles={onFiles} busy={busy} /></div>}
              <Kpis s={state.summary} />
              <InvoiceTable items={state.items} query={query} selectedId={openId} onOpen={setOpenId} />
            </>
          )}
          {view === "requests" && <Requests refreshKey={refreshKey} />}
          {view === "report" && <ReportView refreshKey={refreshKey} />}
        </main>
      </div>

      {open && (
        <InvoiceDrawer invoice={open} onClose={close} onUpdated={onUpdated}
          onDelete={(id) => { setOpenId(null); run(() => api.remove(id)); }} />
      )}
    </div>
  );
}
