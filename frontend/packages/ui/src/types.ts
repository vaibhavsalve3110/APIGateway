/** Shapes returned by the platform API (see the backend's *View records). */

export type Env = "SANDBOX" | "PRODUCTION";
export type ApiStatus = "DRAFT" | "ACTIVE" | "DISABLED";
export type RateWindow = "MINUTE" | "HOUR" | "DAY";
export type AccessTier = "UAT_ONLY" | "PRODUCTION";
export type RecordStatus = "ACTIVE" | "DISABLED";
export type KeyStatus = "ACTIVE" | "EXPIRING" | "EXPIRED" | "REVOKED";

export interface ApiView {
  id: string;
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  backendUrlSandbox: string;
  backendUrlProduction: string | null;
  status: ApiStatus;
  guestVisible: boolean;
  rateLimitCount: number;
  rateLimitWindow: RateWindow;
  ownerTeam: string | null;
  description: string | null;
  disabledAt: string | null;
  deletableFrom: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApiRequest {
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  backendUrlSandbox: string;
  backendUrlProduction: string | null;
  rateLimitCount: number;
  rateLimitWindow: RateWindow;
  ownerTeam: string | null;
  description: string | null;
}

export interface GroupView {
  id: string;
  name: string;
  description: string | null;
  status: RecordStatus;
  partnerCount: number;
}

export interface PartnerView {
  id: string;
  code: string;
  name: string;
  groupId: string;
  groupName: string | null;
  accessTier: AccessTier;
  status: RecordStatus;
  contactEmail: string | null;
  clientIdSandbox: string;
  clientIdProduction: string | null;
  createdAt: string;
}

export interface KeyView {
  id: string;
  environment: Env;
  maskedKey: string;
  status: KeyStatus;
  createdAt: string;
  createdBy: string;
  expiresAt: string | null;
  secondsRemaining: number | null;
  endedAt: string | null;
}

export interface GeneratedKey {
  key: KeyView;
  plaintext: string;
  clientId: string;
  previousKeyExpiresAt: string | null;
}

export interface ApiUsage {
  apiId: string;
  apiName: string;
  proxyPath: string | null;
  success: number;
  failed: number;
  successRate: number;
  minLatencyMs: number | null;
  maxLatencyMs: number | null;
  avgLatencyMs: number | null;
}

export interface UsageReport {
  from: string;
  to: string;
  totalSuccess: number;
  totalFailed: number;
  apis: ApiUsage[];
}

export interface AuditView {
  id: number;
  occurredAt: string;
  actor: string;
  actorRole: string | null;
  action: string;
  objectType: string;
  objectId: string | null;
  detail: string | null;
}
