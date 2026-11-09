// English / Arabic UI strings. Arabic switches the whole layout to right-to-left.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Issue } from "./api";

export type Lang = "en" | "ar";

const STRINGS = {
  // shell
  brandTagline: { en: "E-invoicing readiness", ar: "الجاهزية للفوترة الإلكترونية" },
  workspace: { en: "Workspace", ar: "مساحة العمل" },
  navReadiness: { en: "Readiness", ar: "الجاهزية" },
  navRequests: { en: "Customer requests", ar: "طلبات العملاء" },
  navReport: { en: "Readiness report", ar: "تقرير الجاهزية" },
  navHandoff: { en: "ASP hand-off pack", ar: "حزمة التسليم لمزوّد الخدمة" },
  navDocs: { en: "API docs", ar: "توثيق الواجهة البرمجية" },
  localTitle: { en: "Runs on your machine", ar: "يعمل على جهازك" },
  localBody: { en: "Scans are read by local OCR. Invoices never leave this computer.",
               ar: "تُقرأ المستندات الممسوحة محلياً. لا تغادر الفواتير هذا الجهاز." },
  aiTitle: { en: "AI assist is on", ar: "المساعد الذكي مُفعّل" },
  aiBody: { en: "Invoices the local reader can't fully read are sent to Google Gemini. Clear invoices stay on this computer.",
            ar: "تُرسل الفواتير التي يتعذر قراءتها محلياً إلى Google Gemini. تبقى الفواتير الواضحة على هذا الجهاز." },
  search: { en: "Search invoice, seller, buyer or TRN", ar: "ابحث برقم الفاتورة أو البائع أو المشتري أو الرقم الضريبي" },
  pageTitle: { en: "E-invoicing readiness", ar: "الجاهزية للفوترة الإلكترونية" },
  pageSub: { en: "Get every invoice PINT AE ready before it reaches your Accredited Service Provider.",
             ar: "جهّز كل فاتورة وفق معيار PINT AE قبل إرسالها إلى مزوّد الخدمة المعتمد." },
  clear: { en: "Clear", ar: "مسح" },
  exportReady: { en: "Export ready", ar: "تصدير الجاهزة" },
  addInvoices: { en: "Add invoices", ar: "إضافة فواتير" },
  // empty state
  emptyTitle: { en: "Check your invoices in minutes", ar: "افحص فواتيرك خلال دقائق" },
  emptyBody: { en: "Upload PDFs, scans or e-invoice files. Qaid reads them, checks them against UAE e-invoicing rules, and asks you only what's missing.",
               ar: "ارفع ملفات PDF أو المستندات الممسوحة أو الفواتير الإلكترونية. يقرأها قيد ويطابقها مع قواعد الفوترة الإلكترونية في الإمارات، ولا يسألك إلا عمّا ينقص." },
  trySample: { en: "Or try it with sample invoices", ar: "أو جرّب بفواتير نموذجية" },
  trust1: { en: "Official PINT AE rules", ar: "قواعد PINT AE الرسمية" },
  trust2: { en: "Offline OCR, no cloud upload", ar: "قراءة محلية دون رفع للسحابة" },
  trust3: { en: "UBL 2.1 XML output", ar: "مخرجات XML بصيغة UBL 2.1" },
  dropTitle: { en: "Drop invoices here, or click to browse", ar: "أفلت الفواتير هنا أو انقر للاختيار" },
  dropBusy: { en: "Reading your invoices…", ar: "جارٍ قراءة فواتيرك…" },
  dropHint: { en: "Excel or CSV invoice registers, PDF invoices, photos or scans, e-invoice XML · up to 25 files, 15 MB each",
              ar: "سجلات الفواتير Excel أو CSV، أو فواتير PDF، أو صور ومستندات ممسوحة، أو XML · حتى 25 ملفاً بحجم 15 ميغابايت لكل ملف" },
  // KPIs
  kpiReadiness: { en: "Workspace readiness", ar: "جاهزية مساحة العمل" },
  kpiOf: { en: "of", ar: "من" },
  kpiInvoices: { en: "invoices", ar: "فاتورة" },
  kpiAvg: { en: "avg score", ar: "متوسط الدرجة" },
  kpiReady: { en: "Ready for ASP", ar: "جاهزة لمزوّد الخدمة" },
  kpiReadySub: { en: "Valid UBL can be exported", ar: "يمكن تصدير UBL صالح" },
  kpiReview: { en: "Needs review", ar: "تحتاج مراجعة" },
  kpiReviewSub: { en: "Only confirmations left", ar: "تبقّت التأكيدات فقط" },
  kpiBlocked: { en: "Blocked", ar: "متوقفة" },
  kpiBlockedSub: { en: "Missing or invalid data", ar: "بيانات ناقصة أو غير صحيحة" },
  kpiQuestions: { en: "Open questions", ar: "أسئلة مفتوحة" },
  kpiQuestionsSub: { en: "Answer to unblock", ar: "أجب لإكمال الفواتير" },
  // table
  all: { en: "All", ar: "الكل" },
  ready: { en: "Ready", ar: "جاهزة" },
  colInvoice: { en: "Invoice", ar: "الفاتورة" },
  colParties: { en: "Seller → Buyer", ar: "البائع ← المشتري" },
  colDate: { en: "Date", ar: "التاريخ" },
  colTotal: { en: "Total", ar: "الإجمالي" },
  colScore: { en: "Score", ar: "الدرجة" },
  colStatus: { en: "Status", ar: "الحالة" },
  shown: { en: "shown", ar: "معروضة" },
  noNumber: { en: "No number", ar: "بلا رقم" },
  questions: { en: "questions", ar: "أسئلة" },
  question: { en: "question", ar: "سؤال" },
  noMatch: { en: "No invoices match", ar: "لا توجد فواتير مطابقة" },
  // statuses
  st_ready: { en: "Ready for ASP", ar: "جاهزة" },
  st_review: { en: "Needs review", ar: "تحتاج مراجعة" },
  st_blocked: { en: "Blocked", ar: "متوقفة" },
  // drawer
  questionsForYou: { en: "Questions for you", ar: "أسئلة لك" },
  checkRead: { en: "Check what we read", ar: "تحقّق مما قرأناه" },
  addMissing: { en: "Add missing details", ar: "أضف التفاصيل الناقصة" },
  allCorrect: { en: "All correct", ar: "كلها صحيحة" },
  yesCorrect: { en: "Yes, correct", ar: "نعم، صحيح" },
  correctIt: { en: "Correct it", ar: "تصحيح" },
  save: { en: "Save", ar: "حفظ" },
  allSet: { en: "All set. This invoice is ready for your ASP.", ar: "اكتمل كل شيء. الفاتورة جاهزة لمزوّد الخدمة." },
  nothingToAnswer: { en: "Nothing to answer here.", ar: "لا توجد أسئلة هنا." },
  fixInSource: { en: "Fix in the source document", ar: "يُصحَّح في المستند الأصلي" },
  parties: { en: "Parties", ar: "الأطراف" },
  seller: { en: "Seller", ar: "البائع" },
  buyer: { en: "Buyer", ar: "المشتري" },
  sellerTrn: { en: "Seller TRN", ar: "الرقم الضريبي للبائع" },
  buyerTrn: { en: "Buyer TRN", ar: "الرقم الضريبي للمشتري" },
  issueDate: { en: "Issue date", ar: "تاريخ الإصدار" },
  source: { en: "Source", ar: "المصدر" },
  lineItems: { en: "Line items", ar: "البنود" },
  noLines: { en: "No line items were found on this document.", ar: "لم يُعثر على بنود في هذا المستند." },
  description: { en: "Description", ar: "الوصف" },
  qty: { en: "Qty", ar: "الكمية" },
  price: { en: "Price", ar: "السعر" },
  vat: { en: "VAT", ar: "الضريبة" },
  net: { en: "Net", ar: "الصافي" },
  total: { en: "Total", ar: "الإجمالي" },
  remove: { en: "Remove", ar: "حذف" },
  downloadXml: { en: "Download UBL XML", ar: "تنزيل UBL XML" },
  missing: { en: "Missing", ar: "غير متوفر" },
  learnedProfile: { en: "Your details were filled in from your business profile", ar: "عُبّئت بياناتك من ملف المنشأة" },
  learnedNote: { en: "Filled in by the agent from your earlier answer", ar: "عبّأه الوكيل من إجابة سابقة لك" },
  readBy: { en: "Read by", ar: "قُرئ بواسطة" },
  src_scan: { en: "Scanned document (OCR)", ar: "مستند ممسوح (قراءة ضوئية)" },
  src_pdf: { en: "PDF (text layer)", ar: "ملف PDF نصي" },
  src_json: { en: "Uploaded data", ar: "بيانات مرفوعة" },
  src_xml: { en: "E-invoice XML", ar: "فاتورة إلكترونية XML" },
  src_sample: { en: "Sample data", ar: "بيانات نموذجية" },
  // toasts
  toastSaved: { en: "Answer saved", ar: "تم حفظ الإجابة" },
  toastReady: { en: "Invoice is ready for your ASP", ar: "الفاتورة جاهزة لمزوّد الخدمة" },
  toastApplied: { en: "Also applied to {n} other invoice(s) from the same business", ar: "طُبّقت أيضاً على {n} فاتورة أخرى للجهة نفسها" },
  // requests
  reqTitle: { en: "Customer requests", ar: "طلبات العملاء" },
  reqSub: { en: "The agent groups everything you need from each customer into one message. Review, then send it yourself.",
            ar: "يجمع الوكيل كل ما تحتاجه من كل عميل في رسالة واحدة. راجعها ثم أرسلها بنفسك." },
  reqNone: { en: "No customer details are missing. Nothing to request.", ar: "لا توجد بيانات ناقصة من العملاء." },
  reqInvoices: { en: "invoices", ar: "فواتير" },
  copy: { en: "Copy", ar: "نسخ" },
  copied: { en: "Message copied", ar: "تم نسخ الرسالة" },
  whatsapp: { en: "WhatsApp", ar: "واتساب" },
  email: { en: "Email", ar: "بريد إلكتروني" },
  // report
  repTitle: { en: "Readiness report", ar: "تقرير الجاهزية" },
  repSub: { en: "A one-page summary for the owner or accountant.", ar: "ملخص من صفحة واحدة للمالك أو المحاسب." },
  print: { en: "Print / save as PDF", ar: "طباعة / حفظ PDF" },
  repExposure: { en: "Indicative penalty exposure if not fixed", ar: "الغرامات المحتملة إن لم تُصحَّح (تقديرية)" },
  repExposureNote: { en: "AED {per} per invoice not issued electronically on time, capped at AED {cap} per month (published e-invoicing penalties). Indicative only; check current FTA decisions.",
                     ar: "{per} درهم لكل فاتورة لا تُصدر إلكترونياً في موعدها، بحد أقصى {cap} درهم شهرياً (وفق الغرامات المعلنة). تقدير فقط؛ يُرجى مراجعة قرارات الهيئة الاتحادية للضرائب." },
  repTopIssues: { en: "What's blocking your invoices", ar: "ما يوقف فواتيرك" },
  repAgent: { en: "Work done by the agent", ar: "ما أنجزه الوكيل" },
  repReused: { en: "answers reused across invoices", ar: "إجابات أُعيد استخدامها عبر الفواتير" },
  repRequests: { en: "customer requests drafted", ar: "طلبات عملاء جاهزة" },
  repNotReady: { en: "invoices not ready", ar: "فواتير غير جاهزة" },
  generated: { en: "Generated", ar: "أُنشئ في" },
  // business profile
  navProfile: { en: "Business profile", ar: "ملف المنشأة" },
  profTitle: { en: "Your business, once", ar: "بيانات منشأتك مرة واحدة" },
  profBody: { en: "Qaid fills these into every invoice your business issues, so you never answer them again. Only empty fields are filled.",
              ar: "يُدخل قيد هذه البيانات في كل فاتورة تصدرها منشأتك، فلا تُسأل عنها مجدداً. تُعبّأ الحقول الفارغة فقط." },
  profName: { en: "Registered business name", ar: "الاسم التجاري المسجّل" },
  profTrn: { en: "Tax Registration Number (TRN)", ar: "رقم التسجيل الضريبي" },
  profTrnHint: { en: "15 digits, starts with 1, ends with 03", ar: "15 رقماً يبدأ بـ 1 وينتهي بـ 03" },
  profLicence: { en: "Trade licence number", ar: "رقم الرخصة التجارية" },
  profAuthority: { en: "Licensing authority", ar: "جهة الترخيص" },
  profAddress: { en: "Address", ar: "العنوان" },
  profEmirate: { en: "Emirate", ar: "الإمارة" },
  profPayment: { en: "Usual payment method", ar: "طريقة الدفع المعتادة" },
  profTerms: { en: "Payment terms (days)", ar: "مدة السداد (بالأيام)" },
  profTermsHint: { en: "Used to fill missing due dates", ar: "تُستخدم لتعبئة تواريخ الاستحقاق الناقصة" },
  profSave: { en: "Save and apply", ar: "حفظ وتطبيق" },
  profSaved: { en: "Profile saved · applied to {n} invoice(s)", ar: "تم الحفظ · طُبّق على {n} فاتورة" },
  profPrompt: { en: "Set up your business once and Qaid stops asking for your own TRN, licence and address.",
                ar: "أدخل بيانات منشأتك مرة واحدة ولن يسألك قيد مجدداً عن رقمك الضريبي ورخصتك وعنوانك." },
  profPromptCta: { en: "Set up profile", ar: "إعداد الملف" },
  imported: { en: "Imported {n} invoice(s) from {file} · {c} columns understood", ar: "تم استيراد {n} فاتورة من {file} · فُهم {c} عموداً" },
  src_spreadsheet: { en: "Excel / CSV register", ar: "سجل Excel / CSV" },
} as const;

