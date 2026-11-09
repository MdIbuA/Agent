import { Copy, Mail, MessageCircle, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type CustomerRequest } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useToast } from "./ui";

export function Requests({ refreshKey }: { refreshKey: number }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const [items, setItems] = useState<CustomerRequest[] | null>(null);
  useEffect(() => { api.outreach().then((r) => setItems(r.requests)).catch(() => setItems([])); }, [refreshKey]);

  if (items === null) return <div className="card skeleton" style={{ height: 160 }} />;
  if (items.length === 0) return <section className="card empty"><Users size={22} color="var(--text-3)" /><p>{t("reqNone")}</p></section>;

  return (
    <section className="requests">
      {items.map((r) => {
        const msg = lang === "ar" ? r.messageAr : r.messageEn;
        return (
          <article className="card request" key={(r.buyer ?? "") + r.invoices.join()}>
            <header className="request-head">
              <div>
                <h3>{r.buyer ?? "—"}</h3>
                <div className="cell-sub">{r.invoices.length} {t("reqInvoices")} · {r.invoices.join(", ")}</div>
              </div>
            </header>
            <pre className="message" dir={lang === "ar" ? "rtl" : "ltr"}>{msg}</pre>
            <div className="request-actions">
              <button className="btn btn-sm" onClick={() => navigator.clipboard.writeText(msg).then(() => toast(t("copied")))}>
                <Copy size={14} />{t("copy")}
              </button>
              <a className="btn btn-sm" href={`https://wa.me/?text=${encodeURIComponent(msg)}`} target="_blank" rel="noreferrer">
                <MessageCircle size={14} />{t("whatsapp")}
              </a>
              <a className="btn btn-sm" href={`mailto:?subject=${encodeURIComponent("E-invoicing details")}&body=${encodeURIComponent(msg)}`}>
                <Mail size={14} />{t("email")}
              </a>
            </div>
          </article>
        );
      })}
    </section>
  );
}
