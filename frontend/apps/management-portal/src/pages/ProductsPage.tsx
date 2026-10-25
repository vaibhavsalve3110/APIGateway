import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import {
  Chip, ErrorBanner, formatDateTime, Modal, PageHeader, StatusChip, useAuth,
  type ProductView,
} from "@apigw/ui";

/**
 * API Products (CP-API-09): an ordered journey through several APIs, published to the partners it
 * has been mapped to.
 *
 * A product is a draft until published, exactly as an API is. Unlike an API, publishing it is not
 * reviewed — a product is documentation and an access grouping, not a route on the gateway, and
 * products are administrator-only to begin with.
 */
export function ProductsPage() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [deleting, setDeleting] = useState<ProductView | null>(null);

  const products = useQuery({
    queryKey: ["products"],
    queryFn: () => api.get<ProductView[]>("/api/admin/products"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["products"] });

  const setPublished = useMutation({
    mutationFn: (product: ProductView) =>
      api.post<ProductView>(
        `/api/admin/products/${product.id}/${product.status === "PUBLISHED" ? "unpublish" : "publish"}`,
      ),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (product: ProductView) => api.del(`/api/admin/products/${product.id}`),
    onSuccess: () => { refresh(); setDeleting(null); },
  });

  const all = products.data ?? [];
  const q = query.trim().toLowerCase();
  const rows = useMemo(
    () => (q ? all.filter((p) => `${p.name} ${p.summary ?? ""} ${p.slug}`.toLowerCase().includes(q)) : all),
    [all, q],
  );

  return (
    <div className="page">
      <PageHeader
        title="Products"
        subtitle="Bundle APIs into a journey partners can follow, then map it to the organizations that may use it"
        actions={
          <button className="btn btn-primary" onClick={() => navigate("/products/new")}>+ Add product</button>
        }
      />

      <ErrorBanner error={products.error ?? setPublished.error ?? remove.error} />

      <div className="row" style={{ gap: 10, marginBottom: 12 }}>
        <input className="input" style={{ maxWidth: 320 }} placeholder="Search products"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="muted small">
          {all.length} product{all.length === 1 ? "" : "s"},{" "}
          {all.filter((p) => p.status === "PUBLISHED").length} published
        </div>
      </div>

      {products.isLoading ? (
        <div className="card pad">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card pad empty">
          {all.length === 0
            ? "No products yet. A product is an ordered set of APIs — an onboarding journey, a payments flow — that you map to partners as one thing."
            : "No product matches that search."}
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Product</th><th>Steps</th><th>Mapped to</th><th>Status</th><th>Last updated</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((product) => {
                const drafts = product.steps.filter((s) => s.status !== "ACTIVE").length;
                const orgs = new Set(product.assignments.map((a) => a.partnerId)).size;
                const people = product.assignments.filter((a) => a.partnerUserId).length;
                return (
                  <tr key={product.id}>
                    <td>
                      <div className="strong">{product.name}</div>
                      <div className="muted small mono">/{product.slug}</div>
                      {product.summary ? <div className="muted small">{product.summary}</div> : null}
                    </td>
                    <td>
                      {product.steps.length}
                      {/* Worth surfacing here: a published product whose steps are still drafts
                          shows a partner an empty journey, which looks like a broken page. */}
                      {drafts > 0 ? (
                        <div className="muted small">
                          <Chip tone="warn">{drafts} not live</Chip>
                        </div>
                      ) : null}
                    </td>
                    <td>
                      {orgs === 0 ? (
                        <span className="muted">nobody yet</span>
                      ) : (
                        <>
                          {orgs} organization{orgs === 1 ? "" : "s"}
                          {people > 0 ? <div className="muted small">{people} named person{people === 1 ? "" : "s"}</div> : null}
                        </>
                      )}
                    </td>
                    <td><StatusChip status={product.status} /></td>
                    <td className="muted nowrap" style={{ fontSize: 12 }}>{formatDateTime(product.updatedAt)}</td>
                    <td className="right nowrap">
                      <button className="btn btn-sm" onClick={() => navigate(`/products/${product.id}`)}>Edit</button>{" "}
                      <button className="btn btn-sm" disabled={setPublished.isPending}
                        onClick={() => setPublished.mutate(product)}
                        title={product.status === "PUBLISHED"
                          ? "Partners stop seeing it; the mappings are kept"
                          : "Partners mapped to it will see it"}>
                        {product.status === "PUBLISHED" ? "Unpublish" : "Publish"}
                      </button>{" "}
                      <button className="btn btn-sm btn-danger" onClick={() => setDeleting(product)}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {deleting ? (
        <Modal
          title={`Delete ${deleting.name}?`}
          onClose={() => { setDeleting(null); remove.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setDeleting(null); remove.reset(); }}>Cancel</button>
              <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate(deleting)}>
                {remove.isPending ? "Deleting…" : "Delete product"}
              </button>
            </>
          }
        >
          <ErrorBanner error={remove.error} />
          <p>
            The product and its {deleting.assignments.length} mapping
            {deleting.assignments.length === 1 ? "" : "s"} are removed. The APIs themselves are not
            touched — a product is only a grouping of them.
          </p>
          {deleting.status === "PUBLISHED" ? (
            <p className="notice small">
              This product is published. Partners mapped to it will lose it immediately. Unpublishing
              instead keeps the mappings and can be undone.
            </p>
          ) : null}
        </Modal>
      ) : null}
    </div>
  );
}
