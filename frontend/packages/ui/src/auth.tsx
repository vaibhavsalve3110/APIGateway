import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

import { createApiClient, type ApiClient } from "./api";

/**
 * Two sign-in modes:
 *  - "oidc": Authorization Code + PKCE against Keycloak (the real thing);
 *  - "dev":  pick a preset identity; the backend accepts X-Dev-* headers only when its dev profile is on.
 */
export type AuthConfig =
  | { mode: "oidc"; authority: string; clientId: string }
  | { mode: "dev"; identities: DevIdentity[] };

export interface DevIdentity {
  username: string;
  roles: string[];
  partnerCode?: string;
  label: string;
  description: string;
}

export interface SignedInUser {
  username: string;
  roles: string[];
  partnerCode: string | null;
}

interface AuthState {
  user: SignedInUser | null;
  api: ApiClient;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);
const DEV_KEY = "apigw.dev-identity";

export function useAuth(): AuthState & { user: SignedInUser } {
  const state = useContext(AuthContext);
  if (!state || !state.user) {
    throw new Error("useAuth must be used inside a signed-in AuthProvider");
  }
  return state as AuthState & { user: SignedInUser };
}

export function readAuthConfig(env: Record<string, string | undefined>, identities: DevIdentity[]): AuthConfig {
  if (env.VITE_AUTH_MODE === "oidc") {
    return {
      mode: "oidc",
      authority: env.VITE_OIDC_AUTHORITY ?? "http://localhost:8180/realms/apigw",
      clientId: env.VITE_OIDC_CLIENT_ID ?? "",
    };
  }
  return { mode: "dev", identities };
}

interface ProviderProps {
  config: AuthConfig;
  /** Rendered while signed out; receives the action that starts sign-in. */
  signIn: (props: SignInProps) => ReactNode;
  children: ReactNode;
}

export interface SignInProps {
  mode: AuthConfig["mode"];
  identities: DevIdentity[];
  onDevSignIn: (identity: DevIdentity) => void;
  onOidcSignIn: () => void;
  error: string | null;
}

export function AuthProvider({ config, signIn, children }: ProviderProps) {
  const manager = useMemo(
    () =>
      config.mode === "oidc"
        ? new UserManager({
            authority: config.authority,
            client_id: config.clientId,
            redirect_uri: window.location.origin + "/",
            post_logout_redirect_uri: window.location.origin + "/",
            response_type: "code",
            scope: "openid profile",
            userStore: new WebStorageStateStore({ store: window.sessionStorage }),
          })
        : null,
    [config],
  );

  const [oidcUser, setOidcUser] = useState<User | null>(null);
  const [devIdentity, setDevIdentity] = useState<DevIdentity | null>(() => {
    const raw = sessionStorage.getItem(DEV_KEY);
    return raw ? (JSON.parse(raw) as DevIdentity) : null;
  });
  const [user, setUser] = useState<SignedInUser | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const api = useMemo(
    () =>
      createApiClient((): Record<string, string> => {
        const headers: Record<string, string> = {};
        if (config.mode === "oidc") {
          if (oidcUser) {
            headers.Authorization = `Bearer ${oidcUser.access_token}`;
          }
        } else if (devIdentity) {
          headers["X-Dev-User"] = devIdentity.username;
          headers["X-Dev-Roles"] = devIdentity.roles.join(",");
          if (devIdentity.partnerCode) {
            headers["X-Dev-Partner"] = devIdentity.partnerCode;
          }
        }
        return headers;
      }),
    [config.mode, oidcUser, devIdentity],
  );

  // Complete an OIDC redirect or pick up an existing session.
  useEffect(() => {
    if (!manager) {
      setReady(true);
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const pending = params.has("code") && params.has("state")
      ? manager.signinRedirectCallback().then((u) => {
          window.history.replaceState({}, document.title, window.location.pathname);
          return u;
        })
      : manager.getUser();
    pending
      .then((u) => setOidcUser(u && !u.expired ? u : null))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setReady(true));
  }, [manager]);

  // Ask the backend who we are once we hold credentials.
  const signedIn = config.mode === "oidc" ? oidcUser != null : devIdentity != null;
  useEffect(() => {
    if (!ready || !signedIn) {
      setUser(null);
      return;
    }
    let cancelled = false;
    api
      .get<SignedInUser>("/api/me")
      .then((me) => !cancelled && setUser(me))
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          sessionStorage.removeItem(DEV_KEY);
          setDevIdentity(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ready, signedIn, api]);

  const signOut = useCallback(() => {
    setUser(null);
    if (manager) {
      void manager.signoutRedirect();
    } else {
      sessionStorage.removeItem(DEV_KEY);
      setDevIdentity(null);
    }
  }, [manager]);

  if (!ready || (signedIn && !user && !error)) {
    return <div className="empty">Loading…</div>;
  }
  if (!user) {
    return (
      <>
        {signIn({
          mode: config.mode,
          identities: config.mode === "dev" ? config.identities : [],
          error,
          onDevSignIn: (identity) => {
            setError(null);
            sessionStorage.setItem(DEV_KEY, JSON.stringify(identity));
            setDevIdentity(identity);
          },
          onOidcSignIn: () => {
            setError(null);
            void manager?.signinRedirect();
          },
        })}
      </>
    );
  }
  return <AuthContext.Provider value={{ user, api, signOut }}>{children}</AuthContext.Provider>;
}