export type Key = keyof typeof STRINGS;

// Arabic versions of the agent's questions, keyed by issue code (English comes from the API).
const QUESTIONS_AR: Record<string, string> = {
  MISSING_INVOICE_NUMBER: "ما رقم الفاتورة؟",
  MISSING_ISSUE_DATE: "ما تاريخ إصدار الفاتورة؟",
  BAD_ISSUE_DATE: "ما تاريخ الإصدار الصحيح؟",
  MISSING_SELLER_NAME: "ما الاسم القانوني للبائع؟",
  MISSING_BUYER_NAME: "ما الاسم القانوني للمشتري؟",
  MISSING_SELLER_TRN: "ما الرقم الضريبي للبائع (15 رقماً)؟",
  MISSING_BUYER_TRN: "ما الرقم الضريبي للمشتري (15 رقماً)؟",
  BAD_SELLER_TRN: "يرجى التحقق من الرقم الضريبي للبائع: 15 رقماً يبدأ بـ 1 وينتهي بـ 03.",
  BAD_BUYER_TRN: "يرجى التحقق من الرقم الضريبي للمشتري: 15 رقماً يبدأ بـ 1 وينتهي بـ 03.",
  MISSING_SELLER_ADDRESS: "ما عنوان البائع؟",
  MISSING_BUYER_ADDRESS: "ما عنوان المشتري؟",
  MISSING_SELLER_EMIRATE: "في أي إمارة يقع البائع؟",
  MISSING_BUYER_EMIRATE: "في أي إمارة يقع المشتري؟",
  MISSING_DUE_DATE: "ما تاريخ استحقاق الدفع لهذه الفاتورة؟",
  MISSING_PAYMENT_MEANS: "كيف سيدفع المشتري هذه الفاتورة؟",
  MISSING_SELLER_LICENSE: "ما رقم الرخصة التجارية للبائع؟",
  MISSING_SELLER_LICENSE_AUTHORITY: "ما الجهة التي أصدرت الرخصة التجارية للبائع؟",
  MISSING_CREDIT_REASON: "ما سبب إصدار إشعار الدائن هذا؟",
  MISSING_PRECEDING_INVOICE: "ما رقم الفاتورة التي يصححها إشعار الدائن؟",
};
const CONFIRM_AR: Record<string, string> = {
  invoice_number: "رقم الفاتورة", issue_date: "تاريخ الإصدار", due_date: "تاريخ الاستحقاق",
  gross_total: "الإجمالي", "seller.name": "اسم البائع", "buyer.name": "اسم المشتري",
  "seller.trn": "الرقم الضريبي للبائع", "buyer.trn": "الرقم الضريبي للمشتري",
  "seller.legal_id": "رقم الرخصة التجارية للبائع (من سجل عجمان الرسمي)",
};

