import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";

import {
  ApiError, Chip, COMMON_STATUS_CODES, DocumentationView, emptyDocumentation, ErrorBanner, Field, inferFields,
  isValidJson, mergeFields, Modal, prettyJson, StatusChip, statusTone, useAuth,
  type ApiDocumentation, type ApiRequest, type ApiResponseDoc, type ApiView, type ImportedOperation, type ImportResult,
} from "@apigw/ui";

import { FieldsEditor } from "./FieldsEditor";

type Section = "overview" | "request" | "responses" | "preview";

function blankRequest(): ApiRequest {
  return {
    name: "",
    category: "Payments",
    httpMethod: "GET",
    proxyPath: "/v1/",
    backendUrlSandbox: "http://mock-sandbox:8080/",
    backendUrlProduction: "",
    rateLimitCount: 300,
    rateLimitWindow: "MINUTE",
    ownerTeam: "",
    description: "",
    documentation: {
      ...emptyDocumentation(),
      requestHeaders: [{ name: "X-Request-Id", type: "string", required: false, example: "7f3c2a90-1d4e-4b8a-9c11-2f6f0a1b3c4d", description: "Idempotency / tracing id" }],
      responses: [{ statusCode: 200, description: "Success", bodyExample: null, bodyFields: [] }],
    },
  };
}

function toRequest(a: ApiView): ApiRequest {
  return {
    name: a.name,
    category: a.category,
    httpMethod: a.httpMethod,
    proxyPath: a.proxyPath,
    backendUrlSandbox: a.backendUrlSandbox,
    backendUrlProduction: a.backendUrlProduction ?? "",
    rateLimitCount: a.rateLimitCount,
    rateLimitWindow: a.rateLimitWindow,
    ownerTeam: a.ownerTeam ?? "",
    description: a.description ?? "",
    documentation: a.documentation ?? emptyDocumentation(),
  };
}

/** Joins the spec's server URL and the operation's path — the usual backend target for an imported operation. */
function joinUrl(base: string | null, path: string): string | null {
  if (!base) return null;
  return base.replace(/\/+$/, "") + path;
}

/** Documentation problems the server would also reject, caught before sending. */
function clientProblems(doc: ApiDocumentation): string[] {
  const out: string[] = [];
  if (!isValidJson(doc.requestBodyExample)) out.push("The request body example is not valid JSON.");
  const codes = doc.responses.map((r) => r.statusCode);
  if (new Set(codes).size !== codes.length) out.push("Each HTTP status code can be documented only once.");
  doc.responses.forEach((r) => {
    if (!r.statusCode || r.statusCode < 100 || r.statusCode > 599) out.push(`Response status "${r.statusCode || ""}" must be between 100 and 599.`);
    if (!isValidJson(r.bodyExample)) out.push(`The ${r.statusCode} response body example is not valid JSON.`);
  });
  const named = [...doc.queryParameters, ...doc.requestHeaders, ...doc.requestBodyFields, ...doc.responseHeaders,
    ...doc.responses.flatMap((r) => r.bodyFields)];
  if (named.some((f) => !f.name.trim())) out.push("Every parameter, header and field row needs a name (remove empty rows).");
  return out;
}

