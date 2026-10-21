import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, Chip, ErrorBanner, Field, Modal, PageHeader, StatusChip, useAuth } from "@apigw/ui";

/** Someone who signs in to this portal. Mirrors PlatformUserView. */
interface PlatformUser {
  id: string;
  email: string;
  fullName: string;
  role: "ADMIN" | "DEVELOPER";
  status: "ACTIVE" | "DISABLED";
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  lastLoginAt: string | null;
}

const ROLE_HELP: Record<string, string> = {
  ADMIN: "Everything: approving changes, partners, Developer Portal users, and these accounts",
  DEVELOPER: "Drafts and edits APIs and reads the logs. Publishing needs an administrator's approval",
};

function when(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * APIM users and their roles (CP-LOG-02) — the people who can sign in to this portal.
 *
 * Distinct from Partner Users, who belong to an organization and use the Developer Portal. There is
 * no password to set: sign-in is a one-time code to the address, so adding someone here is all that
 * is needed for them to get in.
 */
export function PlatformUsersPage() {
  const { api, user: me } = useAuth();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<PlatformUser | null>(null);
  const [removing, setRemoving] = useState<PlatformUser | null>(null);
  const [form, setForm] = useState({ fullName: "", email: "", role: "DEVELOPER" as PlatformUser["role"] });

  const users = useQuery({
    queryKey: ["platform-users"],
    queryFn: () => api.get<PlatformUser[]>("/api/admin/platform-users"),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["platform-users"] });

  const create = useMutation({
    mutationFn: () => api.post<PlatformUser>("/api/admin/platform-users", {
      fullName: form.fullName.trim(),
      email: form.email.trim().toLowerCase(),
      role: form.role,
    }),
    onSuccess: () => { refresh(); setAdding(false); setForm({ fullName: "", email: "", role: "DEVELOPER" }); },
  });

  const update = useMutation({
    mutationFn: (next: PlatformUser) => api.put<PlatformUser>(`/api/admin/platform-users/${next.id}`, {
      fullName: next.fullName.trim(),
      email: next.email,
      role: next.role,
      status: next.status,
    }),
    onSuccess: () => { refresh(); setEditing(null); },
  });

  const setStatus = useMutation({
    mutationFn: ({ user, status }: { user: PlatformUser; status: PlatformUser["status"] }) =>
      api.put<PlatformUser>(`/api/admin/platform-users/${user.id}/status`, { status }),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (user: PlatformUser) => api.del(`/api/admin/platform-users/${user.id}`),
    onSuccess: () => { refresh(); setRemoving(null); },
  });

  const rows = users.data ?? [];
  const admins = rows.filter((u) => u.role === "ADMIN" && u.status === "ACTIVE").length;
  const fieldError = (name: string) =>
    create.error instanceof ApiError ? create.error.fields[name] : undefined;

  return (
    <div className="page">
      <PageHeader
        title="Users & roles"
        subtitle="Who can sign in to this portal, and what they are allowed to do"
        actions={<button className="btn btn-primary" onClick={() => setAdding(true)}>Add user</button>}
      />

      <ErrorBanner error={users.error ?? update.error ?? setStatus.error ?? remove.error} />

      {admins === 1 ? (
        <div className="card pad notice" style={{ marginBottom: 12 }}>
          There is only one active administrator. An approval has to come from a different
          administrator than the one who raised it, so <strong>nothing can be published</strong> until
          a second admin exists.
        </div>
      ) : null}

      {users.isLoading ? (
        <div className="card pad">Loading…</div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>E-mail</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last signed in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => {
                const isMe = user.email === me.username;
                return (
                  <tr key={user.id}>
                    <td>
                      <div className="strong">{user.fullName}</div>
                      <div className="muted small">added by {user.createdBy}</div>
                    </td>
                    <td className="mono">
                      {user.email}
                      {isMe ? <> <Chip tone="neutral">you</Chip></> : null}
                    </td>
                    <td>
                      <div>{user.role === "ADMIN" ? "Admin" : "Developer"}</div>
                      <div className="muted small">{ROLE_HELP[user.role]}</div>
                    </td>
                    <td><StatusChip status={user.status} /></td>
                    <td className="nowrap">{when(user.lastLoginAt)}</td>
                    <td className="right nowrap">
                      <button className="btn btn-sm" onClick={() => setEditing(user)}>Edit</button>{" "}
                      <button
                        className="btn btn-sm"
                        disabled={setStatus.isPending}
                        onClick={() => setStatus.mutate({ user, status: user.status === "ACTIVE" ? "DISABLED" : "ACTIVE" })}
                      >
                        {user.status === "ACTIVE" ? "Suspend" : "Reinstate"}
                      </button>{" "}
                      <button className="btn btn-sm btn-danger" onClick={() => setRemoving(user)}>Remove</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {adding ? (
        <Modal
          title="Add an APIM user"
          onClose={() => { setAdding(false); create.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setAdding(false); create.reset(); }}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={create.isPending || !form.fullName.trim() || !form.email.trim()}
                onClick={() => create.mutate()}
              >
                {create.isPending ? "Adding…" : "Add user"}
              </button>
            </>
          }
        >
          <ErrorBanner error={create.error} />
          <Field label="Full name" error={fieldError("fullName")}>
            <input className="input" value={form.fullName} onChange={(e) => setForm({ ...form, fullName: e.target.value })} />
          </Field>
          <Field label="Work e-mail" error={fieldError("email")}>
            <input className="input mono" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Role">
            <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as PlatformUser["role"] })}>
              <option value="DEVELOPER">Developer</option>
              <option value="ADMIN">Admin</option>
            </select>
          </Field>
          <p className="muted small">{ROLE_HELP[form.role]}</p>
          <p className="muted small">
            There is no password to set. They sign in with a one-time code sent to this address, so it
            has to be one they can read.
          </p>
        </Modal>
      ) : null}

      {editing ? (
        <Modal
          title={`Edit ${editing.fullName}`}
          onClose={() => { setEditing(null); update.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setEditing(null); update.reset(); }}>Cancel</button>
              <button className="btn btn-primary" disabled={update.isPending} onClick={() => update.mutate(editing)}>
                {update.isPending ? "Saving…" : "Save"}
              </button>
            </>
          }
        >
          <ErrorBanner error={update.error} />
          <Field label="Full name">
            <input className="input" value={editing.fullName} onChange={(e) => setEditing({ ...editing, fullName: e.target.value })} />
          </Field>
          <Field label="E-mail">
            <input className="input mono" value={editing.email} disabled />
          </Field>
          <p className="muted small">
            The address is the identity the audit trail and the sign-in codes are keyed on, so it
            cannot be changed. A different address is a different person.
          </p>
          <Field label="Role">
            <select
              className="select"
              value={editing.role}
              onChange={(e) => setEditing({ ...editing, role: e.target.value as PlatformUser["role"] })}
            >
              <option value="DEVELOPER">Developer</option>
              <option value="ADMIN">Admin</option>
            </select>
          </Field>
          <p className="muted small">{ROLE_HELP[editing.role]}</p>
          {editing.email === me.username && editing.role !== "ADMIN" ? (
            <p className="notice small">
              This is your own account. Making yourself a Developer will take away your access to
              this screen.
            </p>
          ) : null}
        </Modal>
      ) : null}

      {removing ? (
        <Modal
          title={`Remove ${removing.fullName}?`}
          onClose={() => { setRemoving(null); remove.reset(); }}
          footer={
            <>
              <button className="btn" onClick={() => { setRemoving(null); remove.reset(); }}>Cancel</button>
              <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate(removing)}>
                {remove.isPending ? "Removing…" : "Remove"}
              </button>
            </>
          }
        >
          <ErrorBanner error={remove.error} />
          <p>
            {removing.email} will no longer be able to sign in. What they have already done stays in
            the audit trail, which is keyed on the address.
          </p>
          <p className="muted small">Suspending them instead keeps the account and can be undone.</p>
        </Modal>
      ) : null}
    </div>
  );
}
