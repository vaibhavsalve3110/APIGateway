import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Chip, ErrorBanner, Field, Modal, PageHeader, StatusChip, useAuth } from "@apigw/ui";

/** A change waiting for, or decided by, an administrator. Mirrors ChangeRequestView. */
interface ChangeRequest {
  id: string;
  objectType: string;
  objectId: string | null;
  objectName: string | null;
  objectStatus: string | null;
  action: "PUBLISH" | "UPDATE" | "DISABLE";
  payload: Record<string, unknown> | null;
  summary: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN";
  requestedBy: string;
  requestedAt: string;
  decidedBy: string | null;
  decidedAt: string | null;
  decisionNote: string | null;
}

const ACTION_LABEL: Record<string, string> = {
  PUBLISH: "Publish",
  UPDATE: "Change a live API",
  DISABLE: "Withdraw from service",
};

const FILTERS = [
  { key: "PENDING", label: "Waiting" },
  { key: "", label: "All" },
  { key: "APPROVED", label: "Approved" },
  { key: "REJECTED", label: "Rejected" },
  { key: "WITHDRAWN", label: "Withdrawn" },
] as const;

function when(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The approvals queue (four-eyes).
 *
 * Publishing an API, changing one that is already live, and a developer withdrawing one all land
 * here instead of taking effect. An administrator decides — but never their own request, which is
 * the whole value of the step, so the buttons are hidden for those and the backend refuses them
 * regardless.
 */
export function ApprovalsPage() {
  const { api, user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user.roles.includes("ADMIN");
  const [filter, setFilter] = useState<string>("PENDING");
  const [deciding, setDeciding] = useState<{ request: ChangeRequest; verdict: "approve" | "reject" | "withdraw" } | null>(null);
  const [note, setNote] = useState("");

  const requests = useQuery({
    queryKey: ["change-requests", filter],
    queryFn: () => api.get<ChangeRequest[]>(`/api/admin/change-requests${filter ? `?status=${filter}` : ""}`),
  });

  const decide = useMutation({
    mutationFn: ({ request, verdict }: { request: ChangeRequest; verdict: string }) =>
      api.post<ChangeRequest>(`/api/admin/change-requests/${request.id}/${verdict}`, note.trim() ? { note: note.trim() } : {}),
    onSuccess: () => {
      // The APIs list and the API itself may both have changed, so neither is trustworthy now.
      queryClient.invalidateQueries({ queryKey: ["change-requests"] });
      queryClient.invalidateQueries({ queryKey: ["apis"] });
      queryClient.invalidateQueries({ queryKey: ["api"] });
      setDeciding(null);
      setNote("");
    },
  });

  const rows = requests.data ?? [];
  const waiting = rows.filter((r) => r.status === "PENDING").length;

  return (
    <div className="page">
      <PageHeader
        title="Approvals"
        subtitle={
          filter === "PENDING" && waiting > 0
            ? `${waiting} change${waiting === 1 ? "" : "s"} waiting for an administrator`
            : "Publishing an API, and changing one that is already live, needs a second pair of eyes"
        }
        actions={
          <div className="tabs">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                className={`tab${filter === f.key ? " active" : ""}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      />

      <ErrorBanner error={requests.error ?? decide.error} />

      {requests.isLoading ? (
        <div className="card pad">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card pad empty">
          {filter === "PENDING"
            ? "Nothing is waiting. A developer publishing an API, or changing a live one, will appear here."
            : "No requests to show."}
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>What</th>
                <th>API</th>
                <th>Requested by</th>
                <th>Raised</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((request) => {
                const mine = request.requestedBy === user.username;
                const canDecide = isAdmin && request.status === "PENDING" && !mine;
                const canWithdraw = request.status === "PENDING" && (mine || isAdmin);
                return (
                  <tr key={request.id}>
                    <td>
                      <div className="strong">{ACTION_LABEL[request.action] ?? request.action}</div>
                      <div className="muted small">{request.summary}</div>
                      {request.decisionNote ? (
                        <div className="muted small">Note: {request.decisionNote}</div>
                      ) : null}
                    </td>
                    <td>
                      <div>{request.objectName ?? <span className="muted">deleted</span>}</div>
                      {request.objectStatus ? <div className="muted small">{request.objectStatus.toLowerCase()}</div> : null}
                    </td>
                    <td>
                      {request.requestedBy}
                      {mine ? <> <Chip tone="neutral">you</Chip></> : null}
                      {request.decidedBy ? (
                        <div className="muted small">
                          {request.status === "APPROVED" ? "approved" : request.status === "REJECTED" ? "rejected" : "withdrawn"} by {request.decidedBy}
                        </div>
                      ) : null}
                    </td>
                    <td className="nowrap">{when(request.requestedAt)}</td>
                    <td><StatusChip status={request.status} /></td>
                    <td className="right nowrap">
                      {canDecide ? (
                        <>
                          <button className="btn btn-sm btn-primary" onClick={() => setDeciding({ request, verdict: "approve" })}>
                            Approve
                          </button>{" "}
                          <button className="btn btn-sm" onClick={() => setDeciding({ request, verdict: "reject" })}>
                            Reject
                          </button>
                        </>
                      ) : request.status === "PENDING" && mine && isAdmin ? (
                        // Explained rather than silently absent: an administrator looking at their
                        // own request needs to know why there is no Approve button.
                        <span className="muted small">Needs another admin</span>
                      ) : null}
                      {canWithdraw ? (
                        <>
                          {" "}
                          <button className="btn btn-sm" onClick={() => setDeciding({ request, verdict: "withdraw" })}>
                            Withdraw
                          </button>
                        </>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {deciding ? (
        <Modal
          title={
            deciding.verdict === "approve"
              ? "Approve this change"
              : deciding.verdict === "reject"
                ? "Reject this change"
                : "Withdraw this request"
          }
          onClose={() => { setDeciding(null); setNote(""); }}
          footer={
            <>
              <button className="btn" onClick={() => { setDeciding(null); setNote(""); }}>Cancel</button>
              <button
                className={`btn ${deciding.verdict === "approve" ? "btn-primary" : "btn-danger"}`}
                disabled={decide.isPending}
                onClick={() => decide.mutate({ request: deciding.request, verdict: deciding.verdict })}
              >
                {decide.isPending ? "Working…" : deciding.verdict === "approve" ? "Approve and apply" : deciding.verdict === "reject" ? "Reject" : "Withdraw"}
              </button>
            </>
          }
        >
          <p>{deciding.request.summary}</p>
          <p className="muted small">
            Raised by {deciding.request.requestedBy} on {when(deciding.request.requestedAt)}.
          </p>
          {deciding.verdict === "approve" ? (
            <p className="muted small">
              {deciding.request.action === "PUBLISH"
                ? "Approving puts this API's route on the gateways and makes it visible to partners."
                : deciding.request.action === "DISABLE"
                  ? "Approving removes this API's route from the gateways. Calls to it stop immediately."
                  : "Approving applies the proposed definition below and pushes it to the gateways."}
            </p>
          ) : null}
          {deciding.request.payload ? (
            <>
              <div className="muted small" style={{ marginTop: 10 }}>Proposed definition</div>
              <pre className="code">{JSON.stringify(deciding.request.payload, null, 2)}</pre>
            </>
          ) : null}
          <Field label="Note (optional)">
            <textarea
              className="textarea"
              rows={2}
              value={note}
              placeholder={deciding.verdict === "reject" ? "Why it is being rejected — the requester will see this" : "Recorded in the audit trail"}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        </Modal>
      ) : null}
    </div>
  );
}
