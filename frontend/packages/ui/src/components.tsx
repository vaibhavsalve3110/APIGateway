import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "./api";
import { formatRemaining, secondsUntil } from "./format";

type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "solid";

export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

const STATUS_TONES: Record<string, Tone> = {
  ACTIVE: "ok",
  EXPIRING: "warn",
  DISABLED: "warn",
  DRAFT: "neutral",
  EXPIRED: "neutral",
  REVOKED: "bad",
};

export function StatusChip({ status }: { status: string }) {
  return <Chip tone={STATUS_TONES[status] ?? "neutral"}>{status.charAt(0) + status.slice(1).toLowerCase()}</Chip>;
}

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={`switch${on ? " on" : ""}`}
      onClick={() => onChange(!on)}
    />
  );
}

export function Modal({ title, children, footer, onClose, width }: {
  title: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card modal" role="dialog" aria-modal="true" style={width ? { width } : undefined}>
        <div style={{ padding: "18px 21px 0" }}>
          <h2>{title}</h2>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-foot">{footer}</div>
      </div>
    </div>
  );
}

export function Field({ label, error, children, className }: { label: string; error?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`field${className ? " " + className : ""}`}>
      <span className="label">{label}</span>
      {children}
      {error ? <span className="field-error">{error}</span> : null}
    </label>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }
  const message = error instanceof ApiError || error instanceof Error ? error.message : String(error);
  return <div className="banner banner-bad" role="alert">{message}</div>;
}

/** Re-renders every second; used for overlap-window countdowns. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function Countdown({ until }: { until: string | null }) {
  const now = useNow();
  return <span className="mono">{formatRemaining(secondsUntil(until, now))}</span>;
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => setCopied(true));
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="grow">
        <h1>{title}</h1>
        {subtitle ? <p className="page-sub">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  );
}

export function ComingSoon({ title, brdRefs, description }: { title: string; brdRefs: string; description: string }) {
  return (
    <div className="page">
      <PageHeader title={title} subtitle={`Planned — ${brdRefs}`} />
      <div className="card empty">
        <p style={{ maxWidth: 520, margin: "0 auto", lineHeight: 1.6 }}>{description}</p>
      </div>
    </div>
  );
}

/** The gateway mark used in both portals' headers. */
export function LogoMark({ size = 27 }: { size?: number }) {
  return (
    <div
      style={{
        width: size, height: size, borderRadius: 6, background: "var(--accent)", display: "flex",
        alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}
    >
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round">
        <path d="M3 7h6M15 7h6M3 17h6M15 17h6" />
        <circle cx="12" cy="7" r="2.6" />
        <circle cx="12" cy="17" r="2.6" />
      </svg>
    </div>
  );
}
