import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Chip, ErrorBanner, useAuth } from "@apigw/ui";

import { usePartner } from "../usePartner";

interface CatalogueApi {
  id: string;
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  description: string | null;
  rateLimitCount: number;
  rateLimitWindow: string;
  productionAvailable: boolean;
}

/** My API catalogue (design: DevPortalHome.dc.html; BRD DP-02, DP-08). */
export function CataloguePage() {
  const { api } = useAuth();
  const me = usePartner();
  const apis = useQuery({ queryKey: ["catalogue"], queryFn: () => api.get<CatalogueApi[]>("/api/partner/apis") });
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const rows = (apis.data ?? []).filter((a) => !q || `${a.name} ${a.proxyPath} ${a.category}`.toLowerCase().includes(q));
  const categories = [...new Set(rows.map((a) => a.category))].sort();

  return (
    <div className="page" style={{ padding: "28px 30px 34px" }}>
      <div className="page-head">
        <div className="grow">
          <h1 style={{ fontSize: 26 }}>Your API catalogue</h1>
          <p className="page-sub" style={{ fontSize: 13.5, maxWidth: 640 }}>
            Everything mapped to {me.data?.name ?? "your account"}. Read the contract, run it against the Sandbox, and take the same
            request to Production once your access tier allows it.
          </p>
          {me.data ? (
            <div className="row" style={{ gap: 8, marginTop: 14 }}>
              <Chip tone="info">SANDBOX CLIENT ID · {me.data.clientIdSandbox}</Chip>
              {me.data.clientIdProduction
                ? <Chip tone="ok">PRODUCTION CLIENT ID · {me.data.clientIdProduction}</Chip>
                : <Chip>PRODUCTION NOT PROVISIONED</Chip>}
            </div>
          ) : null}
        </div>
        <input className="input" style={{ width: 280 }} placeholder="Search APIs" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ErrorBanner error={apis.error ?? me.error} />

      {apis.isLoading ? <div className="empty">Loading…</div> : categories.map((category) => (
        <section key={category} className="stack" style={{ gap: 12 }}>
          <h2>{category}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
            {rows.filter((a) => a.category === category).map((a) => (
              <Link key={a.id} to={`/apis/${a.id}`} className="card api-card" style={{ padding: "15px 17px", display: "flex", flexDirection: "column", gap: 8 }}>
                <div className="row" style={{ gap: 8 }}>
                  <Chip tone={a.httpMethod === "GET" ? "info" : "ok"}><span className="mono">{a.httpMethod}</span></Chip>
                  <span className="mono muted" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis" }}>{a.proxyPath}</span>
                </div>
                <div className="api-card-name" style={{ fontSize: 13.5, fontWeight: 600 }}>{a.name}</div>
                <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, flex: 1 }}>{a.description ?? "Documentation coming soon."}</p>
                <div className="row" style={{ gap: 8, paddingTop: 10, borderTop: "1px solid var(--border-row)" }}>
                  <Chip tone="info">SANDBOX</Chip>
                  {a.productionAvailable ? <Chip tone="ok">PRODUCTION</Chip> : null}
                  <span className="grow" />
                  <span className="muted" style={{ fontSize: 11.5 }}>{a.rateLimitCount.toLocaleString("en-IN")} / {a.rateLimitWindow.toLowerCase()}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
