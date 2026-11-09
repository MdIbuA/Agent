import { CheckCircle2, AlertTriangle, XCircle, MessageCircleQuestion } from "lucide-react";
import type { Summary } from "../lib/api";
import { ScoreRing } from "./ui";
import { useI18n } from "../lib/i18n";

export function Kpis({ s }: { s: Summary }) {
  const { t } = useI18n();
  const cards = [
    { label: t("kpiReady"), value: s.ready, icon: CheckCircle2, color: "var(--ok)", sub: t("kpiReadySub") },
    { label: t("kpiReview"), value: s.review, icon: AlertTriangle, color: "var(--warn)", sub: t("kpiReviewSub") },
    { label: t("kpiBlocked"), value: s.blocked, icon: XCircle, color: "var(--err)", sub: t("kpiBlockedSub") },
    { label: t("kpiQuestions"), value: s.openQuestions, icon: MessageCircleQuestion, color: "var(--accent)", sub: t("kpiQuestionsSub") },
  ];
  return (
    <section className="kpis" aria-label="Readiness summary">
      <div className="card kpi kpi-hero">
        <ScoreRing value={s.readinessPct} size={84} stroke={8} label={`${s.readinessPct}% of invoices ready`} />
        <div>
          <div className="kpi-label">{t("kpiReadiness")}</div>
          <div className="kpi-value num">{s.readinessPct}%</div>
          <div className="kpi-sub">{s.ready} {t("kpiOf")} {s.invoices} {t("kpiInvoices")} · {t("kpiAvg")} {s.avgScore}</div>
        </div>
      </div>
      {cards.map(({ label, value, icon: Icon, color, sub }) => (
        <div className="card kpi" key={label}>
          <div className="kpi-label"><Icon size={15} color={color} aria-hidden />{label}</div>
          <div className="kpi-value num">{value}</div>
          <div className="kpi-sub">{sub}</div>
        </div>
      ))}
    </section>
  );
}

export function KpisSkeleton() {
  return (
    <section className="kpis" aria-hidden>
      {Array.from({ length: 5 }, (_, i) => (
        <div className="card kpi" key={i}>
          <div className="skeleton" style={{ height: 14, width: "50%" }} />
          <div className="skeleton" style={{ height: 28, width: "35%", marginTop: 6 }} />
          <div className="skeleton" style={{ height: 12, width: "70%", marginTop: 6 }} />
        </div>
      ))}
    </section>
  );
}
