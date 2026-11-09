import { Printer } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Report } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { ScoreRing } from "./ui";

const aed = (n: number, lang: string) =>
  `${lang === "ar" ? "" : "AED "}${n.toLocaleString(lang === "ar" ? "ar-AE" : "en-AE")}${lang === "ar" ? " درهم" : ""}`;

export function ReportView({ refreshKey }: { refreshKey: number }) {
  const { t, lang } = useI18n();
  const [r, setR] = useState<Report | null>(null);
  useEffect(() => { api.report().then(setR).catch(() => setR(null)); }, [refreshKey]);
  if (!r) return <div className="card skeleton" style={{ height: 240 }} />;
  const s = r.summary;
  const maxIssue = Math.max(1, ...r.topIssues.map((i) => i.invoices));

  return (
    <article className="card report">
      <header className="report-head">
        <div>
          <h2>{t("repTitle")}</h2>
          <div className="cell-sub">{t("generated")} {new Date().toLocaleString(lang === "ar" ? "ar-AE" : "en-GB")}</div>
        </div>
        <button className="btn no-print" onClick={() => window.print()}><Printer size={16} />{t("print")}</button>
      </header>

      <div className="report-grid">
        <div className="report-score">
          <ScoreRing value={s.readinessPct} size={110} stroke={10} />
          <div>
            <div className="kpi-label">{t("kpiReadiness")}</div>
            <div className="kpi-value num">{s.readinessPct}%</div>
            <div className="cell-sub">{s.ready} {t("kpiOf")} {s.invoices} {t("kpiInvoices")}</div>
          </div>
        </div>
        <div className="exposure">
          <div className="kpi-label">{t("repExposure")}</div>
          <div className="exposure-value num">{aed(r.exposureAed, lang)}</div>
          <div className="cell-sub">{r.notReady} {t("repNotReady")}</div>
          <p className="note">{t("repExposureNote", { per: r.penaltyBasis.perInvoice, cap: r.penaltyBasis.monthlyCap.toLocaleString() })}</p>
        </div>
      </div>

      <h3 className="section-title">{t("repTopIssues")}</h3>
      <div className="bars">
        {r.topIssues.map((i) => (
          <div className="bar-row" key={i.code}>
            <span>{i.label}</span>
            <div className="bar"><span style={{ width: `${(100 * i.invoices) / maxIssue}%` }} /></div>
            <span className="num">{i.invoices}</span>
          </div>
        ))}
      </div>

      <h3 className="section-title">{t("repAgent")}</h3>
      <div className="agent-stats">
        <div><strong className="num">{r.answersReusedByAgent}</strong> {t("repReused")}</div>
        <div><strong className="num">{r.customerRequests}</strong> {t("repRequests")}</div>
        <div><strong className="num">{s.openQuestions}</strong> {t("kpiQuestions").toLowerCase()}</div>
      </div>
    </article>
  );
}
