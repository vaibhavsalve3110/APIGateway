import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError, Chip, ErrorBanner, Field, IssuedCredentialsModal, Modal, PageHeader, StatusChip, useAuth,
  type GroupView, type IssuedCredentials, type PartnerView,
} from "@apigw/ui";

/** Groups & partners (design: Partners.dc.html; BRD CP-PTN-01, CP-PTN-02, CP-PTN-07). */
export function PartnersPage() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const [group, setGroup] = useState<string | "ALL">("ALL");
  const [adding, setAdding] = useState<"partner" | "group" | null>(null);
  const [issued, setIssued] = useState<IssuedCredentials | null>(null);

  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api.get<GroupView[]>("/api/admin/partner-groups") });
  const partners = useQuery({ queryKey: ["partners"], queryFn: () => api.get<PartnerView[]>("/api/admin/partners") });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["groups"] });
    void queryClient.invalidateQueries({ queryKey: ["partners"] });
  };
  const rows = (partners.data ?? []).filter((p) => group === "ALL" || p.groupId === group);

  return (
    <div className="page">
      <PageHeader
        title="Groups & Partners"
        subtitle="Access tier decides which gateways a partner has a Client ID on. UAT-only partners can never reach Production."
        actions={<>
          <button className="btn" onClick={() => setAdding("group")}>New partner group</button>
          <button className="btn btn-primary" disabled={(groups.data ?? []).length === 0} onClick={() => setAdding("partner")}>+ Add partner</button>
        </>}
      />
      <ErrorBanner error={groups.error ?? partners.error} />

      <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
        <div className="card" style={{ width: 260, flexShrink: 0, padding: 8 }}>
          <div className="label" style={{ padding: "6px 8px 8px" }}>Partner groups</div>
          <GroupButton active={group === "ALL"} onClick={() => setGroup("ALL")} label="All partners" count={(partners.data ?? []).length} />
          {(groups.data ?? []).map((g) => (
            <GroupButton key={g.id} active={group === g.id} onClick={() => setGroup(g.id)} label={g.name} count={g.partnerCount} />
          ))}
        </div>

        <div className="card grow">
          {partners.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? <div className="empty">No partners in this group yet.</div> : (
            <table className="table">
              <thead>
                <tr><th>Partner</th><th>Group</th><th>Access tier</th><th>Client IDs</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td><div className="cell-title">{p.name}</div><div className="cell-sub">{p.code}</div></td>
                    <td style={{ fontSize: 12 }}>{p.groupName}</td>
                    <td><Chip tone={p.accessTier === "PRODUCTION" ? "ok" : "info"}>{p.accessTier === "PRODUCTION" ? "PROD + UAT" : "UAT ONLY"}</Chip></td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      <div>{p.clientIdSandbox}</div>
                      {p.clientIdProduction ? <div className="muted">{p.clientIdProduction}</div> : null}
                    </td>
                    <td><StatusChip status={p.status} /></td>
                    <td style={{ textAlign: "right" }}><Link className="btn btn-sm" to={`/partners/${p.id}`}>Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {issued ? <IssuedCredentialsModal issued={issued} onClose={() => setIssued(null)} /> : null}
      {adding === "group" ? <GroupModal onClose={() => setAdding(null)} onSaved={refresh} /> : null}
      {adding === "partner" ? (
        <PartnerModal onRegistered={setIssued} groups={groups.data ?? []} defaultGroup={group === "ALL" ? undefined : group}
          onClose={() => setAdding(null)} onSaved={refresh} />
      ) : null}
    </div>
  );
}

function GroupButton({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count: number }) {
  return (
    <button onClick={onClick} className="row" style={{
      width: "100%", padding: "7px 9px", borderRadius: 5, gap: 8, fontSize: 12.5,
      background: active ? "#eef3fb" : undefined, fontWeight: active ? 600 : 500,
    }}>
      <span className="grow" style={{ textAlign: "left" }}>{label}</span>
      <Chip>{count}</Chip>
    </button>
  );
}

function GroupModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { api } = useAuth();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<GroupView>("/api/admin/partner-groups", { name, description }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  return (
    <Modal title="New partner group" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>Create group</button>
    </>}>
      <ErrorBanner error={save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED" ? null : save.error} />
      <Field label="Group name" error={save.error instanceof ApiError ? save.error.fields.name : undefined}>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Description">
        <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
    </Modal>
  );
}

function PartnerModal({ groups, defaultGroup, onClose, onSaved, onRegistered }: {
  onRegistered: (issued: IssuedCredentials) => void;
  groups: GroupView[]; defaultGroup?: string; onClose: () => void; onSaved: () => void;
}) {
  const { api } = useAuth();
  const [name, setName] = useState("");
  const [groupId, setGroupId] = useState(defaultGroup ?? groups[0]?.id ?? "");
  const [contactEmail, setContactEmail] = useState("");
  // Registering an organization issues its signature key pair and IPV salt, shown once.
  const save = useMutation({
    mutationFn: () => api.post<IssuedCredentials>("/api/admin/partners", { name, groupId, contactEmail: contactEmail || null }),
    onSuccess: (result) => { onSaved(); onClose(); onRegistered(result); },
  });
  const fields = save.error instanceof ApiError ? save.error.fields : {};
  return (
    <Modal title="Add partner" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>Add partner</button>
    </>}>
      <ErrorBanner error={save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED" ? null : save.error} />
      <Field label="Organisation name" error={fields.name}>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Partner group" error={fields.groupId}>
        <select className="select" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
      </Field>
      <Field label="Integration contact e-mail" error={fields.contactEmail}>
        <input className="input" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
      </Field>
      <div className="banner banner-info">
        New partners start on the UAT-only tier with a sandbox Client ID. Grant Production access from the partner's page.
      </div>
    </Modal>
  );
}