/** Add / edit an API with its full contract (BRD CP-API-01, CP-API-06, CP-API-07). */
export function ApiEditorPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const { api, user } = useAuth();
  const canEdit = user.roles.includes("ADMIN");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [section, setSection] = useState<Section>("overview");
  const [form, setForm] = useState<ApiRequest>(blankRequest);
  const [importing, setImporting] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  const existing = useQuery({
    queryKey: ["api", id],
    queryFn: () => api.get<ApiView>(`/api/admin/apis/${id}`),
    enabled: !isNew,
  });
  useEffect(() => {
    if (existing.data) setForm(toRequest(existing.data));
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () => {
      // Optional text fields go out as null, not "" — the backend validates a present Production URL.
      const blankToNull = (v: string | null) => (v && v.trim() ? v.trim() : null);
      const body: ApiRequest = {
        ...form,
        backendUrlProduction: blankToNull(form.backendUrlProduction),
        ownerTeam: blankToNull(form.ownerTeam),
        description: blankToNull(form.description),
      };
      return isNew ? api.post<ApiView>("/api/admin/apis", body) : api.put<ApiView>(`/api/admin/apis/${id}`, body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["apis"] });
      queryClient.setQueryData(["api", saved.id], saved);
      setSavedNote(`Saved ${new Date().toLocaleTimeString("en-IN")}`);
      if (isNew) navigate(`/apis/${saved.id}`, { replace: true });
    },
  });

  const set = <K extends keyof ApiRequest>(key: K, value: ApiRequest[K]) => { setSavedNote(null); setForm((f) => ({ ...f, [key]: value })); };
  const setDoc = (patch: Partial<ApiDocumentation>) => set("documentation", { ...form.documentation, ...patch });
  const fieldError = (name: string) => (save.error instanceof ApiError ? save.error.fields[name] : undefined);
  const otherFieldErrors = save.error instanceof ApiError
    ? Object.entries(save.error.fields).filter(([k]) => k.startsWith("documentation")) : [];

  const onSave = () => {
    const found = clientProblems(form.documentation);
    setProblems(found);
    if (found.length === 0) save.mutate();
  };

  const applyOperation = (op: ImportedOperation, result: ImportResult) => {
    setForm((f) => ({
      ...f,
      name: op.name,
      category: op.category,
      httpMethod: op.httpMethod,
      proxyPath: op.proxyPath,
      description: op.description ?? f.description,
      backendUrlSandbox: isNew ? (joinUrl(result.suggestedBackendBaseUrl, op.proxyPath) ?? f.backendUrlSandbox) : f.backendUrlSandbox,
      documentation: op.documentation,
    }));
    setSavedNote(null);
    setImporting(false);
    setSection("request");
  };

  if (!isNew && existing.isLoading) return <div className="page"><div className="empty">Loading…</div></div>;
  if (!isNew && existing.error) return <div className="page"><ErrorBanner error={existing.error} /></div>;

  const doc = form.documentation;
  const sections: { key: Section; label: string; count?: number }[] = [
    { key: "overview", label: "Overview" },
    { key: "request", label: "Request", count: doc.queryParameters.length + doc.requestHeaders.length + doc.requestBodyFields.length },
    { key: "responses", label: "Responses", count: doc.responses.length },
    { key: "preview", label: "Partner preview" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <div className="muted" style={{ fontSize: 12 }}><Link to="/apis">APIs</Link> / {isNew ? "Add API" : form.name}</div>
          <div className="row" style={{ gap: 10, marginTop: 4 }}>
            <h1>{isNew ? "Add API" : form.name || "API"}</h1>
            {existing.data ? <StatusChip status={existing.data.status} /> : null}
            {doc.source !== "MANUAL" ? <Chip tone="info">Imported from {doc.source === "OPENAPI" ? "Swagger / OpenAPI" : "Postman"}</Chip> : null}
          </div>
          <p className="page-sub">Define the route, then document the request, headers and a response for each HTTP status code. Partners see this contract in the Developer Portal.</p>
        </div>
        {canEdit ? (
          <div className="row" style={{ gap: 8 }}>
            {savedNote ? <span className="muted" style={{ fontSize: 12 }}>{savedNote}</span> : null}
            <button className="btn" onClick={() => setImporting(true)}>Import Swagger / Postman</button>
            <button className="btn btn-primary" disabled={save.isPending} onClick={onSave}>
              {save.isPending ? "Saving…" : isNew ? "Add API" : "Save changes"}
            </button>
          </div>
        ) : <Chip>Read only — Admin role required to edit</Chip>}
      </div>

      {problems.length > 0 || otherFieldErrors.length > 0 ? (
        <div className="banner banner-bad">
          <strong>Fix these before saving:</strong>
          <ul style={{ margin: "6px 0 0 18px" }}>
            {problems.map((p) => <li key={p}>{p}</li>)}
            {otherFieldErrors.map(([k, v]) => <li key={k}><span className="mono">{k}</span>: {v}</li>)}
          </ul>
        </div>
      ) : null}
      {save.error && !(save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED") ? <ErrorBanner error={save.error} /> : null}
      {save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED" && otherFieldErrors.length === 0 && section !== "overview" ? (
        <div className="banner banner-bad">Some overview fields need attention. <button className="btn btn-sm" onClick={() => setSection("overview")}>Show</button></div>
      ) : null}

      <div className="card">
        <div className="tabs">
          {sections.map((s) => (
            <button key={s.key} className={`tab${section === s.key ? " tab-active" : ""}`} onClick={() => setSection(s.key)}>
              {s.label}{s.count ? ` ${s.count}` : ""}
            </button>
          ))}
        </div>
        <div style={{ padding: "18px 20px 22px" }}>
          {section === "overview" ? (
            <div className="form-grid" style={{ maxWidth: 820 }}>
              <Field label="API name" error={fieldError("name")} className="span-2">
                <input className="input" value={form.name} disabled={!canEdit} onChange={(e) => set("name", e.target.value)} />
              </Field>
              <Field label="Category" error={fieldError("category")}>
                <input className="input" value={form.category} disabled={!canEdit} onChange={(e) => set("category", e.target.value)} />
              </Field>
              <Field label="Method" error={fieldError("httpMethod")}>
                <select className="select" value={form.httpMethod} disabled={!canEdit} onChange={(e) => set("httpMethod", e.target.value)}>
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}
                </select>
              </Field>
              <Field label="Proxy path (partner-facing) — use {name} for path parameters" error={fieldError("proxyPath")} className="span-2">
                <input className="input mono" value={form.proxyPath} disabled={!canEdit} onChange={(e) => set("proxyPath", e.target.value)} />
              </Field>
              <Field label="Backend URL — Sandbox (UAT)" error={fieldError("backendUrlSandbox")} className="span-2">
                <input className="input mono" value={form.backendUrlSandbox} disabled={!canEdit} onChange={(e) => set("backendUrlSandbox", e.target.value)} />
              </Field>
              <Field label="Backend URL — Production (optional)" error={fieldError("backendUrlProduction")} className="span-2">
                <input className="input mono" value={form.backendUrlProduction ?? ""} disabled={!canEdit} onChange={(e) => set("backendUrlProduction", e.target.value)} />
              </Field>
              <Field label="Rate limit — requests" error={fieldError("rateLimitCount")}>
                <input className="input mono" type="number" min={1} value={form.rateLimitCount} disabled={!canEdit}
                  onChange={(e) => set("rateLimitCount", Number(e.target.value))} />
              </Field>
              <Field label="Per" error={fieldError("rateLimitWindow")}>
                <select className="select" value={form.rateLimitWindow} disabled={!canEdit}
                  onChange={(e) => set("rateLimitWindow", e.target.value as ApiRequest["rateLimitWindow"])}>
                  <option value="MINUTE">Minute</option><option value="HOUR">Hour</option><option value="DAY">Day</option>
                </select>
              </Field>
              <Field label="Owning team" className="span-2">
                <input className="input" value={form.ownerTeam ?? ""} disabled={!canEdit} onChange={(e) => set("ownerTeam", e.target.value)} />
              </Field>
              <Field label="Description shown to partners" className="span-2">
                <textarea className="textarea" rows={3} value={form.description ?? ""} disabled={!canEdit} onChange={(e) => set("description", e.target.value)} />
              </Field>
              <p className="muted span-2" style={{ fontSize: 12 }}>
                The limit is counted per partner Client ID at the gateway. New APIs are hidden from guest users until you switch them on.
              </p>
            </div>
          ) : null}

          {section === "request" ? (
            <div className="stack" style={{ gap: 26 }}>
              <EditorBlock title="Query parameters" sub="Appended to the URL, e.g. ?accountNumber=…">
                <FieldsEditor fields={doc.queryParameters} readOnly={!canEdit} onChange={(v) => setDoc({ queryParameters: v })} addLabel="+ Add query parameter" />
              </EditorBlock>
              <EditorBlock title="Request headers" sub="X-Security-Key is added for every API automatically; list only the extra headers partners must send.">
                <FieldsEditor fields={doc.requestHeaders} readOnly={!canEdit} onChange={(v) => setDoc({ requestHeaders: v })} addLabel="+ Add request header" namePlaceholder="X-Header-Name" />
              </EditorBlock>
              <EditorBlock title="Request body" sub="JSON example and its field reference. Use dotted names for nested fields (payee.ifsc).">
                <JsonExampleEditor
                  value={doc.requestBodyExample}
                  readOnly={!canEdit}
                  onChange={(v) => setDoc({ requestBodyExample: v })}
                  onGenerate={() => setDoc({ requestBodyFields: mergeFields(doc.requestBodyFields, inferFields(doc.requestBodyExample)) })}
                />
                <FieldsEditor fields={doc.requestBodyFields} readOnly={!canEdit} onChange={(v) => setDoc({ requestBodyFields: v })} addLabel="+ Add body field" />
              </EditorBlock>
            </div>
          ) : null}

          {section === "responses" ? (
            <ResponsesEditor doc={doc} readOnly={!canEdit} onChange={setDoc} />
          ) : null}

          {section === "preview" ? (
            <div style={{ maxWidth: 980 }}>
              <div className="banner banner-info" style={{ marginBottom: 16 }}>This is how the documentation appears to partners on the API's page in the Developer Portal (unsaved edits included).</div>
              <DocumentationView key={JSON.stringify(doc.responses.map((r) => r.statusCode))} docs={doc} method={form.httpMethod} keyHeader="X-Security-Key" />
            </div>
          ) : null}
        </div>
      </div>

      {importing ? (
        <ImportModal
          onClose={() => setImporting(false)}
          onPick={applyOperation}
          onImportedAll={(count) => {
            setImporting(false);
            queryClient.invalidateQueries({ queryKey: ["apis"] });
            navigate("/apis", { state: { notice: `${count} API${count === 1 ? "" : "s"} imported as drafts. Review each one, then enable it to publish to the gateways.` } });
          }}
        />
      ) : null}
    </div>
  );
}

