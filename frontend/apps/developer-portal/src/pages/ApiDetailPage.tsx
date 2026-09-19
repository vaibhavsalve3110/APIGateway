import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import {
  Chip, CodeBlock, CopyButton, DocumentationView, ErrorBanner, fillPath, isValidJson, pathParams, prettyJson, statusTone, useAuth,
  type PartnerApiDetail, type TryItRequest, type TryItResponse,
} from "@apigw/ui";

import { usePartner } from "../usePartner";

type Pair = { name: string; value: string };

function toRecord(pairs: Pair[]): Record<string, string> {
  return Object.fromEntries(pairs.filter((p) => p.name.trim() && p.value !== "").map((p) => [p.name.trim(), p.value]));
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function curlFor(api: PartnerApiDetail, path: Record<string, string>, query: Pair[], headers: Pair[], body: string | null): string {
  const qs = new URLSearchParams(toRecord(query)).toString();
  const url = api.sandboxBaseUrl.replace(/\/+$/, "") + fillPath(api.proxyPath, path) + (qs ? `?${qs}` : "");
  const lines = [`curl -X ${api.httpMethod} ${shellQuote(url)}`, `  -H ${shellQuote(`${api.keyHeader}: <your sandbox key>`)}`];
  for (const [k, v] of Object.entries(toRecord(headers))) lines.push(`  -H ${shellQuote(`${k}: ${v}`)}`);
  if (body && body.trim()) {
    lines.push(`  -H 'Content-Type: application/json'`);
    lines.push(`  -d ${shellQuote(body.trim())}`);
  }
  return lines.join(" \\\n");
}

/** One API's contract and the Sandbox console (BRD DP-02, DP-03). */
export function ApiDetailPage() {
  const { id } = useParams();
  const { api } = useAuth();
  const me = usePartner();
  const detail = useQuery({ queryKey: ["catalogue", id], queryFn: () => api.get<PartnerApiDetail>(`/api/partner/apis/${id}`) });

  if (detail.isLoading) return <div className="page"><div className="empty">Loading…</div></div>;
  if (detail.error || !detail.data) {
    return (
      <div className="page" style={{ padding: "28px 30px" }}>
        <Link to="/apis">← Back to catalogue</Link>
        <ErrorBanner error={detail.error ?? new Error("This API is not available to your account.")} />
      </div>
    );
  }
  const a = detail.data;

  return (
    <div className="page" style={{ padding: "24px 30px 34px" }}>
      <div className="muted" style={{ fontSize: 12.5 }}><Link to="/apis">Your API catalogue</Link> / {a.category}</div>
      <div className="page-head">
        <div className="grow">
          <h1 style={{ fontSize: 24 }}>{a.name}</h1>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <Chip tone={a.httpMethod === "GET" ? "info" : "ok"}><span className="mono">{a.httpMethod}</span></Chip>
            <span className="mono" style={{ fontSize: 13 }}>{a.proxyPath}</span>
            <CopyButton value={a.proxyPath} label="Copy path" />
          </div>
          {a.description ? <p className="page-sub" style={{ fontSize: 13.5, maxWidth: 760, lineHeight: 1.6 }}>{a.description}</p> : null}
        </div>
      </div>

      <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "stretch" }}>
        <Fact label="Sandbox base URL" value={a.sandboxBaseUrl} mono />
        <Fact label="Authentication" value={`${a.keyHeader} header`} mono />
        <Fact label="Rate limit (per Client ID)" value={`${a.rateLimitCount.toLocaleString("en-IN")} / ${a.rateLimitWindow.toLowerCase()}`} />
        <Fact label="Environments" value={a.productionAvailable ? "Sandbox · Production" : "Sandbox only"} />
        {me.data ? <Fact label="Your Sandbox Client ID" value={me.data.clientIdSandbox} mono /> : null}
      </div>

      <div className="two-col">
        <div className="card" style={{ padding: "20px 22px" }}>
          <DocumentationView docs={a.documentation} method={a.httpMethod} keyHeader={a.keyHeader} />
        </div>
        <div className="sticky"><TryItPanel api={a} /></div>
      </div>
    </div>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="card" style={{ padding: "10px 14px", minWidth: 170 }}>
      <div className="label">{label}</div>
      <div className={mono ? "mono" : undefined} style={{ fontSize: mono ? 12 : 13, fontWeight: 600, marginTop: 3, wordBreak: "break-all" }}>{value}</div>
    </div>
  );
}

