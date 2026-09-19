import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Countdown, ErrorBanner, GeneratedKeyModal, KeyTable, Modal, PageHeader, useAuth,
  type Env, type GeneratedKey, type KeyView,
} from "@apigw/ui";

import { usePartner } from "../usePartner";

/**
 * My security keys (design: DevKeys.dc.html; BRD v1.3 DP-04, DP-05). Keys are never viewable after creation;
 * a new key keeps the previous one alive for 20 minutes, and no further key can be made inside that window.
 */
export function KeysPage() {
  const { api } = useAuth();
  const me = usePartner();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<Env | null>(null);
  const [generated, setGenerated] = useState<GeneratedKey | null>(null);

  const keys = useQuery({
    queryKey: ["my-keys"],
    queryFn: () => api.get<KeyView[]>("/api/partner/keys"),
    refetchInterval: 15_000,
  });
  const generate = useMutation({
    mutationFn: (env: Env) => api.post<GeneratedKey>(`/api/partner/keys/${env}`),
    onSuccess: (g) => {
      setConfirm(null);
      setGenerated(g);
      void queryClient.invalidateQueries({ queryKey: ["my-keys"] });
    },
  });

  const all = keys.data ?? [];
  const expiring = all.filter((k) => k.status === "EXPIRING");
  const hasLive = (env: Env) => all.some((k) => k.environment === env && (k.status === "ACTIVE" || k.status === "EXPIRING"));
  const envs: Env[] = me.data?.accessTier === "PRODUCTION" ? ["SANDBOX", "PRODUCTION"] : ["SANDBOX"];

  return (
    <div className="page" style={{ padding: "26px 30px 34px" }}>
      <PageHeader
        title="Security keys"
        subtitle="Your key identifies your organisation at the gateway on every call. It is shown once, when you create it — store it in your secret manager straight away."
      />
      <ErrorBanner error={keys.error ?? me.error} />

      {expiring.map((k) => (
        <div key={k.id} className="banner banner-info">
          <span>
            <strong>Rotation in progress ({k.environment.toLowerCase()}).</strong> Your previous key {k.maskedKey} keeps working for{" "}
            <strong><Countdown until={k.expiresAt} /></strong>. Move every system to the new key before it expires — a new key cannot be created until then.
          </span>
        </div>
      ))}

      <div className="row" style={{ gap: 16, alignItems: "stretch" }}>
        {envs.map((env) => {
          const rotating = expiring.some((k) => k.environment === env);
          return (
            <div key={env} className="card grow" style={{ padding: "16px 18px" }}>
              <div className="card-title">{env === "SANDBOX" ? "Sandbox (UAT)" : "Production"}</div>
              <p className="muted mono" style={{ fontSize: 11.5, margin: "4px 0 12px" }}>
                Client ID {env === "SANDBOX" ? me.data?.clientIdSandbox : me.data?.clientIdProduction}
              </p>
              <button className="btn btn-primary" disabled={rotating || generate.isPending} onClick={() => setConfirm(env)}>
                {hasLive(env) ? "Create a new key" : "Create my first key"}
              </button>
            </div>
          );
        })}
        {me.data?.accessTier !== "PRODUCTION" ? (
          <div className="card grow" style={{ padding: "16px 18px", background: "var(--surface-muted)" }}>
            <div className="card-title muted">Production — not provisioned</div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>
              A Production key is issued once your account moves to the Production access tier. Until then, Production endpoints
              reject your Sandbox key.
            </p>
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">Your keys</div>
            <div className="card-sub">Masked — the full value cannot be retrieved by anyone after creation. Lost a key? Create a new one.</div>
          </div>
        </div>
        {keys.isLoading ? <div className="empty">Loading…</div> : <KeyTable keys={all} />}
      </div>

      {confirm ? (
        <Modal
          title={`Create a new ${confirm === "SANDBOX" ? "Sandbox" : "Production"} key?`}
          onClose={() => setConfirm(null)}
          footer={<>
            <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={generate.isPending} onClick={() => generate.mutate(confirm)}>
              {generate.isPending ? "Creating…" : "Create key"}
            </button>
          </>}
        >
          <ErrorBanner error={generate.error} />
          <p className="muted" style={{ lineHeight: 1.6 }}>
            {hasLive(confirm)
              ? "Your current key will keep working for 20 minutes after the new one is created, then it stops. Make sure every system that calls the gateway can be switched to the new key within that time."
              : "The key is shown once, on the next screen. Have your secret manager ready."}
          </p>
        </Modal>
      ) : null}
      {generated ? <GeneratedKeyModal generated={generated} onClose={() => setGenerated(null)} /> : null}
    </div>
  );
}
