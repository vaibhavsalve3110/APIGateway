import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError, Chip, CopyButton, ErrorBanner, Field, formatDateTime, GeneratedKeyModal, IssuedCredentialsModal, KeyTable,
  Modal, StatusChip, useAuth,
  type AccessTier, type Env, type GeneratedKey, type IssuedCredentials, type KeyView, type PartnerUserView,
  type PartnerView, type RevealedSalt,
} from "@apigw/ui";

/** One partner: access tier, Client IDs and security keys (designs: Partners + SecurityKeys artboards). */
export function PartnerDetailPage() {
  const { id = "" } = useParams();
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const [generated, setGenerated] = useState<GeneratedKey | null>(null);
  const [confirmTier, setConfirmTier] = useState<AccessTier | null>(null);
  const [issued, setIssued] = useState<IssuedCredentials | null>(null);
  const [confirmReissue, setConfirmReissue] = useState<"signature" | "salt" | null>(null);
  const [revealed, setRevealed] = useState<RevealedSalt | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmKey, setConfirmKey] = useState<Env | null>(null);

  const partner = useQuery({ queryKey: ["partner", id], queryFn: () => api.get<PartnerView>(`/api/admin/partners/${id}`) });
  const portalUsers = useQuery({
    queryKey: ["partner-users", id],
    queryFn: () => api.get<PartnerUserView[]>(`/api/admin/partners/${id}/users`),
  });
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
    onSuccess: (g) => { setConfirmKey(null); setGenerated(g); refresh(); },
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
  const reissue = useMutation({
    mutationFn: (kind: "signature" | "salt") =>
      api.post<IssuedCredentials>(`/api/admin/partners/${id}/${kind === "signature" ? "signature" : "ipv-salt"}`),
    onSuccess: (result) => { setConfirmReissue(null); setIssued(result); refresh(); },
  });
  const revealSalt = useMutation({
    mutationFn: () => api.post<RevealedSalt>(`/api/admin/partners/${id}/ipv-salt/reveal`),
    onSuccess: setRevealed,
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
        <button className="btn" onClick={() => setEditing(true)}>Edit details</button>
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
          <EnvRow env="SANDBOX" clientId={p.clientIdSandbox} provisioned onGenerate={() => setConfirmKey("SANDBOX")}
            busy={generate.isPending} rotating={rotating.has("SANDBOX")} disabled={p.status !== "ACTIVE"} />
          <EnvRow env="PRODUCTION" clientId={p.clientIdProduction} provisioned={p.accessTier === "PRODUCTION"}
            onGenerate={() => setConfirmKey("PRODUCTION")} busy={generate.isPending} rotating={rotating.has("PRODUCTION")}
            disabled={p.status !== "ACTIVE"} />
          <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>Rate limits are counted per Client ID, so a partner's two keys share one allowance.</p>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">Organization credentials</div>
            <div className="card-sub">
              Used by every user of this organization. The private signature key is shown once, when it is created.
            </div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn btn-sm" onClick={() => setConfirmReissue("signature")}>Recreate keys</button>
            <button className="btn btn-sm" onClick={() => setConfirmReissue("salt")}>Rotate salt</button>
            <button className="btn btn-sm" disabled={revealSalt.isPending} onClick={() => revealSalt.mutate()}>Show salt</button>
          </div>
        </div>
        <div className="row" style={{ gap: 26, padding: "14px 16px", flexWrap: "wrap" }}>
          <div>
            <div className="label">Signature key fingerprint</div>
            <div className="mono" style={{ fontSize: 11.5, wordBreak: "break-all", marginTop: 3 }}>
              {p.signatureFingerprint ?? "—"}
            </div>
            <div className="cell-sub">
              {p.signatureAlgorithm ?? "not issued"}{p.signatureCreatedAt ? ` · issued ${formatDateTime(p.signatureCreatedAt)}` : ""}
            </div>
          </div>
          <div>
            <div className="label">IPV salt</div>
            <div className="mono" style={{ fontSize: 11.5, marginTop: 3 }}>{p.ipvSaltMasked ?? "—"}</div>
            <div className="cell-sub">{p.ipvSaltCreatedAt ? `issued ${formatDateTime(p.ipvSaltCreatedAt)}` : "not issued"}</div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">Developer Portal users</div>
            <div className="card-sub">
              {portalUsers.data === undefined ? "Loading…"
                : `${portalUsers.data.length} account${portalUsers.data.length === 1 ? "" : "s"}, ${portalUsers.data.filter((u) => u.status === "ACTIVE").length} with access — they share the organization credentials above.`}
            </div>
          </div>
          <Link className="btn" to={`/partner-users?partnerId=${id}`}>Manage users</Link>
        </div>
        {portalUsers.data && portalUsers.data.length > 0 ? (
          <table className="table">
            <thead><tr><th style={{ width: "36%" }}>User</th><th>Role</th><th>Access</th><th>Added</th></tr></thead>
            <tbody>
              {portalUsers.data.map((u) => (
                <tr key={u.id}>
                  <td><div className="cell-title">{u.fullName}</div><div className="cell-sub">{u.email}</div></td>
                  <td style={{ fontSize: 12.5 }}>{u.role.replace("PARTNER_", "").toLowerCase()}</td>
                  <td><StatusChip status={u.status === "ACTIVE" ? "ACTIVE" : "REVOKED"} /></td>
                  <td className="muted nowrap" style={{ fontSize: 12 }}>{formatDateTime(u.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : portalUsers.data ? (
          <div className="empty">No Developer Portal users yet for this partner.</div>
        ) : null}
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
      {confirmKey ? (
        <Modal
          title={`Create a new ${confirmKey.toLowerCase()} key for ${p.name}?`}
          onClose={() => setConfirmKey(null)}
          footer={<>
            <button className="btn" onClick={() => setConfirmKey(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={generate.isPending} onClick={() => generate.mutate(confirmKey)}>
              {generate.isPending ? "Creating…" : "Create key"}
            </button>
          </>}
        >
          <ErrorBanner error={generate.error} />
          <p className="muted" style={{ lineHeight: 1.6 }}>
            The partner's current {confirmKey.toLowerCase()} key keeps working for 20 minutes after this, then stops.
            Anything they have not switched over by then starts failing, so agree the timing with them first.
          </p>
          <div className="banner banner-warn" style={{ fontSize: 12.5 }}>
            {p.name}'s Partner Admins are e-mailed the new key, all their portal users are told it changed, and the
            APIM Admin team is notified.
          </div>
        </Modal>
      ) : null}
      {issued ? <IssuedCredentialsModal issued={issued} onClose={() => setIssued(null)} /> : null}
      {editing ? <EditOrganizationModal partner={p} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); refresh(); }} /> : null}
      {revealed ? (
        <Modal title={`IPV salt — ${p.name}`} onClose={() => setRevealed(null)}
          footer={<button className="btn btn-primary" onClick={() => setRevealed(null)}>Close</button>}>
          <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
            Issued {formatDateTime(revealed.createdAt)}. This reveal is recorded in the audit log against your user.
          </p>
          <div className="secret">{revealed.ipvSalt}</div>
          <div className="row"><CopyButton value={revealed.ipvSalt} label="Copy salt" /></div>
        </Modal>
      ) : null}
      {confirmReissue ? (
        <Modal
          title={confirmReissue === "signature" ? "Recreate the signature key pair?" : "Rotate the IPV salt?"}
          onClose={() => setConfirmReissue(null)}
          footer={<>
            <button className="btn" onClick={() => setConfirmReissue(null)}>Cancel</button>
            <button className="btn btn-danger" disabled={reissue.isPending} onClick={() => reissue.mutate(confirmReissue)}>
              {reissue.isPending ? "Working…" : confirmReissue === "signature" ? "Recreate keys" : "Rotate salt"}
            </button>
          </>}
        >
          <ErrorBanner error={reissue.error} />
          <p className="muted" style={{ lineHeight: 1.6 }}>
            {confirmReissue === "signature"
              ? `Every user of ${p.name} signs with this key pair. The current public key (${p.signatureFingerprint ?? "none"}) stops being accepted immediately, so the organization must install the new private key first.`
              : `The current salt (${p.ipvSaltMasked ?? "none"}) stops working immediately and the organization must update its configuration.`}
          </p>
          <div className="banner banner-warn" style={{ fontSize: 12.5 }}>
            There is no overlap period for this material — plan it with the organization first.
          </div>
        </Modal>
      ) : null}
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

/** CP-PTN-02: correct the organization's name or contact address after registration. */
function EditOrganizationModal({ partner, onClose, onSaved }: {
  partner: PartnerView;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { api } = useAuth();
  const [name, setName] = useState(partner.name);
  const [contactEmail, setContactEmail] = useState(partner.contactEmail ?? "");
  const save = useMutation({
    mutationFn: () => api.put<PartnerView>(`/api/admin/partners/${partner.id}`, {
      name, contactEmail: contactEmail.trim() || null,
    }),
    onSuccess: onSaved,
  });
  const fieldError = (field: string) => (save.error instanceof ApiError ? save.error.fields[field] : undefined);

  return (
    <Modal
      title={`Edit ${partner.code}`}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={save.isPending || !name.trim()} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
      </>}
    >
      {save.error && !(save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED")
        ? <ErrorBanner error={save.error} /> : null}
      <div className="form-grid">
        <Field label="Organization name" error={fieldError("name")} className="span-2">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Contact email" error={fieldError("contactEmail")} className="span-2">
          <input className="input" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
        </Field>
      </div>
      <p className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
        This is the organization's own contact address, used for notices. It is not a portal sign-in — those are the
        partner users, each with their own email.
      </p>
    </Modal>
  );
}
