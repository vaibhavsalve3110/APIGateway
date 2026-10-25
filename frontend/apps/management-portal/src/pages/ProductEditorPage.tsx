import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  ApiError, Chip, ErrorBanner, Field, StatusChip, useAuth,
  type ApiView, type ProductRequest, type ProductView, type StepRequest,
} from "@apigw/ui";

const blank: ProductRequest = {
  name: "",
  summary: null,
  description: null,
  journeyMarkdown: null,
  steps: [],
};

function toRequest(product: ProductView): ProductRequest {
  return {
    name: product.name,
    summary: product.summary,
    description: product.description,
    journeyMarkdown: product.journeyMarkdown,
    steps: product.steps.map((s) => ({
      apiId: s.apiId,
      note: s.note,
      dependsOnApiId: s.dependsOnApiId,
    })),
  };
}

/**
 * Build a product: its description, and the ordered journey of APIs that makes it up (CP-API-09).
 *
 * The order of `steps` *is* the journey — the backend numbers them from the array, so moving a row
 * is the whole interaction. Each step can carry a note saying why it is there, and name an earlier
 * API it depends on, which is the thing partners most often get wrong when calling several in
 * sequence.
 */
export function ProductEditorPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const { api } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ProductRequest>(blank);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [adding, setAdding] = useState("");

  const existing = useQuery({
    queryKey: ["product", id],
    queryFn: () => api.get<ProductView>(`/api/admin/products/${id}`),
    enabled: !isNew,
  });
  const apis = useQuery({
    queryKey: ["apis"],
    queryFn: () => api.get<ApiView[]>("/api/admin/apis"),
  });

  useEffect(() => {
    if (existing.data) setForm(toRequest(existing.data));
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () => {
      const trim = (v: string | null) => (v && v.trim() ? v.trim() : null);
      const body: ProductRequest = {
        ...form,
        name: form.name.trim(),
        summary: trim(form.summary),
        description: trim(form.description),
        journeyMarkdown: trim(form.journeyMarkdown),
      };
      return isNew
        ? api.post<ProductView>("/api/admin/products", body)
        : api.put<ProductView>(`/api/admin/products/${id}`, body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      queryClient.setQueryData(["product", saved.id], saved);
      setSavedNote(`Saved ${new Date().toLocaleTimeString("en-IN")}`);
      if (isNew) navigate(`/products/${saved.id}`, { replace: true });
    },
  });

  const byId = useMemo(
    () => new Map((apis.data ?? []).map((a) => [a.id, a])),
    [apis.data],
  );
  const chosen = new Set(form.steps.map((s) => s.apiId));
  const available = (apis.data ?? []).filter((a) => !chosen.has(a.id));

  const set = <K extends keyof ProductRequest>(key: K, value: ProductRequest[K]) => {
    setSavedNote(null);
    setForm((f) => ({ ...f, [key]: value }));
  };
  const setSteps = (steps: StepRequest[]) => set("steps", steps);
  const patchStep = (index: number, patch: Partial<StepRequest>) =>
    setSteps(form.steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));

  const move = (index: number, by: number) => {
    const next = [...form.steps];
    const target = index + by;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next);
  };

  const addStep = (apiId: string) => {
    if (!apiId) return;
    setSteps([...form.steps, { apiId, note: null, dependsOnApiId: null }]);
    setAdding("");
  };

  const fieldError = (name: string) =>
    save.error instanceof ApiError ? save.error.fields[name] : undefined;

  const draftSteps = form.steps.filter((s) => byId.get(s.apiId)?.status !== "ACTIVE");

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <div className="muted" style={{ fontSize: 12 }}>
            <Link to="/products">Products</Link> / {isNew ? "Add product" : form.name || "Product"}
          </div>
          <div className="row" style={{ gap: 10, marginTop: 4 }}>
            <h1>{isNew ? "Add product" : form.name || "Product"}</h1>
            {existing.data ? <StatusChip status={existing.data.status} /> : null}
          </div>
          <p className="page-sub">
            A product is an ordered journey through several APIs. Partners see it in the Developer
            Portal once it is published and mapped to them.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {savedNote ? <span className="muted" style={{ fontSize: 12 }}>{savedNote}</span> : null}
          {!isNew && existing.data ? (
            <Link className="btn" to={`/mapping?product=${existing.data.id}`}>Map to partners</Link>
          ) : null}
          <button className="btn btn-primary" disabled={save.isPending || !form.name.trim()}
            onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : isNew ? "Add product" : "Save changes"}
          </button>
        </div>
      </div>

      <ErrorBanner error={save.error ?? existing.error ?? apis.error} />

      {existing.data?.status === "PUBLISHED" && draftSteps.length > 0 ? (
        <div className="banner banner-warn">
          {draftSteps.length} of these steps {draftSteps.length === 1 ? "is" : "are"} not a live API,
          so partners will not see {draftSteps.length === 1 ? "it" : "them"} in the journey. Publish
          the {draftSteps.length === 1 ? "API" : "APIs"} to complete the product.
        </div>
      ) : null}

      <div className="card pad" style={{ marginBottom: 14 }}>
        <div className="grid-2">
          <Field label="Name" error={fieldError("name")}>
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Summary" error={fieldError("summary")}>
            <input className="input" value={form.summary ?? ""} placeholder="One line, shown in the partner's list"
              onChange={(e) => set("summary", e.target.value)} />
          </Field>
        </div>
        <Field label="Description" error={fieldError("description")}>
          <textarea className="textarea" rows={3} value={form.description ?? ""}
            placeholder="What this product is for, and who should use it"
            onChange={(e) => set("description", e.target.value)} />
        </Field>
        <Field label="Integration guide (Markdown)" error={fieldError("journeyMarkdown")}>
          <textarea className="textarea mono" rows={8} value={form.journeyMarkdown ?? ""}
            placeholder={"## Before you start\n\nWhat a partner needs in place, then the order to call things in."}
            onChange={(e) => set("journeyMarkdown", e.target.value)} />
        </Field>
        {existing.data ? (
          <p className="muted small">
            Partner URL: <span className="mono">/products/{existing.data.slug}</span> — derived from
            the name and kept unique. Renaming the product does not change a slug partners already
            have.
          </p>
        ) : null}
      </div>

      <div className="card">
        <div className="pad row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div className="strong">The journey</div>
            <div className="muted small">
              The order here is the order partners are told to call them in.
            </div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <select className="select" value={adding} onChange={(e) => addStep(e.target.value)}
              disabled={available.length === 0}>
              <option value="">
                {available.length === 0 ? "Every API is already a step" : "Add a step…"}
              </option>
              {available.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} — {a.httpMethod} {a.proxyPath}
                  {a.status !== "ACTIVE" ? ` (${a.status.toLowerCase()})` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {form.steps.length === 0 ? (
          <div className="pad empty">
            No steps yet. Add the APIs a partner calls, in the order they call them.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 54 }}>Step</th><th>API</th><th>Why this step</th>
                <th>Depends on</th><th style={{ width: 96 }} />
              </tr>
            </thead>
            <tbody>
              {form.steps.map((step, index) => {
                const target = byId.get(step.apiId);
                return (
                  <tr key={step.apiId}>
                    <td className="mono">{index + 1}</td>
                    <td>
                      <div className="strong">{target?.name ?? <span className="muted">unknown API</span>}</div>
                      <div className="muted small mono">
                        {target ? `${target.httpMethod} ${target.proxyPath}` : step.apiId}
                      </div>
                      {target && target.status !== "ACTIVE" ? (
                        <Chip tone="warn">{target.status.toLowerCase()} — partners will not see this step</Chip>
                      ) : null}
                    </td>
                    <td>
                      <input className="input" value={step.note ?? ""} placeholder="Optional"
                        onChange={(e) => patchStep(index, { note: e.target.value || null })} />
                    </td>
                    <td>
                      {/* Only earlier steps: a dependency on a later one would describe a journey
                          that cannot be followed in the order given. */}
                      <select className="select" value={step.dependsOnApiId ?? ""}
                        onChange={(e) => patchStep(index, { dependsOnApiId: e.target.value || null })}>
                        <option value="">Nothing</option>
                        {form.steps.slice(0, index).map((earlier) => (
                          <option key={earlier.apiId} value={earlier.apiId}>
                            {byId.get(earlier.apiId)?.name ?? earlier.apiId}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="right nowrap">
                      <button className="btn btn-sm" disabled={index === 0} onClick={() => move(index, -1)}
                        title="Move earlier">↑</button>{" "}
                      <button className="btn btn-sm" disabled={index === form.steps.length - 1}
                        onClick={() => move(index, 1)} title="Move later">↓</button>{" "}
                      <button className="btn btn-sm btn-danger"
                        onClick={() => setSteps(form.steps.filter((_, i) => i !== index))}
                        title="Remove this step">×</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {!isNew && existing.data && existing.data.assignments.length > 0 ? (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="pad row" style={{ justifyContent: "space-between" }}>
            <div className="strong">Mapped to</div>
            <Link className="btn btn-sm" to={`/mapping?product=${existing.data.id}`}>Manage mappings</Link>
          </div>
          <table className="table">
            <thead>
              <tr><th>Organization</th><th>Scope</th><th>Authority</th><th>Mapped</th></tr>
            </thead>
            <tbody>
              {existing.data.assignments.map((a) => (
                <tr key={a.id}>
                  <td>{a.partnerName} <span className="muted mono small">{a.partnerCode}</span></td>
                  <td>{a.partnerUserEmail ?? "Whole organization"}</td>
                  <td className="small">{a.approvalReference}</td>
                  <td className="muted small nowrap">{a.assignedBy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
