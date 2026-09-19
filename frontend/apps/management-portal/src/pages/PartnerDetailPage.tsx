import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Chip, ErrorBanner, GeneratedKeyModal, KeyTable, Modal, StatusChip, useAuth,
  type AccessTier, type Env, type GeneratedKey, type KeyView, type PartnerView,
} from "@apigw/ui";

/** One partner: access tier, Client IDs and security keys (designs: Partners + SecurityKeys artboards). */
export function PartnerDetailPage() {
  const { id = "" } = useParams();
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const [generated, setGenerated] = useState<GeneratedKey | null>(null);
  const [confirmTier, setConfirmTier] = useState<AccessTier | null>(null);

  const partner = useQuery({ queryKey: ["partner", id], queryFn: () => api.get<PartnerView>(`/api/admin/partners/${id}`) });
  const keys = useQuery({
    queryKey: ["partner-keys", id],
    queryFn: () => api.get<KeyView[]>(`/api/admin/partners/${id}/keys`),
    refetchInterval: 15_000, // picks up the automatic expiry at the end of an overlap window
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["partner", id] });
    void queryClient.invalidateQueries({ queryKey: ["partner-keys", id] });
    void queryClient.invalidateQueries({ queryKey: ["partners"] });
  };

  const generate = useMutation({
    mutationFn: (env: Env) => api.post<GeneratedKey>(`/api/admin/partners/${id}/keys/${env}`),
    onSuccess: (g) => { setGenerated(g); refresh(); },
  });
  const revoke = useMutation({
    mutationFn: (k: KeyView) => api.post<KeyView>(`/api/admin/keys/${k.id}/revoke`),
    onSuccess: refresh,
  });
  const changeTier = useMutation({
    mutationFn: (tier: AccessTier) => api.put<PartnerView>(`/api/admin/partners/${id}/access-tier`, { accessTier: tier }),
    onSuccess: () => { setConfirmTier(null); refresh(); },
  });
  const setStatus = useMutation({
    mutationFn: (status: "ACTIVE" | "DISABLED") => api.put<PartnerView>(`/api/admin/partners/${id}/status`, { status }),
    onSuccess: refresh,
  });

  const p = partner.data;
  if (partner.isLoading) {
    return <div className="empty">Loading…</div>;
  }
  if (!p) {
    return <div className="page"><ErrorBanner error={partner.error} /></div>;
  }
  const rotating = new Set((keys.data ?? []).filter((k) => k.status === "EXPIRING").map((k) => k.environment));

  return (
    <div className="page">
      <div className="muted" style={{ fontSize: 12 }}><Link to="/partners">Groups & Partners</Link> / {p.name}</div>
      <div className="page-head">
        <div style={{ width: 46, height: 46, borderRadius: 9, background: "var(--accent-tint)", color: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 600, fontSize: 15 }}>
          {p.name.split(/\s+/).slice(0, 2).map((w) => w[0]).join("")}
        </div>
        <div className="grow">
          <div className="row" style={{ gap: 9 }}><h1>{p.name}</h1><StatusChip status={p.status} /></div>
          <p className="page-sub">Partner ID {p.code} · {p.groupName} · {p.contactEmail ?? "no contact e-mail"}</p>
        </div>
        <button className="btn" disabled={setStatus.isPending} onClick={() => setStatus.mutate(p.status === "ACTIVE" ? "DISABLED" : "ACTIVE")}>
          {p.status === "ACTIVE" ? "Disable partner" : "Re-enable partner"}
        </button>
      </div>
      <ErrorBanner error={generate.error ?? revoke.error ?? changeTier.error ?? setStatus.error ?? keys.error} />

      <div className="row" style={{ alignItems: "stretch", gap: 16 }}>
        <div className="card grow" style={{ padding: "16px 18px" }}>
          <div className="card-title">Access tier</div>
          <p className="muted" style={{ fontSize: 12.5, margin: "3px 0 14px" }}>
            Enforced by the gateways themselves: each environment is a separate gateway, and a partner only has a Client ID and keys on the ones it is entitled to.
          </p>
          {(["UAT_ONLY", "PRODUCTION"] as AccessTier[]).map((tier) => (
            <label key={tier} className="row" style={{
              alignItems: "flex-start", padding: "11px 13px", borderRadius: 6, marginBottom: 9, cursor: "pointer",
              border: `1.5px solid ${p.accessTier === tier ? "var(--accent)" : "var(--border)"}`,
              background: p.accessTier === tier ? "#f5f8fd" : undefined,
            }}>
              <input type="radio" checked={p.accessTier === tier} onChange={() => setConfirmTier(tier)} style={{ marginTop: 3 }} />
              <span>
                <strong style={{ fontSize: 12.5 }}>{tier === "UAT_ONLY" ? "UAT access only" : "Production access (includes UAT)"}</strong>
                <span className="muted" style={{ display: "block", fontSize: 12, marginTop: 2 }}>
                  {tier === "UAT_ONLY" ? "Sandbox URL only. Production calls are rejected at the gateway."
                    : "Sandbox and Production URLs, each with its own Client ID and keys."}
                </span>
              </span>
            </label>
          ))}
        </div>
        <div className="card" style={{ width: 360, padding: "16px 18px" }}>
          <div className="card-title" style={{ marginBottom: 12 }}>Client IDs</div>
          <EnvRow env="SANDBOX" clientId={p.clientIdSandbox} provisioned onGenerate={() => generate.mutate("SANDBOX")}
            busy={generate.isPending} rotating={rotating.has("SANDBOX")} disabled={p.status !== "ACTIVE"} />
          <EnvRow env="PRODUCTION" clientId={p.clientIdProduction} provisioned={p.accessTier === "PRODUCTION"}
            onGenerate={() => generate.mutate("PRODUCTION")} busy={generate.isPending} rotating={rotating.has("PRODUCTION")}
            disabled={p.status !== "ACTIVE"} />
          <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>Rate limits are counted per Client ID, so a partner's two keys share one allowance.</p>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">Security keys</div>
            <div className="card-sub">Masked only — keys are shown once, to whoever generates them. A new key keeps the previous one alive for 20 minutes.</div>
          </div>
        </div>
        {keys.isLoading ? <div className="empty">Loading…</div> : (
          <KeyTable keys={keys.data ?? []} onRevoke={(k) => revoke.mutate(k)} revoking={revoke.isPending ? revoke.variables?.id : null} />
        )}
      </div>

      {generated ? <GeneratedKeyModal generated={generated} onClose={() => setGenerated(null)} /> : null}
      {confirmTier ? (
        <Modal
          title={confirmTier === "PRODUCTION" ? "Grant Production access?" : "Withdraw Production access?"}
          onClose={() => setConfirmTier(null)}
          footer={<>
            <button className="btn" onClick={() => setConfirmTier(null)}>Cancel</button>
            <button className={`btn ${confirmTier === "PRODUCTION" ? "btn-primary" : "btn-danger"}`} disabled={changeTier.isPending}
              onClick={() => changeTier.mutate(confirmTier)}>
              {confirmTier === "PRODUCTION" ? "Grant Production access" : "Withdraw and revoke keys"}
            </button>
          </>}
        >
          <p className="muted" style={{ lineHeight: 1.6 }}>
            {confirmTier === "PRODUCTION"
              ? "A Production Client ID is issued on the Production gateway. Information Security sign-off must already be on file."
              : "Every Production key for this partner is revoked immediately. Sandbox access is unaffected."}
          </p>
        </Modal>
      ) : null}
    </div>
  );
}

function EnvRow({ env, clientId, provisioned, onGenerate, busy, rotating, disabled }: {
  env: Env; clientId: string | null; provisioned: boolean; onGenerate: () => void; busy: boolean; rotating: boolean; disabled: boolean;
}) {
  return (
    <div style={{ padding: "10px 0", borderTop: env === "PRODUCTION" ? "1px solid var(--border-row)" : undefined }}>
      <div className="row" style={{ gap: 7, marginBottom: 5 }}>
        <Chip tone={env === "PRODUCTION" ? (provisioned ? "ok" : "neutral") : "info"}>{env === "SANDBOX" ? "UAT / SANDBOX" : "PRODUCTION"}</Chip>
        <span className="grow" />
        <button className="btn btn-sm" disabled={!provisioned || busy || rotating || disabled} onClick={onGenerate}
          title={rotating ? "A rotation is in progress — wait for the previous key to expire" : undefined}>
          Generate key
        </button>
      </div>
      <div className="mono" style={{ fontSize: 11.5, color: provisioned ? "var(--text-2)" : "var(--text-4)" }}>
        {provisioned ? clientId : "Not provisioned"}
      </div>
    </div>
  );
}
