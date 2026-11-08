// Typed client for the Python API (ira/server.py). Shapes mirror ira/service.py:serialize.

export type Status = "ready" | "review" | "blocked";

export interface Issue {
  code: string;
  severity: "error" | "warning";
  field: string;
  message: string;
  question: string;
  answerable: boolean;
}

export interface Party { name: string | null; trn: string | null; address: string | null }

export interface Line {
  description: string | null;
  quantity: string | null;
  unitPrice: string | null;
  vatRate: string | null;
  lineTotal: string | null;
}

export interface Invoice {
  id: string;
  source: "sample" | "json" | "scan";
  file: string | null;
  invoiceNumber: string | null;
  issueDate: string | null;
  currency: string;
  seller: Party;
  buyer: Party;
  lines: Line[];
  totals: { net: string | null; vat: string | null; gross: string | null };
  status: Status;
  readyForAsp: boolean;
  score: number;
  issues: Issue[];
}

export interface Summary {
  invoices: number;
  ready: number;
  review: number;
  blocked: number;
  readinessPct: number;
  avgScore: number;
  openQuestions: number;
}

export interface State { summary: Summary; items: Invoice[] }
export interface UploadResult extends State { errors: { file: string; error: string }[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach the Qaid server. Is it running?");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<{ ok: boolean; ocr: string | null }>("/api/health"),
  list: () => request<State>("/api/invoices"),
  sample: (count = 12) => request<State>(`/api/invoices/sample?count=${count}`, { method: "POST" }),
  upload: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<UploadResult>("/api/invoices/upload", { method: "POST", body: form });
  },
  answer: (id: string, field: string, value: string) =>
    request<{ item: Invoice; summary: Summary }>(`/api/invoices/${id}/answer`, json({ field, value })),
  confirm: (id: string, field: string) =>
    request<{ item: Invoice; summary: Summary }>(`/api/invoices/${id}/confirm`, json({ field })),
  remove: (id: string) => request<State>(`/api/invoices/${id}`, { method: "DELETE" }),
  clear: () => request<State>("/api/invoices", { method: "DELETE" }),
  xmlUrl: (id: string) => `/api/invoices/${id}/xml`,
  exportUrl: "/api/export.zip",
};

// ---- formatting helpers -----------------------------------------------------
export const fmtMoney = (v: string | null, currency = "AED") =>
  v == null ? null : `${currency} ${Number(v).toLocaleString("en-AE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const isValidIsoDate = (iso: string | null) =>
  !!iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) && !Number.isNaN(new Date(`${iso}T00:00:00`).getTime())
  && new Date(`${iso}T00:00:00`).toISOString().startsWith(iso);

export const fmtDate = (iso: string | null) => {
  if (!iso) return null;
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

export const statusLabel: Record<Status, string> = { ready: "Ready for ASP", review: "Needs review", blocked: "Blocked" };

export const statusColor: Record<Status, string> = { ready: "var(--ok)", review: "var(--warn)", blocked: "var(--err)" };

export const scoreColor = (s: number) => (s >= 85 ? "var(--ok)" : s >= 50 ? "var(--warn)" : "var(--err)");

// Input hints for owner answers, keyed by field.
export const fieldHint: Record<string, { placeholder: string; hint?: string; inputMode?: "numeric" | "decimal" | "text" }> = {
  "seller.trn": { placeholder: "100 1234 5678 9012", hint: "15 digits. Spaces and dashes are fine.", inputMode: "numeric" },
  "buyer.trn": { placeholder: "100 1234 5678 9012", hint: "15 digits. Spaces and dashes are fine.", inputMode: "numeric" },
  issue_date: { placeholder: "25/12/2026", hint: "Day first, as printed on the invoice." },
  invoice_number: { placeholder: "e.g. INV-2026-0042" },
  gross_total: { placeholder: "0.00", inputMode: "decimal" },
  "seller.name": { placeholder: "Registered legal name" },
  "buyer.name": { placeholder: "Registered legal name" },
  "seller.address": { placeholder: "Street, area, emirate" },
  "buyer.address": { placeholder: "Street, area, emirate" },
};