function TryItPanel({ api: target }: { api: PartnerApiDetail }) {
  const { api } = useAuth();
  const doc = target.documentation;
  const params = useMemo(() => pathParams(target.proxyPath), [target.proxyPath]);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [path, setPath] = useState<Record<string, string>>({});
  const [query, setQuery] = useState<Pair[]>(() => doc.queryParameters.map((q) => ({ name: q.name, value: q.example ?? "" })));
  const [headers, setHeaders] = useState<Pair[]>(() =>
    doc.requestHeaders.filter((h) => h.name.toLowerCase() !== target.keyHeader.toLowerCase()).map((h) => ({ name: h.name, value: h.example ?? "" })));
  const hasBody = target.httpMethod !== "GET" && target.httpMethod !== "DELETE";
  const [body, setBody] = useState(() => prettyJson(doc.requestBodyExample));
  const [view, setView] = useState<"body" | "headers">("body");

  const send = useMutation({
    mutationFn: () => api.post<TryItResponse>(`/api/partner/apis/${target.id}/try`, {
      apiKey: key.trim(),
      pathParams: path,
      query: toRecord(query),
      headers: toRecord(headers),
      body: hasBody && body.trim() ? body : null,
    } satisfies TryItRequest),
  });

  const missingPath = params.filter((p) => !path[p]?.trim());
  const bodyValid = !hasBody || isValidJson(body);
  const canSend = key.trim().length > 0 && missingPath.length === 0 && bodyValid && !send.isPending;
  const res = send.data;

  return (
    <div className="card">
      <div className="card-head" style={{ padding: "13px 16px", borderBottom: "1px solid var(--border-row)" }}>
        <div className="row" style={{ gap: 8 }}>
          <div className="grow">
            <div className="card-title">Try it live</div>
            <div className="card-sub">Sends a real request to the Sandbox (UAT) with your key. Production is never callable from the portal.</div>
          </div>
          <Chip tone="info">SANDBOX</Chip>
        </div>
      </div>
      <div className="stack" style={{ gap: 14, padding: "14px 16px 16px" }}>
        {target.tryItSimulated ? (
          <div className="banner banner-warn" style={{ fontSize: 12 }}>
            Demo mode: no Sandbox gateway is connected, so responses are simulated from the documented examples. Your key is still checked.
          </div>
        ) : null}

        <label className="field">
          <span className="label">{target.keyHeader} — your Sandbox key</span>
          <div className="row" style={{ gap: 6 }}>
            <input className="input mono grow" type={showKey ? "text" : "password"} autoComplete="off" spellCheck={false}
              placeholder="agw_sbx_…" value={key} onChange={(e) => setKey(e.target.value)} />
            <button type="button" className="btn btn-sm" onClick={() => setShowKey((s) => !s)}>{showKey ? "Hide" : "Show"}</button>
          </div>
          <span className="muted" style={{ fontSize: 11.5 }}>
            Keys are shown only once, when generated. Lost it? <Link to="/keys">Generate a new Sandbox key</Link> — the old one keeps working for 20 minutes.
          </span>
        </label>

        {params.length > 0 ? (
          <PairBlock title="Path parameters">
            {params.map((p) => (
              <div key={p} className="row" style={{ gap: 6 }}>
                <span className="mono" style={{ width: 130, fontSize: 12, flexShrink: 0 }}>{p}<span style={{ color: "var(--bad)" }}> *</span></span>
                <input className="input cell-input mono grow" aria-label={p} value={path[p] ?? ""} onChange={(e) => setPath((s) => ({ ...s, [p]: e.target.value }))} />
              </div>
            ))}
          </PairBlock>
        ) : null}

        <PairsEditor title="Query parameters" pairs={query} onChange={setQuery}
          required={new Set(doc.queryParameters.filter((q) => q.required).map((q) => q.name))} />
        <PairsEditor title="Headers" pairs={headers} onChange={setHeaders}
          required={new Set(doc.requestHeaders.filter((h) => h.required).map((h) => h.name))} />

        {hasBody ? (
          <label className="field">
            <div className="row" style={{ gap: 8 }}>
              <span className="label grow">Body (JSON)</span>
              {!bodyValid ? <Chip tone="bad">Invalid JSON</Chip> : null}
              <button type="button" className="btn btn-sm" disabled={!bodyValid || !body.trim()} onClick={() => setBody(prettyJson(body))}>Format</button>
              {doc.requestBodyExample ? <button type="button" className="btn btn-sm" onClick={() => setBody(prettyJson(doc.requestBodyExample))}>Reset</button> : null}
            </div>
            <textarea className="textarea mono" rows={Math.min(14, Math.max(5, body.split("\n").length + 1))} spellCheck={false}
              style={{ fontSize: 12 }} value={body} onChange={(e) => setBody(e.target.value)} />
          </label>
        ) : null}

        <div className="row" style={{ gap: 8 }}>
          <button className="btn btn-primary" disabled={!canSend} onClick={() => send.mutate()}>{send.isPending ? "Sending…" : "Send request"}</button>
          {missingPath.length > 0 ? <span className="muted" style={{ fontSize: 11.5 }}>Fill {missingPath.join(", ")}</span>
            : !key.trim() ? <span className="muted" style={{ fontSize: 11.5 }}>Enter your Sandbox key</span> : null}
        </div>

        <ErrorBanner error={send.error} />

        {res ? (
          <div className="stack" style={{ gap: 8 }}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <Chip tone={statusTone(res.status)}><span className="mono">{res.status}</span></Chip>
              <span className="mono muted" style={{ fontSize: 11.5 }}>{res.latencyMs} ms</span>
              {res.simulated ? <Chip tone="warn">Simulated</Chip> : <Chip tone="ok">Live Sandbox</Chip>}
            </div>
            <div className="mono muted" style={{ fontSize: 11, wordBreak: "break-all" }}>{target.httpMethod} {res.requestUrl}</div>
            {res.note ? <div className="muted" style={{ fontSize: 11.5 }}>{res.note}</div> : null}
            <div className="row" style={{ gap: 4 }}>
              <button type="button" className={`btn btn-sm${view === "body" ? " btn-primary" : ""}`} onClick={() => setView("body")}>Body</button>
              <button type="button" className={`btn btn-sm${view === "headers" ? " btn-primary" : ""}`} onClick={() => setView("headers")}>
                Headers {Object.keys(res.headers).length}
              </button>
              <span className="grow" />
              {view === "body" && res.body ? <CopyButton value={res.body} label="Copy" /> : null}
            </div>
            {view === "body"
              ? <CodeBlock code={res.body ? prettyJson(res.body) : "(empty body)"} maxHeight={320} />
              : <CodeBlock code={Object.entries(res.headers).map(([k, v]) => `${k}: ${v}`).join("\n") || "(no headers)"} maxHeight={320} />}
          </div>
        ) : null}

        <details>
          <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>cURL for this request</summary>
          <div style={{ marginTop: 8 }}>
            <CodeBlock code={curlFor(target, path, query, headers, hasBody ? body : null)} maxHeight={220} />
          </div>
        </details>
      </div>
    </div>
  );
}

function PairBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="label">{title}</span>
      {children}
    </div>
  );
}

function PairsEditor({ title, pairs, onChange, required }: { title: string; pairs: Pair[]; onChange: (next: Pair[]) => void; required: Set<string> }) {
  const update = (i: number, patch: Partial<Pair>) => onChange(pairs.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <PairBlock title={title}>
      {pairs.map((p, i) => (
        <div key={i} className="row" style={{ gap: 6 }}>
          <input className="input cell-input mono" style={{ width: 130, flexShrink: 0 }} aria-label={`${title} name`} value={p.name}
            onChange={(e) => update(i, { name: e.target.value })} />
          <input className="input cell-input mono grow" aria-label={`${p.name || title} value`} value={p.value}
            placeholder={required.has(p.name) ? "required" : ""} onChange={(e) => update(i, { value: e.target.value })} />
          <button type="button" className="btn btn-sm" aria-label="Remove" onClick={() => onChange(pairs.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div><button type="button" className="btn btn-sm" onClick={() => onChange([...pairs, { name: "", value: "" }])}>+ Add</button></div>
    </PairBlock>
  );
}
