import type { ReactNode } from "react";

import { PageHeader, useAuth } from "@apigw/ui";

/**
 * Hides a screen from anyone who is not an APIM Admin.
 *
 * The navigation already leaves these out for a developer, but a bookmark, a shared link or a typed
 * URL gets past that. The backend refuses every call behind these screens regardless — this exists
 * so the answer is a sentence rather than a page of failed requests.
 */
export function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user.roles.includes("ADMIN")) {
    return <>{children}</>;
  }
  return (
    <div className="page">
      <PageHeader
        title="Administrators only"
        subtitle="Your account has the Developer role"
      />
      <div className="card pad">
        <p>
          This screen is limited to APIM Admins. As a Developer you can draft and edit APIs, raise
          them for publishing, and read every log and report.
        </p>
        <p className="muted small">
          If you need access to this, ask an APIM Admin to change your role under Users &amp; roles.
        </p>
      </div>
    </div>
  );
}
