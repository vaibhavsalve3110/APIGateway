import { useQuery } from "@tanstack/react-query";

import { useAuth, type AccessTier, type RecordStatus } from "@apigw/ui";

export type PartnerUserRole = "PARTNER_ADMIN" | "PARTNER_DEVELOPER" | "PARTNER_VIEWER";

export interface PartnerMe {
  code: string;
  name: string;
  accessTier: AccessTier;
  status: RecordStatus;
  clientIdSandbox: string;
  clientIdProduction: string | null;
  /** Null when the token has no matching user record. */
  role: PartnerUserRole | null;
  /** Only a Partner Admin may rotate a live credential (CP-SEC-05). */
  canGenerateKeys: boolean;
}

/** The signed-in partner's own account — the backend derives it from the token, never from the request. */
export function usePartner() {
  const { api } = useAuth();
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<PartnerMe>("/api/partner/me") });
}
