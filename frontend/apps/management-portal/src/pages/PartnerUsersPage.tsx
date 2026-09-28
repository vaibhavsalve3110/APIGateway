import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import {
  ApiError, Chip, ErrorBanner, Field, formatDateTime, Modal, PageHeader, StatusChip, useAuth,
  type PartnerUserRole, type PartnerUserView, type PartnerView, type RecordStatus,
} from "@apigw/ui";

const ROLE_LABEL: Record<PartnerUserRole, string> = {
  PARTNER_ADMIN: "Partner Admin",
  PARTNER_DEVELOPER: "Developer",
  PARTNER_VIEWER: "Viewer",
};

const ROLE_HELP: Record<PartnerUserRole, string> = {
  PARTNER_ADMIN: "Reads documentation and generates or rotates the organization's security keys.",
  PARTNER_DEVELOPER: "Reads documentation and runs Sandbox tests; cannot generate keys.",
  PARTNER_VIEWER: "Read-only access to documentation and usage.",
};

/**
 * Developer Portal logins, grouped by organization (BRD CP-PTN-04). An organization may have as many users
 * as it needs; the signature key pair and IPV salt belong to the organization, on its own page.
 */
export function PartnerUsersPage() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const partnerFilter = params.get("partnerId") ?? "";
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<PartnerUserView | null>(null);
  const [deleting, setDeleting] = useState<PartnerUserView | null>(null);

  const users = useQuery({
    queryKey: ["partner-users", partnerFilter],
    queryFn: () => api.get<PartnerUserView[]>(`/api/admin/partner-users${partnerFilter ? `?partnerId=${partnerFilter}` : ""}`),
  });
  const partners = useQuery({ queryKey: ["partners"], queryFn: () => api.get<PartnerView[]>("/api/admin/partners") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["partner-users"] });

  const setAccess = useMutation({
    mutationFn: (u: PartnerUserView) =>
      api.post<PartnerUserView>(`/api/admin/partner-users/${u.id}/access`,
        { status: (u.status === "ACTIVE" ? "DISABLED" : "ACTIVE") satisfies RecordStatus }),
    onSuccess: refresh,
  });

  const q = query.trim().toLowerCase();
  const rows = (users.data ?? []).filter(
    (u) => !q || `${u.fullName} ${u.email} ${u.partnerName} ${u.partnerCode}`.toLowerCase().includes(q));
  const activeCount = useMemo(() => (users.data ?? []).filter((u) => u.status === "ACTIVE").length, [users.data]);

  return (
    <div className="page">
      <PageHeader
        title="Partner users"
        subtitle={`${users.data?.length ?? 0} Developer Portal logins · ${activeCount} with access · signature keys and the IPV salt belong to the organization`}
        actions={<button className="btn btn-primary" onClick={() => setAdding(true)}>+ Add partner user</button>}
      />
      <ErrorBanner error={users.error ?? setAccess.error} />

      <div className="card">
        <div className="tabs" style={{ gap: 10 }}>
          <select
            className="select"
            style={{ width: 260, margin: "9px 0" }}
            value={partnerFilter}
            onChange={(e) => setParams(e.target.value ? { partnerId: e.target.value } : {})}
          >
            <option value="">All organizations</option>
            {(partners.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
          </select>
          <div className="grow" />
          <input className="input" style={{ width: 260, margin: "9px 0" }} placeholder="Search name, email or organization"
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>

        {users.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? (
          <div className="empty">No portal users yet. Add one so the organization can sign in to the Developer Portal.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: "26%" }}>User</th><th>Organization</th><th>Role</th><th>Access</th>
                <th>Added</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="cell-title">{u.fullName}</div>
                    <div className="cell-sub">{u.email}</div>
                  </td>
                  <td>
                    <Link to={`/partners/${u.partnerId}`} style={{ fontSize: 12.5 }}>{u.partnerName}</Link>
                    <div className="cell-sub">{u.partnerCode}</div>
                  </td>
                  <td><Chip tone={u.role === "PARTNER_ADMIN" ? "info" : "neutral"}>{ROLE_LABEL[u.role]}</Chip></td>
                  <td><StatusChip status={u.status === "ACTIVE" ? "ACTIVE" : "REVOKED"} /></td>
                  <td className="muted nowrap" style={{ fontSize: 12 }}>{formatDateTime(u.createdAt)}</td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <button className="btn btn-sm" onClick={() => setEditing(u)}>Edit</button>
                      <button className="btn btn-sm" disabled={setAccess.isPending} onClick={() => setAccess.mutate(u)}>
                        {u.status === "ACTIVE" ? "Revoke access" : "Grant access"}
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        disabled={u.status === "ACTIVE"}
                        title={u.status === "ACTIVE" ? "Revoke this user's access before deleting the account" : undefined}
                        onClick={() => setDeleting(u)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12, maxWidth: 800, lineHeight: 1.6 }}>
        A user's email address is their Developer Portal sign-in and can be corrected at any time; it must stay unique
        across all organizations. Adding, editing or revoking a user never changes the organization's signature key
        pair or IPV salt — those are managed on the organization's own page.
      </p>

      {adding ? (
        <AddUserModal
          partners={partners.data ?? []}
          presetPartnerId={partnerFilter || null}
          onClose={() => setAdding(false)}
          onCreated={() => { setAdding(false); refresh(); }}
        />
      ) : null}
      {editing ? <EditUserModal user={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} /> : null}
      {deleting ? <DeleteUserModal user={deleting} onClose={() => setDeleting(null)} onDeleted={() => { setDeleting(null); refresh(); }} /> : null}
    </div>
  );
}

