import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { AuthProvider, ComingSoon, readAuthConfig, SignInScreen, type DevIdentity } from "@apigw/ui";

import { Layout } from "./Layout";
import { ApiDetailPage } from "./pages/ApiDetailPage";
import { CataloguePage } from "./pages/CataloguePage";
import { KeysPage } from "./pages/KeysPage";

// Partner codes match the demo seed (backend profile "demo") and the Keycloak demo realm.
const identities: DevIdentity[] = [
  {
    username: "integrations@acmefintech.in", roles: ["PARTNER"], partnerCode: "PTN-00001",
    label: "Acme Fintech Pvt Ltd", description: "UAT-only partner — Production is withheld",
  },
  {
    username: "integrations@kaverypayments.in", roles: ["PARTNER"], partnerCode: "PTN-00002",
    label: "Kavery Payments", description: "Production + UAT partner",
  },
];

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/apis" replace /> },
      { path: "apis", element: <CataloguePage /> },
      { path: "apis/:id", element: <ApiDetailPage /> },
      { path: "keys", element: <KeysPage /> },
      {
        path: "sandbox",
        element: <ComingSoon title="Sandbox console" brdRefs="DP-03"
          description="Open any API from your catalogue and use its Try it live panel to call the Sandbox with your own key. A standalone console with saved requests follows." />,
      },
      {
        path: "guides",
        element: <ComingSoon title="Guides" brdRefs="DP-06, DP-07"
          description="Token and refresh-token APIs, and the request encryption / response decryption reference." />,
      },
    ],
  },
]);

export function App() {
  return (
    <AuthProvider
      config={readAuthConfig(import.meta.env, identities)}
      signIn={(props) => (
        <SignInScreen
          {...props}
          product="Developer Portal"
          headline="Your APIs, your documentation, your keys."
          points={[
            "Only the APIs mapped to your organisation — nothing more",
            "Test against the Sandbox with your own key",
            "Rotate keys yourself, with a 20-minute overlap for cut-over",
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