function EditorBlock({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div>
        <h2 style={{ fontSize: 14.5 }}>{title}</h2>
        {sub ? <p className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>{sub}</p> : null}
      </div>
      {children}
    </section>
  );
}

function JsonExampleEditor({ value, onChange, onGenerate, readOnly, label = "Example (JSON)" }: {
  value: string | null;
  onChange: (next: string | null) => void;
  onGenerate: () => void;
  readOnly?: boolean;
  label?: string;
}) {
  const valid = isValidJson(value);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ gap: 8 }}>
        <span className="label">{label}</span>
        {!valid ? <Chip tone="bad">Invalid JSON</Chip> : null}
        <span className="grow" />
        {readOnly ? null : (
          <>
            <button type="button" className="btn btn-sm" disabled={!value || !valid} onClick={() => onChange(prettyJson(value))}>Format</button>
            <button type="button" className="btn btn-sm" disabled={!value || !valid} onClick={onGenerate}
              title="Build the field table from this example, keeping descriptions already written">Generate fields from example</button>
          </>
        )}
      </div>
      <textarea className="textarea mono" rows={Math.min(18, Math.max(6, (value ?? "").split("\n").length + 1))} spellCheck={false}
        style={{ fontSize: 12, borderColor: valid ? undefined : "var(--bad)" }} placeholder='{ "field": "value" }'
        value={value ?? ""} disabled={readOnly} onChange={(e) => onChange(e.target.value || null)} />
    </div>
  );
}

