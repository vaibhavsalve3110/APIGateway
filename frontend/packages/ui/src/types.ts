/** Shapes returned by the platform API (see the backend's *View records). */

export type Env = "SANDBOX" | "PRODUCTION";
export type ApiStatus = "DRAFT" | "ACTIVE" | "DISABLED";
export type RateWindow = "MINUTE" | "HOUR" | "DAY";
export type AccessTier = "UAT_ONLY" | "PRODUCTION";
export type RecordStatus = "ACTIVE" | "DISABLED";
export type KeyStatus = "ACTIVE" | "EXPIRING" | "EXPIRED" | "REVOKED";

/** One documented parameter, header or body field; dotted names express nesting (payee.ifsc). */
export interface ApiField {
  name: string;
  type: string;
  required: boolean;
  example: string | null;
  description: string | null;
}

export interface ApiResponseDoc {
  statusCode: number;
  description: string | null;
  bodyExample: string | null;
  bodyFields: ApiField[];
}

export interface ApiDocumentation {
  source: "MANUAL" | "OPENAPI" | "POSTMAN" | string;
  queryParameters: ApiField[];
  requestHeaders: ApiField[];
  requestBodyFields: ApiField[];
  requestBodyExample: string | null;
  responseHeaders: ApiField[];
  responses: ApiResponseDoc[];
}

export interface ImportedOperation {
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  description: string | null;
  documentation: ApiDocumentation;
}

export interface ImportResult {
  format: "OPENAPI" | "POSTMAN";
  title: string | null;
  suggestedBackendBaseUrl: string | null;
  operations: ImportedOperation[];
  warnings: string[];
}

/** Developer Portal view of one API — no internal backend URLs. */
export interface PartnerApiDetail {
  id: string;
  name: string;
  category: string;
  httpMethod: string;
  proxyPath: string;
  description: string | null;
  rateLimitCount: number;
  rateLimitWindow: string;
  productionAvailable: boolean;
  sandboxBaseUrl: string;
  keyHeader: string;
  tryItSimulated: boolean;
  documentation: ApiDocumentation;
}

export interface TryItRequest {
  apiKey: string;
  pathParams: Record<string, string>;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: string | null;
}

export interface TryItResponse {
  status: number;
  latencyMs: number;
  headers: Record<string, string>;
  body: string;
  simulated: boolean;
  requestUrl: string;
  note: string | null;
}

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
  documentation: ApiDocumentation;
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
  documentation: ApiDocumentation;
  /** Only read on create: DRAFT keeps an imported API off the gateways until it is enabled. */
  status?: ApiStatus;
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
  /** Organization-level request signing; the private key is never stored. */
  signatureAlgorithm: string | null;
  signatureFingerprint: string | null;
  signaturePublicKey: string | null;
  signatureCreatedAt: string | null;
  ipvSaltMasked: string | null;
  ipvSaltCreatedAt: string | null;
}

export type PartnerUserRole = "PARTNER_ADMIN" | "PARTNER_DEVELOPER" | "PARTNER_VIEWER";

/**
 * A Developer Portal login belonging to an organization (CP-PTN-04). The signature key pair and IPV salt
 * belong to the organization, so nothing secret appears here.
 */
export interface PartnerUserView {
  id: string;
  partnerId: string;
  partnerCode: string;
  partnerName: string;
  fullName: string;
  email: string;
  role: PartnerUserRole;
  status: RecordStatus;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

/** Returned once, when organization credentials are issued: the private key is never retrievable again. */
export interface IssuedCredentials {
  partner: PartnerView | null;
  privateKeyPem: string | null;
  publicKeyPem: string | null;
  ipvSalt: string | null;
  notice: string | null;
}

export interface RevealedSalt {
  partnerId: string;
  ipvSalt: string;
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

/** One call reported by a gateway (CP-RPT-02). */
export interface UsageLogEntry {
  id: number;
  occurredAt: string;
  apiId: string | null;
  apiName: string;
  httpMethod: string | null;
  proxyPath: string | null;
  environment: Env;
  clientId: string | null;
  partnerName: string | null;
  partnerCode: string | null;
  statusCode: number;
  latencyMs: number;
}

export interface PartnerUsage {
  clientId: string;
  partnerName: string | null;
  partnerCode: string | null;
  success: number;
  failed: number;
  avgLatencyMs: number | null;
}

/** Management Portal landing page (CP-RPT-01). */
export interface DashboardSummary {
  counts: {
    apis: number;
    activeApis: number;
    draftApis: number;
    disabledApis: number;
    partners: number;
    activePartners: number;
    productionPartners: number;
    partnerUsers: number;
  };
  lastHour: {
    from: string;
    success: number;
    failed: number;
    successRate: number;
    avgLatencyMs: number | null;
  };
  topApis: ApiUsage[];
  topPartners: PartnerUsage[];
}

/** An operational failure recorded in error_event (CP-LOG-05). */
export interface ErrorView {
  id: number;
  occurredAt: string;
  source: "SMTP" | "GATEWAY" | "SCHEDULER" | "API" | string;
  code: string;
  message: string;
  detail: string | null;
  actor: string | null;
  request: string | null;
  clientIp: string | null;
  /** Short id quoted to the caller, so a support report can be matched to this row. */
  reference: string;
  /**
   * The organization the failure belongs to, worked out from who was signed in or what was called.
   * Null means it could not be attributed to one — a platform failure rather than a partner's.
   */
  partnerId: string | null;
  partnerCode: string | null;
  partnerName: string | null;
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
