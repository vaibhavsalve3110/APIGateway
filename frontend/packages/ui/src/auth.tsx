import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { createApiClient, type ApiClient } from "./api";

/**
 * Sign-in is a CAPTCHA followed by a one-time code e-mailed to the address given (BRD CP-LOG-01): the
 * platform holds no passwords. A successful code exchange returns a session token, kept in sessionStorage so
 * a refresh does not sign the user out, and gone when the tab closes.
 */
export interface SignedInUser {
  username: string;
  roles: string[];
  partnerCode: string | null;
}

export interface Session {
  token: string;
  expiresAt: string;
  email: string;
  displayName: string;
  roles: string[];
  partnerCode: string | null;
}

interface AuthState {
  user: SignedInUser | null;
  api: ApiClient;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);
const SESSION_KEY = "apigw.session";

export function useAuth(): AuthState & { user: SignedInUser } {
  const state = useContext(AuthContext);
  if (!state || !state.user) {
    throw new Error("useAuth must be used inside a signed-in AuthProvider");
  }
  return state as AuthState & { user: SignedInUser };
}

function readStoredSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) {
      return null;
    }
    const session = JSON.parse(raw) as Session;
    return new Date(session.expiresAt).getTime() > Date.now() ? session : null;
  } catch {
    return null; // private mode, blocked storage or a corrupt value: just sign in again
  }
}

export interface SignInProps {
  /** Called by the sign-in screen once the code has been exchanged for a session. */
  onSignedIn: (session: Session) => void;
  /** An unauthenticated client for the /api/auth endpoints. */
  api: ApiClient;
  error: string | null;
}

interface ProviderProps {
  /** Which roles may use this portal; anyone else is signed out with an explanation. */
  allowedRoles: string[];
  portalName: string;
  signIn: (props: SignInProps) => ReactNode;
  children: ReactNode;
}

export function AuthProvider({ allowedRoles, portalName, signIn, children }: ProviderProps) {
  const [session, setSession] = useState<Session | null>(readStoredSession);
  const [user, setUser] = useState<SignedInUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(session != null);

  const api = useMemo(
    () => createApiClient((): Record<string, string> => (session ? { Authorization: `Bearer ${session.token}` } : {})),
    [session],
  );
  const publicApi = useMemo(() => createApiClient(() => ({})), []);

  const clearSession = useCallback(() => {
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // nothing to clear
    }
    setSession(null);
    setUser(null);
  }, []);

  // Confirm the stored token is still good, and that this user belongs in this portal.
  useEffect(() => {
    if (!session) {
      setUser(null);
      setChecking(false);
      return;
    }
    let cancelled = false;
    setChecking(true);
    api
      .get<SignedInUser>("/api/auth/me")
      .then((me) => {
        if (cancelled) {
          return;
        }
        if (!me.roles.some((role) => allowedRoles.includes(role))) {
          setError(`This account cannot use the ${portalName}.`);
          clearSession();
          return;
        }
        setUser(me);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) {
          clearSession(); // expired or revoked: back to the sign-in screen, quietly
        }
      })
      .finally(() => !cancelled && setChecking(false));
    return () => {
      cancelled = true;
    };
  }, [session, api, allowedRoles, portalName, clearSession]);

  const signOut = useCallback(() => {
    setError(null);
    clearSession();
  }, [clearSession]);

  if (checking) {
    return <div className="empty">Loading…</div>;
  }
  if (!user) {
    return (
      <>
        {signIn({
          api: publicApi,
          error,
          onSignedIn: (next) => {
            if (!next.roles.some((role) => allowedRoles.includes(role))) {
              setError(`This account cannot use the ${portalName}.`);
              return;
            }
            try {
              sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
            } catch {
              // the session simply will not survive a refresh
            }
            setError(null);
            setSession(next);
          },
        })}
      </>
    );
  }
  return <AuthContext.Provider value={{ user, api, signOut }}>{children}</AuthContext.Provider>;
}