const HINTS_AR: Record<string, string> = {
  "seller.trn": "15 رقماً، يبدأ بـ 1 وينتهي بـ 03. المسافات والشرطات مقبولة.",
  "buyer.trn": "15 رقماً، يبدأ بـ 1 وينتهي بـ 03. المسافات والشرطات مقبولة.",
  due_date: "اليوم أولاً. مطلوب عندما يكون هناك مبلغ مستحق.",
  issue_date: "اليوم أولاً، كما هو مطبوع على الفاتورة.",
  payment_means: "مطلوب في الفواتير الإلكترونية في الإمارات.",
  "seller.legal_id": "كما هو مطبوع على الرخصة التجارية.",
  "seller.legal_authority": "الجهة التي أصدرت الرخصة (البر الرئيسي أو المنطقة الحرة).",
  credit_reason: "أسباب إشعار الدائن المعتمدة في الإمارات.",
  preceding_invoice: "الفاتورة التي يصححها إشعار الدائن هذا.",
};

const MESSAGES_AR: Record<string, string> = {
  BAD_VAT_RATE: "نسبة الضريبة في أحد البنود غير صحيحة؛ النسبة القياسية في الإمارات 5%.",
  LINE_MATH_MISMATCH: "مبلغ أحد البنود لا يساوي الكمية × السعر.",
  VAT_TOTAL_MISMATCH: "إجمالي الضريبة لا يطابق مجموع البنود.",
  NET_TOTAL_MISMATCH: "الإجمالي قبل الضريبة لا يطابق مجموع البنود.",
  GROSS_TOTAL_MISMATCH: "الإجمالي لا يطابق مجموع البنود مع الضريبة.",
  NO_LINES: "لا توجد بنود في الفاتورة.",
  NON_AED_CURRENCY: "الفاتورة بعملة غير الدرهم؛ يجب أيضاً بيان مبالغ الضريبة بالدرهم.",
  LICENCE_NOT_IN_REGISTER: "لم يُعثر على رقم الرخصة في سجل دائرة التنمية الاقتصادية بعجمان (بيانات مفتوحة).",
  LICENCE_NAME_MISMATCH: "رقم الرخصة مسجّل في سجل عجمان باسم تجاري مختلف.",
  WRONG_SPECIFICATION: "المستند لا يتبع مواصفة PINT AE الإماراتية.",
  BAD_CURRENCY: "رمز العملة غير صحيح وفق معيار ISO 4217.",
  BAD_UNIT_CODE: "وحدة القياس في أحد البنود غير معتمدة.",
};

