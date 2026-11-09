import { UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useI18n } from "../lib/i18n";

const ACCEPT = ".xlsx,.xlsm,.csv,.pdf,.jpg,.jpeg,.png,.tif,.tiff,.webp,.bmp,.json,.xml";

export function Dropzone({ onFiles, busy }: { onFiles: (files: File[]) => void; busy: boolean }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [active, setActive] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setActive(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      className="drop" data-active={active} role="button" tabIndex={0} aria-busy={busy}
      aria-label="Upload invoices: drop files here or press Enter to browse"
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && (e.preventDefault(), input.current?.click())}
      onDragOver={(e) => { e.preventDefault(); setActive(true); }}
      onDragLeave={() => setActive(false)}
      onDrop={onDrop}
    >
      <div className="drop-icon">{busy ? <span className="spinner" /> : <UploadCloud size={24} aria-hidden />}</div>
      <strong>{busy ? t("dropBusy") : t("dropTitle")}</strong>
      <small>{t("dropHint")}</small>
      <input ref={input} type="file" multiple accept={ACCEPT} hidden
        onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) onFiles(f); e.target.value = ""; }} />
    </div>
  );
}