/** Deletion is permanent and only offered once access has been revoked (the backend enforces the same rule). */
function DeleteUserModal({ user, onClose, onDeleted }: {
  user: PartnerUserView;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { api } = useAuth();
  const remove = useMutation({
    mutationFn: () => api.del(`/api/admin/partner-users/${user.id}`),
    onSuccess: onDeleted,
  });

  return (
    <Modal
      title={`Delete ${user.fullName}?`}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          {remove.isPending ? "Deleting…" : "Delete user"}
        </button>
      </>}
    >
      <ErrorBanner error={remove.error} />
      <p className="muted" style={{ lineHeight: 1.6 }}>
        <span className="mono">{user.email}</span> can no longer sign in to the Developer Portal, and the address becomes
        free for a new account. {user.partnerName}'s security keys, signature key pair and IPV salt are untouched —
        they belong to the organization, not to this user.
      </p>
      <div className="banner banner-info" style={{ fontSize: 12.5 }}>
        What this user did stays in the audit log; only the login is removed.
      </div>
    </Modal>
  );
}

function RoleField({ value, onChange }: { value: PartnerUserRole; onChange: (r: PartnerUserRole) => void }) {
  return (
    <Field label="Role in the Developer Portal" className="span-2">
      <select className="select" value={value} onChange={(e) => onChange(e.target.value as PartnerUserRole)}>
        {(Object.keys(ROLE_LABEL) as PartnerUserRole[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
      </select>
      <span className="muted" style={{ fontSize: 11.5 }}>{ROLE_HELP[value]}</span>
    </Field>
  );
}

function AddUserModal({ partners, presetPartnerId, onClose, onCreated }: {
  partners: PartnerView[];
  presetPartnerId: string | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { api } = useAuth();
  const [partnerId, setPartnerId] = useState(presetPartnerId ?? partners[0]?.id ?? "");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<PartnerUserRole>("PARTNER_ADMIN");

  const create = useMutation({
    mutationFn: () => api.post<PartnerUserView>(`/api/admin/partners/${partnerId}/users`, { fullName, email, role }),
    onSuccess: onCreated,
  });
  const fieldError = (name: string) => (create.error instanceof ApiError ? create.error.fields[name] : undefined);

  return (
    <Modal
      title="Add partner user"
      width={620}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!partnerId || !fullName.trim() || !email.trim() || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? "Adding…" : "Add user"}
        </button>
      </>}
    >
      {create.error && !(create.error instanceof ApiError && create.error.code === "VALIDATION_FAILED")
        ? <ErrorBanner error={create.error} /> : null}
      <div className="form-grid">
        <Field label="Organization" className="span-2">
          <select className="select" value={partnerId} disabled={!!presetPartnerId} onChange={(e) => setPartnerId(e.target.value)}>
            {partners.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
          </select>
        </Field>
        <Field label="Full name" error={fieldError("fullName")}>
          <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label="Email (Developer Portal sign-in)" error={fieldError("email")}>
          <input className="input" type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <RoleField value={role} onChange={setRole} />
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        The user signs in with this email and shares the organization's signature key pair and IPV salt.
      </p>
    </Modal>
  );
}

function EditUserModal({ user, onClose, onSaved }: { user: PartnerUserView; onClose: () => void; onSaved: () => void }) {
  const { api } = useAuth();
  const [fullName, setFullName] = useState(user.fullName);
  const [email, setEmail] = useState(user.email);
  const [role, setRole] = useState<PartnerUserRole>(user.role);
  const save = useMutation({
    mutationFn: () => api.put<PartnerUserView>(`/api/admin/partner-users/${user.id}`, { fullName, email, role }),
    onSuccess: onSaved,
  });
  const fieldError = (name: string) => (save.error instanceof ApiError ? save.error.fields[name] : undefined);
  const emailChanged = email.trim().toLowerCase() !== user.email;

  return (
    <Modal
      title={`Edit ${user.fullName}`}
      width={620}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={save.isPending || !fullName.trim() || !email.trim()} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
      </>}
    >
      {save.error && !(save.error instanceof ApiError && save.error.code === "VALIDATION_FAILED")
        ? <ErrorBanner error={save.error} /> : null}
      <div className="form-grid">
        <Field label="Full name" error={fieldError("fullName")}>
          <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label="Email (Developer Portal sign-in)" error={fieldError("email")}>
          <input className="input" type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <RoleField value={role} onChange={setRole} />
      </div>
      {emailChanged ? (
        <div className="banner banner-warn" style={{ fontSize: 12.5 }}>
          The sign-in address changes to <span className="mono">{email.trim().toLowerCase()}</span>. Tell the user before
          saving — the one-time code is sent to the new address from then on.
        </div>
      ) : (
        <p className="muted" style={{ fontSize: 12 }}>Organization: {user.partnerName} ({user.partnerCode}).</p>
      )}
    </Modal>
  );
}
