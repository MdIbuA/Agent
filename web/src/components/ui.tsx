import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { scoreColor, statusColor, type Status } from "../lib/api";
import { useI18n } from "../lib/i18n";

export function ScoreRing({ value, size = 64, stroke = 6, label }: { value: number; size?: number; stroke?: number; label?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ width: size, height: size }} role="img" aria-label={label ?? `Score ${value} out of 100`}>
      <svg width={size} height={size}>
        <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        <circle className="ring-bar" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke}
          stroke={scoreColor(value)} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} />
      </svg>
      <span className="ring-label num" style={{ fontSize: size * 0.27 }}>{Math.round(value)}</span>
    </div>
  );
}

const STATUS_ICON = { ready: CheckCircle2, review: AlertTriangle, blocked: XCircle };

export function StatusChip({ status }: { status: Status }) {
  const Icon = STATUS_ICON[status];
  const { t } = useI18n();
  return <span className={`chip chip-${status}`}><Icon size={13} aria-hidden />{t(`st_${status}`)}</span>;
}

// Colour follows status, not the number: an 85 that is still blocked must not look healthy.
export function ScoreBar({ value, status }: { value: number; status: Status }) {
  return (
    <div className="score" aria-label={`Readiness score ${value}`}>
      <div className="score-bar"><span style={{ width: `${value}%`, background: statusColor[status] }} /></div>
      <span className="num cell-sub" style={{ width: 26, textAlign: "right" }}>{value}</span>
    </div>
  );
}

// ---- Toasts -------------------------------------------------------------------
type Toast = { id: number; text: string };
const ToastCtx = createContext<(text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useCallback((text: string) => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-2), { id, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className="toast"><CheckCircle2 size={16} aria-hidden />{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