function ResponsesEditor({ doc, readOnly, onChange }: { doc: ApiDocumentation; readOnly: boolean; onChange: (patch: Partial<ApiDocumentation>) => void }) {
  const [selected, setSelected] = useState(0);
  const [newCode, setNewCode] = useState("");
  const responses = doc.responses;
  const current: ApiResponseDoc | undefined = responses[Math.min(selected, responses.length - 1)];
  const currentIndex = current ? responses.indexOf(current) : -1;
  const used = new Set(responses.map((r) => r.statusCode));

  const update = (patch: Partial<ApiResponseDoc>) =>
    onChange({ responses: responses.map((r, i) => (i === currentIndex ? { ...r, ...patch } : r)) });
  const add = (code: number) => {
    if (!code || used.has(code)) return;
    const label = COMMON_STATUS_CODES.find((c) => c.code === code)?.label ?? null;
    const next = [...responses, { statusCode: code, description: label, bodyExample: null, bodyFields: [] }].sort((a, b) => a.statusCode - b.statusCode);
    onChange({ responses: next });
    setSelected(next.findIndex((r) => r.statusCode === code));
    setNewCode("");
  };
  const remove = () => {
    onChange({ responses: responses.filter((_, i) => i !== currentIndex) });
    setSelected(0);
  };
  const customCode = Number(newCode);

  return (
    <div className="stack" style={{ gap: 26 }}>
      <EditorBlock title="Response body by HTTP status code" sub="Document one response per status code — the success payload and each error partners should handle.">
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          {responses.map((r, i) => (
            <button key={r.statusCode + ":" + i} type="button" className={`status-tab${i === currentIndex ? " on" : ""}`} onClick={() => setSelected(i)}>
              <Chip tone={statusTone(r.statusCode)}><span className="mono">{r.statusCode || "—"}</span></Chip>
              <span style={{ fontSize: 12 }}>{r.description ?? ""}</span>
            </button>
          ))}
          {readOnly ? null : (
            <div className="row" style={{ gap: 6, marginLeft: 6 }}>
              <select className="select cell-input" aria-label="Add status code" value="" onChange={(e) => add(Number(e.target.value))}>
                <option value="">+ Add status code…</option>
                {COMMON_STATUS_CODES.filter((c) => !used.has(c.code)).map((c) => <option key={c.code} value={c.code}>{c.code} {c.label}</option>)}
              </select>
              <input className="input cell-input mono" style={{ width: 76 }} placeholder="other" inputMode="numeric" aria-label="Custom status code"
                value={newCode} onChange={(e) => setNewCode(e.target.value.replace(/\D/g, "").slice(0, 3))} />
              <button type="button" className="btn btn-sm" disabled={!(customCode >= 100 && customCode <= 599) || used.has(customCode)} onClick={() => add(customCode)}>Add</button>
            </div>
          )}
        </div>

        {current ? (
          <div className="card" style={{ padding: "16px 18px" }}>
            <div className="stack" style={{ gap: 14 }}>
              <div className="row" style={{ gap: 12, alignItems: "flex-end" }}>
                <Field label="Status code">
                  <input className="input mono" style={{ width: 90 }} inputMode="numeric" value={current.statusCode || ""} disabled={readOnly}
                    onChange={(e) => update({ statusCode: Number(e.target.value.replace(/\D/g, "").slice(0, 3)) })} />
                </Field>
                <div className="grow">
                  <Field label="Description">
                    <input className="input" value={current.description ?? ""} disabled={readOnly} placeholder="When this response is returned"
                      onChange={(e) => update({ description: e.target.value || null })} />
                  </Field>
                </div>
                {readOnly ? null : <button type="button" className="btn btn-danger" onClick={remove}>Remove {current.statusCode}</button>}
              </div>
              <JsonExampleEditor
                label="Response body example (JSON)"
                value={current.bodyExample}
                readOnly={readOnly}
                onChange={(v) => update({ bodyExample: v })}
                onGenerate={() => update({ bodyFields: mergeFields(current.bodyFields, inferFields(current.bodyExample)) })}
              />
              <FieldsEditor fields={current.bodyFields} readOnly={readOnly} onChange={(v) => update({ bodyFields: v })} addLabel="+ Add response field" />
            </div>
          </div>
        ) : <p className="muted" style={{ fontSize: 12.5 }}>No responses yet — add the success code first.</p>}
      </EditorBlock>

      <EditorBlock title="Response headers" sub="Headers returned with the response (for example X-RateLimit-Remaining, X-Correlation-Id).">
        <FieldsEditor fields={doc.responseHeaders} readOnly={readOnly} onChange={(v) => onChange({ responseHeaders: v })} addLabel="+ Add response header" namePlaceholder="X-Header-Name" />
      </EditorBlock>
    </div>
  );
}

