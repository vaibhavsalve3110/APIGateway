import { useState, type ReactNode } from "react";

import { Chip } from "./components";
import { prettyJson, statusTone } from "./docs";
import type { ApiDocumentation, ApiField } from "./types";

export function CodeBlock({ code, maxHeight = 360 }: { code: string; maxHeight?: number }) {
  return (
    <pre className="code-block" style={{ maxHeight }}>
      {code}
    </pre>
  );
}

export function FieldsTable({ fields, emptyText }: { fields: ApiField[]; emptyText?: string }) {
  if (fields.length === 0) {
    return emptyText ? <p className="muted" style={{ fontSize: 12.5 }}>{emptyText}</p> : null;
  }
  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr><th style={{ width: "28%" }}>Name</th><th style={{ width: "14%" }}>Type</th><th style={{ width: "11%" }}>Required</th><th style={{ width: "20%" }}>Example</th><th>Description</th></tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.name}>
              <td className="mono" style={{ fontSize: 12, fontWeight: 500, paddingLeft: 14 + Math.min(4, f.name.split(".").length - 1) * 14 }}>
                {f.name}
              </td>
              <td className="mono muted" style={{ fontSize: 11.5 }}>{f.type}</td>
              <td>{f.required ? <Chip tone="bad">Required</Chip> : <Chip>Optional</Chip>}</td>
              <td className="mono muted" style={{ fontSize: 11.5, wordBreak: "break-all" }}>{f.example ?? ""}</td>
              <td className="muted" style={{ fontSize: 12.5 }}>{f.description ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="stack" style={{ gap: 8 }}>
      <div>
        <h2 style={{ fontSize: 15 }}>{title}</h2>
        {sub ? <p className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>{sub}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Read-only documentation: what partners see, and the Management Portal's preview of it. */
export function DocumentationView({ docs, method, keyHeader }: { docs: ApiDocumentation; method: string; keyHeader?: string }) {
  const sorted = [...docs.responses].sort((a, b) => a.statusCode - b.statusCode);
  const [selected, setSelected] = useState<number | null>(sorted[0]?.statusCode ?? null);
  const response = sorted.find((r) => r.statusCode === selected) ?? sorted[0];
  const hasBody = docs.requestBodyFields.length > 0 || !!docs.requestBodyExample;

  return (
    <div className="stack" style={{ gap: 24 }}>
      {docs.queryParameters.length > 0 ? (
        <Section title="Query parameters"><FieldsTable fields={docs.queryParameters} /></Section>
      ) : null}

      <Section title="Request headers" sub={keyHeader ? `Every call also needs your security key in ${keyHeader}.` : undefined}>
        <FieldsTable fields={docs.requestHeaders} emptyText="No additional headers." />
      </Section>

      {hasBody || method !== "GET" ? (
        <Section title="Request body" sub={hasBody ? "JSON." : undefined}>
          {hasBody ? (
            <>
              <FieldsTable fields={docs.requestBodyFields} />
              {docs.requestBodyExample ? <CodeBlock code={prettyJson(docs.requestBodyExample)} /> : null}
            </>
          ) : <p className="muted" style={{ fontSize: 12.5 }}>No request body.</p>}
        </Section>
      ) : null}

      <Section title="Responses" sub="Select a status code to see its body.">
        {sorted.length === 0 ? <p className="muted" style={{ fontSize: 12.5 }}>No responses documented yet.</p> : (
          <>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              {sorted.map((r) => (
                <button key={r.statusCode} type="button" onClick={() => setSelected(r.statusCode)}
                  className={`status-tab${response?.statusCode === r.statusCode ? " on" : ""}`}>
                  <Chip tone={statusTone(r.statusCode)}><span className="mono">{r.statusCode}</span></Chip>
                  <span style={{ fontSize: 12 }}>{r.description ?? ""}</span>
                </button>
              ))}
            </div>
            {response ? (
              <div className="stack" style={{ gap: 10 }}>
                {response.bodyFields.length > 0 ? <FieldsTable fields={response.bodyFields} /> : null}
                {response.bodyExample ? <CodeBlock code={prettyJson(response.bodyExample)} />
                  : <p className="muted" style={{ fontSize: 12.5 }}>No body.</p>}
              </div>
            ) : null}
          </>
        )}
      </Section>

      {docs.responseHeaders.length > 0 ? (
        <Section title="Response headers"><FieldsTable fields={docs.responseHeaders} /></Section>
      ) : null}
    </div>
  );
}
