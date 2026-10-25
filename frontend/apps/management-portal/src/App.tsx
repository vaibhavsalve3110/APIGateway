import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { AuthProvider, ComingSoon, SignInScreen } from "@apigw/ui";

import { AdminOnly } from "./AdminOnly";
import { Shell } from "./Shell";
import { ApiEditorPage } from "./pages/ApiEditorPage";
import { ApisPage } from "./pages/ApisPage";
import { MappingPage } from "./pages/MappingPage";
import { ProductEditorPage } from "./pages/ProductEditorPage";
import { ProductsPage } from "./pages/ProductsPage";
import { ApiLogsPage } from "./pages/ApiLogsPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ErrorsPage } from "./pages/ErrorsPage";
import { PartnerDetailPage } from "./pages/PartnerDetailPage";
import { PartnersPage } from "./pages/PartnersPage";
import { PartnerUsersPage } from "./pages/PartnerUsersPage";
import { PlatformUsersPage } from "./pages/PlatformUsersPage";
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
      { path: "approvals", element: <ApprovalsPage /> },
      // Wrapped rather than merely hidden from the navigation: the backend refuses a developer on
      // all of these, and a 403 page is a worse explanation than saying so up front.
      { path: "partners", element: <AdminOnly><PartnersPage /></AdminOnly> },
      { path: "partners/:id", element: <AdminOnly><PartnerDetailPage /></AdminOnly> },
      { path: "partner-users", element: <AdminOnly><PartnerUsersPage /></AdminOnly> },
      { path: "usage", element: <UsagePage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "errors", element: <ErrorsPage /> },
      { path: "products", element: <AdminOnly><ProductsPage /></AdminOnly> },
      { path: "products/new", element: <AdminOnly><ProductEditorPage /></AdminOnly> },
      { path: "products/:id", element: <AdminOnly><ProductEditorPage /></AdminOnly> },
      // CP-API-06/07 now live on each API's page (Request / Responses tabs and Import).
      { path: "documentation", element: <Navigate to="/apis" replace /> },
      { path: "mapping", element: <AdminOnly><MappingPage /></AdminOnly> },
      {
        path: "domains",
        element: <AdminOnly><ComingSoon title="Domains" brdRefs="CP-DOM-01 to CP-DOM-10, GW-09"
          description="Register domains, verify ownership, bind TLS certificates and environments, and choose which APIs each domain exposes." /></AdminOnly>,
      },
      { path: "users", element: <AdminOnly><PlatformUsersPage /></AdminOnly> },
    ],
  },
]);

export function App() {
  return (
    <AuthProvider
      allowedRoles={["ADMIN", "DEVELOPER"]}
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