const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

/** CP-API-06: Swagger 2 / OpenAPI 3 (JSON or YAML) or Postman v2.x collection → one or many APIs. */
function ImportModal({ onClose, onPick, onImportedAll }: {
  onClose: () => void;
  onPick: (op: ImportedOperation, result: ImportResult) => void;
  onImportedAll: (count: number) => void;
}) {
  const { api } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [backendBase, setBackendBase] = useState("");

  const parse = useMutation({
    mutationFn: (file: { name: string; content: string }) => api.post<ImportResult>("/api/admin/apis/import", { fileName: file.name, content: file.content }),
    onSuccess: (r) => { setChosen(new Set(r.operations.map((_, i) => i))); setBackendBase(r.suggestedBackendBaseUrl ?? ""); },
  });
  const result = parse.data;

  const importAll = useMutation({
    mutationFn: async () => {
      const ops = (result?.operations ?? []).filter((_, i) => chosen.has(i));
      for (const op of ops) {
        await api.post<ApiView>("/api/admin/apis", {
          name: op.name, category: op.category, httpMethod: op.httpMethod, proxyPath: op.proxyPath,
          backendUrlSandbox: joinUrl(backendBase || null, op.proxyPath) ?? "http://mock-sandbox:8080" + op.proxyPath,
          backendUrlProduction: null, rateLimitCount: 300, rateLimitWindow: "MINUTE", ownerTeam: null,
          description: op.description, documentation: op.documentation, status: "DRAFT",
        } satisfies ApiRequest);
      }
      return ops.length;
    },
    onSuccess: onImportedAll,
  });

  const onFile = async (file: File | undefined) => {
    setLocalError(null);
    parse.reset();
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) {
      setLocalError("The file is larger than 5 MB.");
      return;
    }
    setFileName(file.name);
    parse.mutate({ name: file.name, content: await file.text() });
  };

  const toggle = (i: number) => setChosen((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; });

  return (
    <Modal
      title="Import Swagger / OpenAPI or Postman collection"
      width={760}
      onClose={onClose}
      footer={result ? <>
        <span className="muted grow" style={{ fontSize: 12 }}>Click an operation to load it into this form, or create all selected as drafts.</span>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={chosen.size === 0 || importAll.isPending} onClick={() => importAll.mutate()}>
          {importAll.isPending ? "Importing…" : `Import ${chosen.size} as drafts`}
        </button>
      </> : <button className="btn" onClick={onClose}>Cancel</button>}
    >
      <div
        className="card"
        style={{ padding: "22px 18px", textAlign: "center", borderStyle: "dashed", background: "var(--surface-muted)", cursor: "pointer" }}
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); void onFile(e.dataTransfer.files[0]); }}
      >
        <div style={{ fontWeight: 600 }}>{fileName ?? "Drop a file here or click to choose"}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Swagger 2.0 / OpenAPI 3.x (.json, .yaml) or Postman collection v2.x (.json) · up to 5 MB</div>
        <input ref={fileInput} type="file" hidden accept=".json,.yaml,.yml,application/json,application/yaml"
          onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
      </div>

      {localError ? <div className="banner banner-bad">{localError}</div> : null}
      <ErrorBanner error={parse.error ?? importAll.error} />
      {parse.isPending ? <div className="empty">Reading the file…</div> : null}

      {result ? (
        <>
          <div className="row" style={{ gap: 8 }}>
            <Chip tone="info">{result.format === "OPENAPI" ? "Swagger / OpenAPI" : "Postman"}</Chip>
            <strong>{result.title ?? "Untitled"}</strong>
            <span className="muted">· {result.operations.length} operation{result.operations.length === 1 ? "" : "s"}</span>
          </div>
          {result.warnings.length > 0 ? (
            <div className="banner banner-warn">
              <ul style={{ margin: "0 0 0 16px" }}>{result.warnings.slice(0, 6).map((w) => <li key={w}>{w}</li>)}</ul>
              {result.warnings.length > 6 ? <div>…and {result.warnings.length - 6} more</div> : null}
            </div>
          ) : null}
          <Field label="Backend base URL — Sandbox (used for drafts; each API's path is appended)">
            <input className="input mono" value={backendBase} placeholder="http://mock-sandbox:8080" onChange={(e) => setBackendBase(e.target.value)} />
          </Field>
          <div className="card" style={{ maxHeight: 320, overflowY: "auto" }}>
            <table className="table">
              <thead><tr><th style={{ width: 34 }}>
                <input type="checkbox" aria-label="Select all" checked={chosen.size === result.operations.length}
                  onChange={(e) => setChosen(e.target.checked ? new Set(result.operations.map((_, i) => i)) : new Set())} />
              </th><th>Operation</th><th>Documented</th><th /></tr></thead>
              <tbody>
                {result.operations.map((op, i) => (
                  <tr key={i}>
                    <td><input type="checkbox" aria-label={`Select ${op.name}`} checked={chosen.has(i)} onChange={() => toggle(i)} /></td>
                    <td>
                      <div className="row" style={{ gap: 8 }}>
                        <Chip tone={op.httpMethod === "GET" ? "info" : "ok"}><span className="mono">{op.httpMethod}</span></Chip>
                        <div>
                          <div className="cell-title">{op.name}</div>
                          <div className="cell-sub">{op.proxyPath} · {op.category}</div>
                        </div>
                      </div>
                    </td>
                    <td className="muted" style={{ fontSize: 11.5 }}>
                      {op.documentation.requestBodyFields.length} body fields · responses {op.documentation.responses.map((r) => r.statusCode).join(", ") || "—"}
                    </td>
                    <td><button className="btn btn-sm" onClick={() => onPick(op, { ...result, suggestedBackendBaseUrl: backendBase || null })}>Use this</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Modal>
  );
}