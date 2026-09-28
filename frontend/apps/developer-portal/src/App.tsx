import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { AuthProvider, ComingSoon, SignInScreen } from "@apigw/ui";

import { Layout } from "./Layout";
import { ApiDetailPage } from "./pages/ApiDetailPage";
import { CataloguePage } from "./pages/CataloguePage";
import { DashboardPage } from "./pages/DashboardPage";
import { KeysPage } from "./pages/KeysPage";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "apis", element: <CataloguePage /> },
      { path: "apis/:id", element: <ApiDetailPage /> },
      { path: "keys", element: <KeysPage /> },
      // Sandbox testing lives on each API's own page ("Try it live"), so a separate console is not needed.
      { path: "sandbox", element: <Navigate to="/apis" replace /> },
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
      allowedRoles={["PARTNER"]}
      portalName="Developer Portal"
      signIn={(props) => (
        <SignInScreen
          {...props}
          product="Developer Portal"
          headline="Your APIs, your documentation, your keys."
          points={[
            "Sign in with a one-time code sent to your registered e-mail address",
            "Only the APIs mapped to your organisation — nothing more",
            "Test against the Sandbox with your own key, and rotate keys yourself",
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
