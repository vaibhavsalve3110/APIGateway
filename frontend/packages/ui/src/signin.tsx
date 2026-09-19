import type { ReactNode } from "react";

import type { SignInProps } from "./auth";
import { LogoMark } from "./components";

/** Sign-in screen shared by both portals (design: AdminLogin / DevLogin artboards). */
export function SignInScreen({ product, headline, points, dark = false, ...props }: SignInProps & {
  product: string;
  headline: string;
  points: string[];
  dark?: boolean;
}) {
  return (
    <div style={{ display: "flex", minHeight: "100%" }}>
      <div
        style={{
          width: 520, flexShrink: 0, padding: "48px 48px 40px", display: "flex", flexDirection: "column",
          background: dark ? "var(--rail)" : "var(--surface)", color: dark ? "#e3e8ef" : "var(--text)",
          borderRight: dark ? undefined : "1px solid var(--border)",
        }}
      >
        <div className="row">
          <LogoMark size={34} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>API Gateway</div>
            <div style={{ fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--text-4)" }}>{product}</div>
          </div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 400 }}>
          <h1 style={{ fontSize: 30, lineHeight: 1.25, color: dark ? "#f2f5f9" : undefined }}>{headline}</h1>
          <ul style={{ margin: "24px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 12 }}>
            {points.map((p) => (
              <li key={p} className="row" style={{ alignItems: "flex-start", color: dark ? "var(--rail-text)" : "var(--text-2)" }}>
                <span style={{ color: "#5b7bb5", fontWeight: 700 }}>✓</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-4)" }}>Access is monitored and logged.</div>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
        <div style={{ width: "100%", maxWidth: 420 }} className="stack">
          <div>
            <h1>Sign in</h1>
            <p className="page-sub">
              {props.mode === "oidc"
                ? "You will be sent to the organisation's sign-in page (Keycloak), with multi-factor authentication."
                : "Developer mode — choose who to sign in as. The backend accepts this only with its dev profile on."}
            </p>
          </div>
          {props.error ? <div className="banner banner-bad">{props.error}</div> : null}
          {props.mode === "oidc" ? (
            <button className="btn btn-primary" style={{ height: 40 }} onClick={props.onOidcSignIn}>Continue to sign-in</button>
          ) : (
            props.identities.map((identity) => (
              <IdentityButton key={identity.username} onClick={() => props.onDevSignIn(identity)}>
                <div style={{ fontWeight: 600 }}>{identity.label}</div>
                <div className="muted" style={{ fontSize: 12 }}>{identity.description}</div>
              </IdentityButton>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function IdentityButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button className="card" style={{ padding: "13px 15px", textAlign: "left" }} onClick={onClick}>
      {children}
    </button>
  );
}
