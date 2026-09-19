import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Chip, ErrorBanner, formatDateTime, Modal, PageHeader, StatusChip, Switch, useAuth,
  type ApiStatus, type ApiView,
} from "@apigw/ui";

type Tab = "ALL" | ApiStatus;

const METHOD_TONE: Record<string, "info" | "ok" | "warn" | "bad"> = { GET: "info", POST: "ok", PUT: "warn", PATCH: "warn", DELETE: "bad" };

/** API inventory (design: Main.dc.html; BRD CP-API-01..05, CP-API-08, CP-RPT-05). */
export function ApisPage() {
  const { api, user } = useAuth();
  const isAdmin = user.roles.includes("ADMIN");
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("ALL");
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const notice = (useLocation().state as { notice?: string } | null)?.notice;
  const [deleting, setDeleting] = useState<ApiView | null>(null);

  const apis = useQuery({ queryKey: ["apis"], queryFn: () => api.get<ApiView[]>("/api/admin/apis") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["apis"] });

  const toggleGuest = useMutation({
    mutationFn: (a: ApiView) => api.put<ApiView>(`/api/admin/apis/${a.id}/guest-visibility`, { visible: !a.guestVisible }),
    onSuccess: refresh,
  });
  const setStatus = useMutation({
    mutationFn: (a: ApiView) => api.post<ApiView>(`/api/admin/apis/${a.id}/${a.status === "DISABLED" ? "enable" : "disable"}`),
    onSuccess: refresh,
  });

  const all = apis.data ?? [];
  const counts = useMemo(() => ({
    ALL: all.length,
    ACTIVE: all.filter((a) => a.status === "ACTIVE").length,
    DISABLED: all.filter((a) => a.status === "DISABLED").length,
    DRAFT: all.filter((a) => a.status === "DRAFT").length,
  }), [all]);
  const q = query.trim().toLowerCase();
  const rows = all
    .filter((a) => tab === "ALL" || a.status === tab)
    .filter((a) => !q || `${a.name} ${a.proxyPath} ${a.category}`.toLowerCase().includes(q));

  return (
    <div className="page">
      <PageHeader
        title="APIs"
        subtitle={`${counts.ALL} APIs onboarded · ${counts.ACTIVE} active · ${all.filter((a) => a.guestVisible).length} visible to guest users`}
        actions={isAdmin ? <button className="btn btn-primary" onClick={() => navigate("/apis/new")}>+ Add API</button> : null}
      />
      {notice ? <div className="banner banner-ok">{notice}</div> : null}
      <ErrorBanner error={apis.error ?? toggleGuest.error ?? setStatus.error} />

      <div className="card">
        <div className="tabs">
          {(["ALL", "ACTIVE", "DISABLED", "DRAFT"] as Tab[]).map((t) => (
            <button key={t} className={`tab${tab === t ? " tab-active" : ""}`} onClick={() => setTab(t)}>
              {t === "ALL" ? "All APIs" : t.charAt(0) + t.slice(1).toLowerCase()} {counts[t]}
            </button>
          ))}
          <div className="grow" />
          <input className="input" style={{ width: 260, margin: "9px 0" }} placeholder="Search name, path or category"
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {apis.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? <div className="empty">No APIs match.</div> : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>API</th><th>Category</th><th>Method</th><th>Status</th><th>Guest</th>
                <th>Rate limit</th><th>Last updated</th>{isAdmin ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td><Link to={`/apis/${a.id}`} className="cell-title link">{a.name}</Link><div className="cell-sub">{a.proxyPath}</div></td>
                  <td>{a.category}</td>
                  <td><Chip tone={METHOD_TONE[a.httpMethod] ?? "info"}><span className="mono">{a.httpMethod}</span></Chip></td>
                  <td>
                    <StatusChip status={a.status} />
                    {a.status === "DISABLED" && a.deletableFrom ? (
                      <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>deletable {formatDateTime(a.deletableFrom)}</div>
                    ) : null}
                  </td>
                  <td>
                    <Switch on={a.guestVisible} label={`Visible to guest users: ${a.name}`} disabled={!isAdmin || toggleGuest.isPending}
                      onChange={() => toggleGuest.mutate(a)} />
                  </td>
                  <td className="mono nowrap" style={{ fontSize: 11.5 }}>{a.rateLimitCount.toLocaleString("en-IN")} / {a.rateLimitWindow.toLowerCase()}</td>
                  <td className="muted nowrap" style={{ fontSize: 12 }}>{formatDateTime(a.updatedAt)}</td>
                  {isAdmin ? (
                    <td>
                      <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                        <button className="btn btn-sm" onClick={() => navigate(`/apis/${a.id}`)}>Edit</button>
                        <button className="btn btn-sm" disabled={setStatus.isPending} onClick={() => setStatus.mutate(a)}>
                          {a.status === "DISABLED" ? "Enable" : "Disable"}
                        </button>
                        <button className="btn btn-sm btn-danger" onClick={() => setDeleting(a)}>Delete</button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {deleting ? <DeleteApiModal target={deleting} onClose={() => setDeleting(null)} onDeleted={refresh} /> : null}
    </div>
  );
}

/** CP-RPT-05: the backend refuses deletion inside the cooling period; the modal explains why. */
function DeleteApiModal({ target, onClose, onDeleted }: { target: ApiView; onClose: () => void; onDeleted: () => void }) {
  const { api } = useAuth();
  const remove = useMutation({
    mutationFn: () => api.del(`/api/admin/apis/${target.id}`),
    onSuccess: () => { onDeleted(); onClose(); },
  });
  const blockedUntil = target.status !== "DISABLED" ? null : target.deletableFrom;
  const eligible = target.status === "DISABLED" && blockedUntil != null && new Date(blockedUntil).getTime() <= Date.now();

  return (
    <Modal
      title={eligible ? "Delete this API permanently?" : "This API cannot be deleted yet"}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{eligible ? "Cancel" : "Close"}</button>
        {eligible ? (
          <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>Delete API</button>
        ) : null}
      </>}
    >
      <ErrorBanner error={remove.error} />
      <p className="muted" style={{ lineHeight: 1.6 }}>
        {target.status !== "DISABLED"
          ? "Disable the API first. It can be deleted once it has stayed disabled for the full cooling period (7 days by default)."
          : eligible
            ? "The cooling period has passed. Deleting removes the definition and its gateway routes."
            : "The API is inside its cooling period. Deletion is allowed from the date below."}
      </p>
      <div className="card" style={{ padding: "12px 14px", background: "var(--surface-muted)" }}>
        <div className="row" style={{ justifyContent: "space-between" }}><span className="muted">API</span><strong>{target.name}</strong></div>
        <div className="row" style={{ justifyContent: "space-between", marginTop: 6 }}><span className="muted">Disabled since</span><span className="mono">{formatDateTime(target.disabledAt)}</span></div>
        <div className="row" style={{ justifyContent: "space-between", marginTop: 6 }}><span className="muted">Deletable from</span><span className="mono">{formatDateTime(blockedUntil)}</span></div>
      </div>
    </Modal>
  );
}
