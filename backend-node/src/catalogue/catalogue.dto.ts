/**
 * Field-for-field equivalents of backend-java's ApiView, PartnerView and GroupView. The portals are
 * shared between both services, so a missing or renamed field here is a broken screen there.
 */

export interface ApiDocumentation {
  source?: string | null;
  queryParameters?: unknown[] | null;
  requestHeaders?: unknown[] | null;
  requestBodyFields?: unknown[] | null;
  requestBodyExample?: string | null;
  responseHeaders?: unknown[] | null;
  responses?: unknown[] | null;
}

export interface ApiView {
  id: string;
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  backendUrlSandbox: string;
  backendUrlProduction: string | null;
  status: string;
  guestVisible: boolean;
  rateLimitCount: number;
  rateLimitWindow: string;
  ownerTeam: string | null;
  description: string | null;
  disabledAt: string | null;
  /** Only set once an API is DISABLED: when the cooling period lets it be deleted (CP-RPT-05). */
  deletableFrom: string | null;
  createdAt: string;
  updatedAt: string;
  documentation: ApiDocumentation | null;
}

export interface PartnerView {
  id: string;
  code: string;
  name: string;
  groupId: string;
  groupName: string | null;
  accessTier: string;
  status: string;
  contactEmail: string | null;
  clientIdSandbox: string;
  clientIdProduction: string | null;
  createdAt: string;
  signatureAlgorithm: string | null;
  signatureFingerprint: string | null;
  signaturePublicKey: string | null;
  signatureCreatedAt: string | null;
  ipvSaltMasked: string | null;
  ipvSaltCreatedAt: string | null;
}

export interface GroupView {
  id: string;
  name: string;
  description: string | null;
  status: string;
  partnerCount: number;
}
