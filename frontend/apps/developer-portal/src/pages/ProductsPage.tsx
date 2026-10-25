import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Chip, ErrorBanner, PageHeader, useAuth, type PartnerProductView } from "@apigw/ui";

/**
 * The products this organization has been given (CP-API-09).
 *
 * A product is an ordered journey through several APIs — onboarding, a payments flow — rather than a
 * single endpoint. Only products published *and* mapped to this organization appear, which is why
 * an empty list here is normal rather than a fault.
 */
export function ProductsPage() {
  const { api } = useAuth();

  const products = useQuery({
    queryKey: ["partner-products"],
    queryFn: () => api.get<PartnerProductView[]>("/api/partner/products"),
  });

  const rows = products.data ?? [];

  return (
    <div className="page">
      <PageHeader
        title="Products"
        subtitle="Guided journeys through several APIs, assembled for you"
      />

      <ErrorBanner error={products.error} />

      {products.isLoading ? (
        <div className="card pad">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card pad empty">
          No products have been shared with your organization yet. Your APIs are all under{" "}
          <Link to="/apis">API Catalogue</Link> — a product simply groups several of them into a
          sequence. Ask your relationship manager if you expected one here.
        </div>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          {rows.map((product) => (
            <div className="card" key={product.id}>
              <div className="pad">
                <div className="row" style={{ gap: 10, alignItems: "center" }}>
                  <h2 style={{ margin: 0 }}>{product.name}</h2>
                  {/* Worth saying: it means the rest of the organization cannot see this yet, which
                      explains why a colleague's portal looks different. */}
                  {product.assignedToYouDirectly ? <Chip tone="info">shared with you personally</Chip> : null}
                </div>
                {product.summary ? <p className="page-sub">{product.summary}</p> : null}
                {product.description ? <p>{product.description}</p> : null}
              </div>

              {product.steps.length === 0 ? (
                <div className="pad empty">
                  The APIs for this product are not published yet. It will fill in as they go live.
                </div>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: 54 }}>Step</th><th>API</th><th>Call</th><th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {product.steps.map((step) => (
                      <tr key={`${product.id}-${step.step}`}>
                        <td className="mono">{step.step}</td>
                        <td>
                          <Link to={`/apis/${step.apiId}`} className="strong">{step.apiName}</Link>
                          {step.apiDescription ? (
                            <div className="muted small">{step.apiDescription}</div>
                          ) : null}
                        </td>
                        <td className="mono nowrap small">{step.httpMethod} {step.proxyPath}</td>
                        <td className="small">
                          {step.note}
                          {step.dependsOnApiName ? (
                            <div className="muted">
                              Call <strong>{step.dependsOnApiName}</strong> first — this step needs
                              what it returns.
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {product.journeyMarkdown ? (
                <div className="pad">
                  <div className="strong" style={{ marginBottom: 6 }}>Integration guide</div>
                  {/* Rendered as pre-wrapped text rather than parsed: the portal has no Markdown
                      renderer yet, and showing the source is honest where half-parsed output is not. */}
                  <pre className="code" style={{ whiteSpace: "pre-wrap" }}>{product.journeyMarkdown}</pre>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