export function messageText(issue: Issue, lang: Lang): string {
  return lang === "ar" ? MESSAGES_AR[issue.code] ?? issue.message : issue.message;
}

export function hintText(field: string, en: string | undefined, lang: Lang): string | undefined {
  return lang === "ar" ? HINTS_AR[field] ?? en : en;
}

export function questionText(issue: Issue, lang: Lang): string {
  if (lang === "en") return issue.question;
  if (issue.code.startsWith("UNCONFIRMED")) {
    const value = issue.question.split(": is it ")[1]?.replace(/\?$/, "") ?? "";
    const label = CONFIRM_AR[issue.field] ?? issue.field;
    return `تأكيد ${label}: هل هو ${value}؟`;
  }
  return QUESTIONS_AR[issue.code] ?? issue.question;
}

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (k: Key, vars?: Record<string, string | number>) => string };
const I18n = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (k) => STRINGS[k].en });
export const useI18n = () => useContext(I18n);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("qaid-lang") as Lang) ?? "en");
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    localStorage.setItem("qaid-lang", lang);
  }, [lang]);
  const t = (k: Key, vars?: Record<string, string | number>) => {
    let s: string = STRINGS[k][lang];
    for (const [name, v] of Object.entries(vars ?? {})) s = s.replace(`{${name}}`, String(v));
    return s;
  };
  return <I18n.Provider value={{ lang, setLang, t }}>{children}</I18n.Provider>;
}
