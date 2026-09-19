import { useQuery } from "@tanstack/react-query";

import { useAuth, type AccessTier, type RecordStatus } from "@apigw/ui";

export interface PartnerMe {
  code: string;
  name: string;
  accessTier: AccessTier;
  status: RecordStatus;
  clientIdSandbox: string;
  clientIdProduction: string | null;
}

/** The signed-in partner's own account — the backend derives it from the token, never from the request. */
export function usePartner() {
  const { api } = useAuth();
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<PartnerMe>("/api/partner/me") });
}
