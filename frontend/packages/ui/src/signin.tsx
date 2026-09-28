import { useCallback, useEffect, useRef, useState } from "react";

import type { Session, SignInProps } from "./auth";
import { ApiError } from "./api";
import { LogoMark, useNow } from "./components";

interface Captcha {
  challengeId: string;
  image: string;
  expiresInSeconds: number;
}

interface CodeRequested {
  expiresInSeconds: number;
  resendInSeconds: number;
  /** Only when no mail server is configured: lets the demo run end to end. */
  devCode: string | null;
}

/**
 * Sign-in shared by both portals (design: AdminLogin / DevLogin artboards): e-mail plus a CAPTCHA, then the
 * one-time code sent to that address. The same screen serves staff and partner users; the backend decides
 * which roles a given address has.
 */
export function SignInScreen({ product, headline, points, dark = false, api, error, onSignedIn }: SignInProps & {
  product: string;
  headline: string;
  points: string[];
  dark?: boolean;
}) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [captcha, setCaptcha] = useState<Captcha | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);
  const now = useNow(1000);

  const newCaptcha = useCallback(() => {
    setCaptchaAnswer("");
    api.post<Captcha>("/api/auth/captcha")
      .then(setCaptcha)
      .catch((e: unknown) => setProblem(e instanceof Error ? e.message : String(e)));
  }, [api]);

  useEffect(() => {
    if (step === "email" && !captcha) {
      newCaptcha();
    }
  }, [step, captcha, newCaptcha]);

  const secondsLeft = resendAt ? Math.max(0, Math.ceil((resendAt - now) / 1000)) : 0;

  const requestCode = () => {
    setBusy(true);
    setProblem(null);
    api.post<CodeRequested>("/api/auth/otp/request", {
      email: email.trim(), captchaId: captcha?.challengeId ?? "", captchaAnswer,
    })
      .then((result) => {
        setDevCode(result.devCode);
        setResendAt(Date.now() + result.resendInSeconds * 1000);
        setStep("code");
        setTimeout(() => codeInput.current?.focus(), 50);
      })
      .catch((e: unknown) => {
        setProblem(e instanceof ApiError ? e.message : String(e));
        newCaptcha(); // a challenge is single-use, right or wrong
      })
      .finally(() => setBusy(false));
  };

  const verify = () => {
    setBusy(true);
    setProblem(null);
    api.post<Session>("/api/auth/otp/verify", { email: email.trim(), code: code.trim() })
      .then(onSignedIn)
      .catch((e: unknown) => setProblem(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const startOver = () => {
    setStep("email");
    setCode("");
    setDevCode(null);
    setProblem(null);
    newCaptcha();
  };

  return (
    <div style={{ display: "flex", minHeight: "100%" }}>
      <div
        className="signin-brand"
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
              {step === "email"
                ? "Enter your work e-mail address and the characters in the image. We will send you a one-time code."
                : `We have sent a code to ${email.trim()}. It is valid for a few minutes and can be used once.`}
            </p>
          </div>

          {error ? <div className="banner banner-bad">{error}</div> : null}
          {problem ? <div className="banner banner-bad">{problem}</div> : null}

          {step === "email" ? (
            <form className="stack" style={{ gap: 14 }} onSubmit={(e) => { e.preventDefault(); requestCode(); }}>
              <label className="field">
                <span className="label">Work e-mail</span>
                <input className="input" type="email" autoComplete="username" autoFocus placeholder="you@example.in"
                  value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="field">
                <span className="label">Characters in the image</span>
                <div className="row" style={{ gap: 10 }}>
                  {captcha ? (
                    <img src={captcha.image} alt="CAPTCHA" width={190} height={60}
                      style={{ borderRadius: 6, border: "1px solid var(--border)" }} />
                  ) : <div className="card" style={{ width: 190, height: 60 }} />}
                  <button type="button" className="btn btn-sm" onClick={newCaptcha} title="Show a different image">↻ New image</button>
                </div>
                <input className="input mono" style={{ textTransform: "uppercase", letterSpacing: "0.18em" }}
                  autoComplete="off" spellCheck={false} maxLength={8}
                  value={captchaAnswer} onChange={(e) => setCaptchaAnswer(e.target.value)} />
              </label>
              <button className="btn btn-primary" style={{ height: 40 }} type="submit"
                disabled={busy || !email.trim() || !captchaAnswer.trim() || !captcha}>
                {busy ? "Sending…" : "Send one-time code"}
              </button>
            </form>
          ) : (
            <form className="stack" style={{ gap: 14 }} onSubmit={(e) => { e.preventDefault(); verify(); }}>
              {devCode ? (
                <div className="banner banner-warn" style={{ fontSize: 12.5 }}>
                  No mail server is configured, so the code is shown here for this environment only:{" "}
                  <strong className="mono">{devCode}</strong>
                </div>
              ) : null}
              <label className="field">
                <span className="label">One-time code</span>
                <input ref={codeInput} className="input mono" inputMode="numeric" autoComplete="one-time-code"
                  style={{ fontSize: 20, letterSpacing: "0.4em", height: 46 }} maxLength={8} placeholder="000000"
                  value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              </label>
              <button className="btn btn-primary" style={{ height: 40 }} type="submit" disabled={busy || code.trim().length < 4}>
                {busy ? "Checking…" : "Sign in"}
              </button>
              <div className="row" style={{ gap: 12 }}>
                <button type="button" className="btn btn-sm" disabled={secondsLeft > 0 || busy} onClick={startOver}>
                  {secondsLeft > 0 ? `Resend in ${secondsLeft}s` : "Send another code"}
                </button>
                <button type="button" className="btn btn-sm" onClick={startOver}>Use a different address</button>
              </div>
            </form>
          )}

          <p className="muted" style={{ fontSize: 11.5, lineHeight: 1.6 }}>
            Accounts are created by your administrator. If your address is not recognised you will not receive a code.
          </p>
        </div>
      </div>
    </div>
  );
}
