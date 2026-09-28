import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { AuthProvider, ComingSoon, SignInScreen } from "@apigw/ui";

import { Shell } from "./Shell";
import { ApiEditorPage } from "./pages/ApiEditorPage";
import { ApisPage } from "./pages/ApisPage";
import { ApiLogsPage } from "./pages/ApiLogsPage";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ErrorsPage } from "./pages/ErrorsPage";
import { PartnerDetailPage } from "./pages/PartnerDetailPage";
import { PartnersPage } from "./pages/PartnersPage";
import { PartnerUsersPage } from "./pages/PartnerUsersPage";
import { UsagePage } from "./pages/UsagePage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "logs", element: <ApiLogsPage /> },
      { path: "apis", element: <ApisPage /> },
      { path: "apis/new", element: <ApiEditorPage /> },
      { path: "apis/:id", element: <ApiEditorPage /> },
      { path: "partners", element: <PartnersPage /> },
      { path: "partners/:id", element: <PartnerDetailPage /> },
      { path: "partner-users", element: <PartnerUsersPage /> },
      { path: "usage", element: <UsagePage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "errors", element: <ErrorsPage /> },
      {
        path: "products",
        element: <ComingSoon title="Products & portal content" brdRefs="CP-API-09, CP-API-10"
          description="Bundle APIs into Products, and edit and publish Developer Portal pages." />,
      },
      // CP-API-06/07 now live on each API's page (Request / Responses tabs and Import).
      { path: "documentation", element: <Navigate to="/apis" replace /> },
      {
        path: "mapping",
        element: <ComingSoon title="Access mapping" brdRefs="CP-PTN-03, CP-RPT-06"
          description="Map Products or APIs to partner groups, with mandatory approval evidence before a mapping can be saved." />,
      },
      {
        path: "domains",
        element: <ComingSoon title="Domains" brdRefs="CP-DOM-01 to CP-DOM-10, GW-09"
          description="Register domains, verify ownership, bind TLS certificates and environments, and choose which APIs each domain exposes." />,
      },
      {
        path: "users",
        element: <ComingSoon title="Users & roles" brdRefs="CP-LOG-02"
          description="Internal users are managed in Keycloak for now; an in-portal user screen follows." />,
      },
    ],
  },
]);

export function App() {
  return (
    <AuthProvider
      allowedRoles={["ADMIN", "EDITOR"]}
      portalName="Management Portal"
      signIn={(props) => (
        <SignInScreen
          {...props}
          dark
          product="Management Portal"
          headline="One place to govern every API you expose."
          points={[
            "Sign in with a one-time code sent to your work e-mail — no passwords to steal",
            "Keys shown once and stored only as hashes, with a 20-minute rotation overlap",
            "Every configuration change audited with user, time and detail",
          ]}
        />
      )}
    >
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>
  );
}
