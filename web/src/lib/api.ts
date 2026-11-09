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
  source: "sample" | "json" | "xml" | "pdf" | "scan";
  extractor: string | null;
  learned: string[];
  appliedTo?: string[];
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

export interface CustomerRequest {
  buyer: string | null; buyerTrn: string | null; seller: string | null;
  invoices: string[]; needs: string[]; messageEn: string; messageAr: string;
}

export interface Report {
  summary: Summary; notReady: number; exposureAed: number; exposureByMonth: Record<string, number>;
  penaltyBasis: { perInvoice: number; monthlyCap: number };
  topIssues: { code: string; label: string; invoices: number }[];
  answersReusedByAgent: number; customerRequests: number;
}
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
  health: () => request<{ ok: boolean; ocr: string | null; ai: boolean; aiModel: string | null }>("/api/health"),
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
  outreach: () => request<{ requests: CustomerRequest[] }>("/api/outreach"),
  report: () => request<Report>("/api/report"),
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
export interface FieldHint {
  placeholder: string;
  hint?: string;
  inputMode?: "numeric" | "decimal" | "text";
  options?: { value: string; label: string }[];
}

const EMIRATES = [
  { value: "DXB", label: "Dubai" }, { value: "AUH", label: "Abu Dhabi" }, { value: "SHJ", label: "Sharjah" },
  { value: "AJM", label: "Ajman" }, { value: "UAQ", label: "Umm Al Quwain" },
  { value: "RAK", label: "Ras Al Khaimah" }, { value: "FUJ", label: "Fujairah" },
];
// Official PINT AE payment means code list (UNCL4461 subset).
const PAYMENT_MEANS = [
  { value: "30", label: "Bank transfer" }, { value: "20", label: "Cheque" }, { value: "10", label: "Cash" },
  { value: "54", label: "Credit card" }, { value: "55", label: "Debit card" }, { value: "49", label: "Direct debit" },
  { value: "68", label: "Online payment link" }, { value: "21", label: "Banker's draft" },
  { value: "1", label: "Not specified" },
];
// Official UAE credit note reasons (CreditReason code list, Art. 61 VAT Decree-Law cases).
const CREDIT_REASONS = [
  { value: "DL8.61.1.D", label: "Goods or services returned" },
  { value: "DL8.61.1.A", label: "Supply cancelled" },
  { value: "DL8.61.1.C", label: "Agreed price changed (e.g. bad debt relief)" },
  { value: "DL8.61.1.E", label: "Tax charged or applied in error" },
  { value: "DL8.61.1.B", label: "Tax treatment changed" },
  { value: "VD", label: "Volume discount" },
];
const TRN_HINT = "15 digits, starting with 1 and ending with 03. Spaces and dashes are fine.";

export const fieldHint: Record<string, FieldHint> = {
  "seller.trn": { placeholder: "100 1234 5678 9003", hint: TRN_HINT, inputMode: "numeric" },
  "buyer.trn": { placeholder: "100 1234 5678 9003", hint: TRN_HINT, inputMode: "numeric" },
  "seller.emirate": { placeholder: "Choose emirate", options: EMIRATES },
  "buyer.emirate": { placeholder: "Choose emirate", options: EMIRATES },
  payment_means: { placeholder: "Choose payment method", options: PAYMENT_MEANS, hint: "Required on UAE e-invoices." },
  credit_reason: { placeholder: "Choose a reason", options: CREDIT_REASONS, hint: "Official UAE credit note reasons." },
  preceding_invoice: { placeholder: "e.g. INV-2026-0042", hint: "The invoice this credit note corrects." },
  due_date: { placeholder: "25/01/2027", hint: "Day first. Required when an amount is payable." },
  "seller.legal_id": { placeholder: "e.g. 1234567", hint: "As printed on the trade licence." },
  "seller.legal_authority": { placeholder: "e.g. Dubai Department of Economy and Tourism", hint: "The mainland or free-zone authority that issued the licence." },
  issue_date: { placeholder: "25/12/2026", hint: "Day first, as printed on the invoice." },
  invoice_number: { placeholder: "e.g. INV-2026-0042" },
  gross_total: { placeholder: "0.00", inputMode: "decimal" },
  "seller.name": { placeholder: "Registered legal name" },
  "buyer.name": { placeholder: "Registered legal name" },
  "seller.address": { placeholder: "Street, area, emirate" },
  "buyer.address": { placeholder: "Street, area, emirate" },
};
