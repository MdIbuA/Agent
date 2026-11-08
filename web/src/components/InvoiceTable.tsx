import { ArrowDown, ArrowUp, FileText, ScanLine, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { fmtDate, fmtMoney, isValidIsoDate, type Invoice, type Status } from "../lib/api";
import { ScoreBar, StatusChip } from "./ui";

type Filter = "all" | Status;
type SortKey = "score" | "issueDate" | "gross";

export function InvoiceTable({ items, query, selectedId, onOpen }: {
  items: Invoice[]; query: string; selectedId: string | null; onOpen: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "score", dir: 1 });

  const counts = useMemo(() => ({
    all: items.length,
    blocked: items.filter((i) => i.status === "blocked").length,
    review: items.filter((i) => i.status === "review").length,
    ready: items.filter((i) => i.status === "ready").length,
  }), [items]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const val = (i: Invoice) => sort.key === "score" ? i.score
      : sort.key === "gross" ? Number(i.totals.gross ?? -1) : i.issueDate ?? "";
    return items
      .filter((i) => filter === "all" || i.status === filter)
      .filter((i) => !q || [i.invoiceNumber, i.file, i.seller.name, i.buyer.name, i.seller.trn, i.buyer.trn]
        .some((v) => v?.toLowerCase().includes(q)))
      .sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [items, filter, query, sort]);

  const sortBtn = (key: SortKey, label: string) => {
    const active = sort.key === key;
    const Icon = sort.dir === 1 ? ArrowUp : ArrowDown;
    return (
      <th aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={key === "gross" ? "right" : ""}>
        <button onClick={() => setSort({ key, dir: active ? (-sort.dir as 1 | -1) : 1 })}>
          {label}{active && <Icon size={12} aria-hidden />}
        </button>
      </th>
    );
  };

  const tabs: { key: Filter; label: string }[] = [
    { key: "all", label: "All" }, { key: "blocked", label: "Blocked" },
    { key: "review", label: "Needs review" }, { key: "ready", label: "Ready" },
  ];

  return (
    <section className="card" aria-label="Invoices">
      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Filter by status">
          {tabs.map((t) => (
            <button key={t.key} aria-pressed={filter === t.key} onClick={() => setFilter(t.key)}>
              {t.label}<span className="count num">{counts[t.key]}</span>
            </button>
          ))}
        </div>
        <span className="cell-sub">{rows.length} shown · sorted by {sort.key === "gross" ? "total" : sort.key === "issueDate" ? "date" : "score"}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th className="hide-sm">Seller → Buyer</th>
              {sortBtn("issueDate", "Date")}
              {sortBtn("gross", "Total")}
              {sortBtn("score", "Score")}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => {
              const Icon = i.source === "scan" ? ScanLine : FileText;  // pdf/xml/json are digital
              const q = i.issues.filter((x) => x.answerable).length;
              return (
                <tr key={i.id} aria-selected={selectedId === i.id} tabIndex={0}
                  onClick={() => onOpen(i.id)} onKeyDown={(e) => e.key === "Enter" && onOpen(i.id)}>
                  <td>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <Icon size={16} color="var(--text-3)" aria-label={i.source === "scan" ? "Scanned" : "Digital"} />
                      <div>
                        <div className="cell-primary">{i.invoiceNumber ?? <span className="missing">No number</span>}</div>
                        <div className="cell-sub">{q ? `${q} question${q > 1 ? "s" : ""}` : i.file}</div>
                      </div>
                    </div>
                  </td>
                  <td className="hide-sm">
                    <div>{i.seller.name ?? <span className="missing">Unknown seller</span>}</div>
                    <div className="cell-sub">→ {i.buyer.name ?? "Unknown buyer"}</div>
                  </td>
                  <td className="num">
                    {!i.issueDate ? <span className="missing">—</span>
                      : isValidIsoDate(i.issueDate) ? fmtDate(i.issueDate)
                      : <span style={{ color: "var(--err)" }} title="Not a valid date">{i.issueDate}</span>}
                  </td>
                  <td className="num right">{fmtMoney(i.totals.gross, i.currency) ?? <span className="missing">—</span>}</td>
                  <td><ScoreBar value={i.score} status={i.status} /></td>
                  <td><StatusChip status={i.status} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="empty" style={{ padding: 40 }}>
            <Search size={20} color="var(--text-3)" aria-hidden />
            <p>No invoices match{query ? ` “${query}”` : " this filter"}.</p>
          </div>
        )}
      </div>
    </section>
  );
}
