import { Building2, Check } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type BusinessProfile } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";

const EMIRATES = [["DXB", "Dubai", "دبي"], ["AUH", "Abu Dhabi", "أبوظبي"], ["SHJ", "Sharjah", "الشارقة"], ["AJM", "Ajman", "عجمان"],
  ["UAQ", "Umm Al Quwain", "أم القيوين"], ["RAK", "Ras Al Khaimah", "رأس الخيمة"], ["FUJ", "Fujairah", "الفجيرة"]];
const PAYMENTS = [["30", "Bank transfer", "تحويل بنكي"], ["20", "Cheque", "شيك"], ["10", "Cash", "نقداً"],
  ["54", "Credit card", "بطاقة ائتمان"], ["55", "Debit card", "بطاقة خصم"], ["68", "Online payment link", "رابط دفع إلكتروني"]];

export function ProfileView({ onSaved }: { onSaved: (updated: number) => void }) {
  const { t, lang } = useI18n();
  const [p, setP] = useState<BusinessProfile>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.profile().then((r) => setP(r.profile ?? {})).catch(() => {}); }, []);

  const field = (k: keyof BusinessProfile, label: Key, ph = "", hint?: Key) => (
    <label className="form-field">
      <span>{t(label)}</span>
      <input className="input" value={p[k] ?? ""} placeholder={ph} onChange={(e) => setP({ ...p, [k]: e.target.value })} />
      {hint && <small>{t(hint)}</small>}
    </label>
  );
  const select = (k: keyof BusinessProfile, label: Key, opts: string[][]) => (
    <label className="form-field">
      <span>{t(label)}</span>
      <select className="input" value={p[k] ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value })}>
        <option value="">—</option>
        {opts.map(([v, en, ar]) => <option key={v} value={v}>{lang === "ar" ? ar : en}</option>)}
      </select>
    </label>
  );
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { const r = await api.saveProfile(p); setP(r.profile); onSaved(r.updatedInvoices); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
    finally { setBusy(false); }
  };

  return (
    <form className="card profile" onSubmit={submit}>
      <header className="profile-head">
        <span className="drop-icon"><Building2 size={22} /></span>
        <div><h2>{t("profTitle")}</h2><p className="cell-sub">{t("profBody")}</p></div>
      </header>
      <div className="form-grid">
        {field("name", "profName", "Al Noor Building Materials LLC")}
        {field("trn", "profTrn", "100 1234 5678 9003", "profTrnHint")}
        {field("legal_id", "profLicence", "784512")}
        {field("legal_authority", "profAuthority", "Dubai Department of Economy and Tourism")}
        {field("address", "profAddress", "Deira, Dubai")}
        {select("emirate", "profEmirate", EMIRATES)}
        {select("payment_means", "profPayment", PAYMENTS)}
        {field("payment_terms_days", "profTerms", "30", "profTermsHint")}
      </div>
      {error && <div className="field-error" role="alert">{error}</div>}
      <div><button className="btn btn-primary" disabled={busy}>{busy ? <span className="spinner" /> : <Check size={16} />}{t("profSave")}</button></div>
    </form>
  );
}
