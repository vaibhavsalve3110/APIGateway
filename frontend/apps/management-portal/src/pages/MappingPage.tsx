import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  ApiError, Chip, ErrorBanner, Field, Modal, PageHeader, formatDateTime, useAuth,
  type PartnerUserView, type PartnerView, type ProductView,
} from "@apigw/ui";

/**
 * Access mapping (CP-PTN-03): which organizations may use which product.
 *
 * A mapping names an organization, optionally narrowed to one person inside it — useful for a pilot
 * before the whole organization is let in. **Every mapping requires an approval reference**, because
 * the question asked in a review is not who clicked it, which the audit trail answers, but who
 * authorised it. The platform cannot verify a ticket number, so it is free text; what it can do is
 * refuse to save a mapping without one.
 *
 * Mapping a draft product is allowed on purpose: the access decision and the publishing decision are
 * separate, and lining up mappings before launch is the normal order of work. The table says plainly
 * when a product is not published, so nobody expects partners to see it yet.
 */
export function MappingPage() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const productFilter = params.get("product") ?? "";

  const [mapping, setMapping] = useState(false);
  const [removing, setRemoving] = useState<{ product: ProductView; assignmentId: string; who: string } | null>(null);
  const [form, setForm] = useState({ productId: "", partnerId: "", partnerUserId: "", approvalReference: "" });

  const products = useQuery({
    queryKey: ["products"],
    queryFn: () => api.get<ProductView[]>("/api/admin/products"),
  });
  const partners = useQuery({
    queryKey: ["partners"],
    queryFn: () => api.get<PartnerView[]>("/api/admin/partners"),
  });
  // Only needed once somebody narrows a mapping to a person, but cheap and it keeps the dialog
  // responsive rather than fetching on each change of organization.
  const partnerUsers = useQuery({
    queryKey: ["partner-users"],
    queryFn: () => api.get<PartnerUserView[]>("/api/admin/partner-users"),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["products"] });

  const assign = useMutation({
    mutationFn: () =>
      api.post<ProductView>(`/api/admin/products/${form.productId}/assignments`, {
        partnerId: form.partnerId,
        partnerUserId: form.partnerUserId || null,
        approvalReference: form.approvalReference.trim(),
      }),
    onSuccess: () => {
      refresh();
      setMapping(false);
      // The reference is deliberately *not* kept for the next mapping: it is the authority for one
      // decision, and carrying it over is how the wrong ticket ends up against the wrong partner.
      setForm({ productId: form.productId, partnerId: "", partnerUserId: "", approvalReference: "" });
    },
  });

  const unassign = useMutation({
    mutationFn: ({ product, assignmentId }: { product: ProductView; assignmentId: string }) =>
      api.del(`/api/admin/products/${product.id}/assignments/${assignmentId}`),
    onSuccess: () => { refresh(); setRemoving(null); },
  });

  useEffect(() => {
    if (productFilter && !form.productId) setForm((f) => ({ ...f, productId: productFilter }));
  }, [productFilter, form.productId]);

  const all = products.data ?? [];
  const shown = productFilter ? all.filter((p) => p.id === productFilter) : all;

  /** Every mapping across every product, flattened, so this reads as a list of access grants. */
  const mappings = useMemo(
    () => shown.flatMap((product) => product.assignments.map((a) => ({ product, assignment: a }))),
    [shown],
  );

  const usersOf = (partnerId: string) =>
    (partnerUsers.data ?? []).filter((u) => u.partnerId === partnerId);
  const fieldError = (name: string) =>
    assign.error instanceof ApiError ? assign.error.fields[name] : undefined;

  const unmapped = all.filter((p) => p.assignments.length === 0);

  return (
    <div className="page">
      <PageHeader
        title="Access mapping"
        subtitle="Which organizations may use which product, and the authority for each grant"
        actions={
          <button className="btn btn-primary" disabled={all.length === 0} onClick={() => setMapping(true)}>
            + Map a product
          </button>
        }
      />

      <ErrorBanner error={products.error ?? partners.error ?? unassign.error} />

      {products.isLoading ? (
        // Checked before the empty state, not after: an empty `all` means "not loaded yet" just as
        // often as it means "nothing exists", and telling someone to create a product they already
        // have is worse than a moment of "Loading…".
        <div className="card pad">Loading…</div>
      ) : all.length === 0 ? (
        <div className="card pad empty">
          There are no products to map yet. <Link to="/products/new">Create one</Link> — a product is
          an ordered set of APIs that you grant as a single thing.
        </div>
      ) : (
        <>
          <div className="row" style={{ gap: 10, marginBottom: 12, alignItems: "center" }}>
            <select className="select" style={{ maxWidth: 320 }} value={productFilter}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                if (e.target.value) next.set("product", e.target.value); else next.delete("product");
                setParams(next, { replace: true });
              }}>
              <option value="">All products</option>
              {all.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <div className="muted small">
              {mappings.length} mapping{mappings.length === 1 ? "" : "s"}
              {unmapped.length > 0 && !productFilter
                ? ` — ${unmapped.length} product${unmapped.length === 1 ? "" : "s"} mapped to nobody`
                : ""}
            </div>
          </div>

          {mappings.length === 0 ? (
            <div className="card pad empty">
              {productFilter
                ? "This product is not mapped to anyone yet, so no partner can see it."
                : "Nothing is mapped yet. A published product is still invisible until it is mapped to an organization."}
            </div>
          ) : (
            <div className="card">
              <table className="table">
                <thead>
                  <tr>
                    <th>Product</th><th>Organization</th><th>Scope</th>
                    <th>Authority (CP-PTN-03)</th><th>Mapped by</th><th />
                  </tr>
                </thead>
                <tbody>
                  {mappings.map(({ product, assignment }) => (
                    <tr key={assignment.id}>
                      <td>
                        <div className="strong">{product.name}</div>
                        {product.status !== "PUBLISHED" ? (
                          <Chip tone="warn">draft — partners cannot see it yet</Chip>
                        ) : (
                          <div className="muted small mono">/{product.slug}</div>
                        )}
                      </td>
                      <td>
                        {assignment.partnerName}
                        <div className="muted small mono">{assignment.partnerCode}</div>
                      </td>
                      <td>
                        {assignment.partnerUserEmail ? (
                          <>
                            <Chip tone="info">one person</Chip>
                            <div className="muted small">{assignment.partnerUserEmail}</div>
                          </>
                        ) : (
                          "Whole organization"
                        )}
                      </td>
                      <td className="small">{assignment.approvalReference}</td>
                      <td className="muted small nowrap">
                        {assignment.assignedBy}
                        <div>{formatDateTime(assignment.assignedAt)}</div>
                      </td>
                      <td className="right">
                        <button className="btn btn-sm btn-danger"
                          onClick={() => setRemoving({
                            product,
                            assignmentId: assignment.id,
                            who: assignment.partnerUserEmail ?? assignment.partnerName ?? "that organization",
                          })}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {mapping ? (
        <Modal
          title="Map a product to a partner"
          onClose={() => { setMapping(false); assign.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setMapping(false); assign.reset(); }}>Cancel</button>
              <button className="btn btn-primary"
                disabled={assign.isPending || !form.productId || !form.partnerId || !form.approvalReference.trim()}
                onClick={() => assign.mutate()}>
                {assign.isPending ? "Mapping…" : "Save mapping"}
              </button>
            </>
          }
        >
          <ErrorBanner error={assign.error} />
          <Field label="Product" error={fieldError("productId")}>
            <select className="select" value={form.productId}
              onChange={(e) => setForm({ ...form, productId: e.target.value })}>
              <option value="">Choose a product…</option>
              {all.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.status !== "PUBLISHED" ? " (draft)" : ""}
                </option>
              ))}
            </select>
          </Field>
          {form.productId && all.find((p) => p.id === form.productId)?.status !== "PUBLISHED" ? (
            <p className="muted small">
              This product is a draft. The mapping is saved now and takes effect the moment it is
              published — lining mappings up before launch is the normal order of work.
            </p>
          ) : null}

          <Field label="Organization" error={fieldError("partnerId")}>
            <select className="select" value={form.partnerId}
              onChange={(e) => setForm({ ...form, partnerId: e.target.value, partnerUserId: "" })}>
              <option value="">Choose an organization…</option>
              {(partners.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name} — {p.code}</option>
              ))}
            </select>
          </Field>

          <Field label="Scope">
            <select className="select" value={form.partnerUserId} disabled={!form.partnerId}
              onChange={(e) => setForm({ ...form, partnerUserId: e.target.value })}>
              <option value="">The whole organization</option>
              {usersOf(form.partnerId).map((u) => (
                <option key={u.id} value={u.id}>Only {u.fullName} — {u.email}</option>
              ))}
            </select>
          </Field>
          <p className="muted small">
            Narrowing to one person is for a pilot: only they see the product, and the rest of the
            organization does not.
          </p>

          <Field label="Approval reference" error={fieldError("approvalReference")}>
            <input className="input" value={form.approvalReference}
              placeholder="Ticket number, e-mail subject, signed-note id"
              onChange={(e) => setForm({ ...form, approvalReference: e.target.value })} />
          </Field>
          <p className="muted small">
            Required (CP-PTN-03). Granting a partner access is an access decision, and this is what
            records who authorised it — the audit trail already records who clicked. It is stored on
            the mapping and written into the trail.
          </p>
        </Modal>
      ) : null}

      {removing ? (
        <Modal
          title="Remove this mapping?"
          onClose={() => { setRemoving(null); unassign.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setRemoving(null); unassign.reset(); }}>Cancel</button>
              <button className="btn btn-danger" disabled={unassign.isPending}
                onClick={() => unassign.mutate({ product: removing.product, assignmentId: removing.assignmentId })}>
                {unassign.isPending ? "Removing…" : "Remove mapping"}
              </button>
            </>
          }
        >
          <ErrorBanner error={unassign.error} />
          <p>
            {removing.who} will no longer see <strong>{removing.product.name}</strong> in the
            Developer Portal. Their security keys and their access to the individual APIs are not
            affected — a product is a grouping, not a permission on the gateway.
          </p>
          <p className="muted small">
            The authority this was granted under is kept in the audit trail.
          </p>
        </Modal>
      ) : null}
    </div>
  );
}
