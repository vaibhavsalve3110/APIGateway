"""Response shapes, for documentation.

These describe what each endpoint returns. They are **not** attached as `response_model`, because
that would make FastAPI filter every response through them — and a model that is subtly wrong would
then drop fields silently, which is exactly the class of defect the parity harness exists to catch.
They are referenced from the OpenAPI document instead (see `openapi_doc.py`), so Swagger describes
the API without standing between a handler and its caller.

Every timestamp is an ISO-8601 instant as `Instant.toString()` prints it, which is why they are
typed `str` rather than `datetime`: the wire format is the contract, not Python's rendering of it.
"""

from typing import Any

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 9457 problem document. Every error from this API has this shape."""

    detail: str = Field(description="What went wrong, in a sentence a user can read")
    instance: str = Field(description="The request path")
    status: int
    title: str
    code: str = Field(description="Stable machine-readable code the portals switch on")
    reference: str | None = Field(
        default=None, description="Present on a 5xx: quote it to an administrator to find the log entry"
    )
    fields: dict[str, str] | None = Field(
        default=None, description="Present on a validation failure: the message for each bad field"
    )


# --------------------------------------------------------------------------- catalogue


class ApiDocumentation(BaseModel):
    source: str | None = None
    queryParameters: list[dict[str, Any]] = []  # noqa: N815, RUF012
    requestHeaders: list[dict[str, Any]] = []  # noqa: N815, RUF012
    requestBodyFields: list[dict[str, Any]] = []  # noqa: N815, RUF012
    requestBodyExample: str | None = None  # noqa: N815
    responseHeaders: list[dict[str, Any]] = []  # noqa: N815, RUF012
    responses: list[dict[str, Any]] = []  # noqa: RUF012


class ApiView(BaseModel):
    id: str
    name: str
    category: str
    httpMethod: str  # noqa: N815
    proxyPath: str  # noqa: N815
    backendUrlSandbox: str  # noqa: N815
    backendUrlProduction: str | None  # noqa: N815
    status: str = Field(description="DRAFT, ACTIVE or DISABLED")
    guestVisible: bool  # noqa: N815
    rateLimitCount: int  # noqa: N815
    rateLimitWindow: str  # noqa: N815
    ownerTeam: str | None  # noqa: N815
    description: str | None
    disabledAt: str | None  # noqa: N815
    deletableFrom: str | None = Field(  # noqa: N815
        default=None, description="When the cooling period lets it be deleted; null unless disabled"
    )
    createdAt: str  # noqa: N815
    updatedAt: str  # noqa: N815
    documentation: ApiDocumentation | None


class GroupView(BaseModel):
    id: str
    name: str
    description: str | None
    status: str
    partnerCount: int  # noqa: N815


class PartnerView(BaseModel):
    id: str
    code: str = Field(description="PTN-00001 and so on")
    name: str
    groupId: str  # noqa: N815
    groupName: str | None  # noqa: N815
    accessTier: str = Field(description="UAT_ONLY or PRODUCTION")  # noqa: N815
    status: str
    contactEmail: str | None  # noqa: N815
    clientIdSandbox: str  # noqa: N815
    clientIdProduction: str | None  # noqa: N815
    createdAt: str  # noqa: N815
    signatureAlgorithm: str | None  # noqa: N815
    signatureFingerprint: str | None  # noqa: N815
    signaturePublicKey: str | None  # noqa: N815
    signatureCreatedAt: str | None  # noqa: N815
    ipvSaltMasked: str | None = Field(  # noqa: N815
        default=None, description="The salt as the portals show it; the value itself is encrypted at rest"
    )
    ipvSaltCreatedAt: str | None  # noqa: N815


class PartnerUserView(BaseModel):
    id: str
    partnerId: str  # noqa: N815
    partnerCode: str | None  # noqa: N815
    partnerName: str | None  # noqa: N815
    fullName: str  # noqa: N815
    email: str = Field(description="The sign-in identity, unique across every organization")
    role: str = Field(description="PARTNER_ADMIN, PARTNER_DEVELOPER or PARTNER_VIEWER")
    status: str
    createdBy: str  # noqa: N815
    createdAt: str  # noqa: N815
    updatedAt: str  # noqa: N815


class IssuedCredentials(BaseModel):
    """Returned once, when credentials are issued. The private key and salt are never stored."""

    partner: PartnerView | None
    privateKeyPem: str | None = Field(  # noqa: N815
        default=None, description="Shown once and not kept. If it is lost, recreate the pair"
    )
    publicKeyPem: str | None  # noqa: N815
    ipvSalt: str | None  # noqa: N815
    notice: str


class RevealedSalt(BaseModel):
    partnerId: str  # noqa: N815
    ipvSalt: str  # noqa: N815
    createdAt: str | None  # noqa: N815


# --------------------------------------------------------------------------- keys


class KeyView(BaseModel):
    id: str
    environment: str
    maskedKey: str = Field(description="Only a one-way hash of the key is stored")  # noqa: N815
    status: str = Field(description="ACTIVE, EXPIRING, EXPIRED or REVOKED")
    createdAt: str  # noqa: N815
    createdBy: str  # noqa: N815
    expiresAt: str | None  # noqa: N815
    secondsRemaining: int | None = Field(  # noqa: N815
        default=None, description="Counts down only while a key is inside its overlap window"
    )
    endedAt: str | None  # noqa: N815


class GeneratedKey(BaseModel):
    key: KeyView
    plaintext: str = Field(description="The key itself, returned once and never again")
    clientId: str  # noqa: N815
    previousKeyExpiresAt: str | None = Field(  # noqa: N815
        default=None, description="When the key being replaced stops working"
    )


# --------------------------------------------------------------------------- products and content


class StepView(BaseModel):
    step: int
    apiId: str  # noqa: N815
    apiName: str  # noqa: N815
    category: str | None
    httpMethod: str | None  # noqa: N815
    proxyPath: str | None  # noqa: N815
    status: str | None
    apiDescription: str | None  # noqa: N815
    note: str | None
    dependsOnApiId: str | None  # noqa: N815
    dependsOnApiName: str | None  # noqa: N815


class AssignmentView(BaseModel):
    id: str
    partnerId: str  # noqa: N815
    partnerCode: str | None  # noqa: N815
    partnerName: str | None  # noqa: N815
    partnerUserId: str | None = Field(  # noqa: N815
        default=None, description="Null means the whole organization; set narrows it to one person"
    )
    partnerUserEmail: str | None  # noqa: N815
    assignedBy: str  # noqa: N815
    assignedAt: str  # noqa: N815
    approvalReference: str = Field(  # noqa: N815
        description="CP-PTN-03: the authority for this mapping — a ticket, e-mail or note reference"
    )


class ProductView(BaseModel):
    id: str
    name: str
    slug: str
    summary: str | None
    description: str | None
    journeyMarkdown: str | None  # noqa: N815
    status: str
    steps: list[StepView]
    assignments: list[AssignmentView]
    createdAt: str  # noqa: N815
    createdBy: str  # noqa: N815
    updatedAt: str  # noqa: N815
    publishedAt: str | None  # noqa: N815


class PartnerProductView(BaseModel):
    id: str
    name: str
    slug: str
    summary: str | None
    description: str | None
    journeyMarkdown: str | None  # noqa: N815
    steps: list[StepView] = Field(description="Only APIs that are live")
    assignedToYouDirectly: bool  # noqa: N815


class VersionView(BaseModel):
    id: str
    version: int
    editedBy: str  # noqa: N815
    editedAt: str  # noqa: N815
    live: bool = Field(description="True for the version partners are currently shown")


class PageView(BaseModel):
    id: str
    slug: str
    title: str
    category: str
    status: str
    position: int
    bodyMarkdown: str = Field(description="The newest draft, which is not what partners see")  # noqa: N815
    unpublishedChanges: bool  # noqa: N815
    createdAt: str  # noqa: N815
    createdBy: str  # noqa: N815
    updatedAt: str  # noqa: N815
    publishedAt: str | None  # noqa: N815
    versions: list[VersionView]


class PageLink(BaseModel):
    slug: str
    title: str
    category: str


class PublishedPageView(BaseModel):
    slug: str
    title: str
    category: str
    bodyMarkdown: str  # noqa: N815
    publishedAt: str | None  # noqa: N815


# --------------------------------------------------------------------------- usage and logs


class ApiUsage(BaseModel):
    apiId: str | None  # noqa: N815
    apiName: str  # noqa: N815
    proxyPath: str | None  # noqa: N815
    success: int
    failed: int
    successRate: float  # noqa: N815
    minLatencyMs: int | None  # noqa: N815
    maxLatencyMs: int | None  # noqa: N815
    avgLatencyMs: int | None  # noqa: N815


class UsageReport(BaseModel):
    from_: str = Field(alias="from")
    to: str
    totalSuccess: int  # noqa: N815
    totalFailed: int  # noqa: N815
    apis: list[ApiUsage]


class LogEntry(BaseModel):
    id: int
    occurredAt: str  # noqa: N815
    apiId: str | None  # noqa: N815
    apiName: str | None = Field(  # noqa: N815
        default=None, description='"Deleted API" when the API has since been removed'
    )
    httpMethod: str | None  # noqa: N815
    proxyPath: str | None  # noqa: N815
    environment: str | None
    clientId: str | None  # noqa: N815
    partnerName: str | None  # noqa: N815
    partnerCode: str | None  # noqa: N815
    statusCode: int  # noqa: N815
    latencyMs: int  # noqa: N815


class AuditView(BaseModel):
    id: int
    occurredAt: str  # noqa: N815
    actor: str
    actorRole: str | None  # noqa: N815
    action: str
    objectType: str  # noqa: N815
    objectId: str | None  # noqa: N815
    detail: str | None


class AuditActor(BaseModel):
    """Someone who appears in the trail. Read from the trail, so deleted users remain findable."""

    actor: str
    actorRole: str | None  # noqa: N815
    entries: int
    lastSeen: str | None  # noqa: N815


class ErrorView(BaseModel):
    id: int
    occurredAt: str  # noqa: N815
    source: str = Field(description="API, GATEWAY, SMTP or SCHEDULER")
    code: str
    message: str
    detail: str | None = Field(default=None, description="Stack trace, where there is one")
    actor: str | None
    request: str | None
    clientIp: str | None  # noqa: N815
    reference: str
    partnerId: str | None = Field(  # noqa: N815
        default=None,
        description="Worked out from the actor or the request path; null means the platform's own",
    )
    partnerCode: str | None  # noqa: N815
    partnerName: str | None  # noqa: N815


class IngestResult(BaseModel):
    accepted: int = Field(description="Entries stored. Unparseable ones are skipped, not rejected")


# --------------------------------------------------------------------------- dashboards


class DashboardCounts(BaseModel):
    apis: int
    activeApis: int  # noqa: N815
    draftApis: int  # noqa: N815
    disabledApis: int  # noqa: N815
    partners: int
    activePartners: int  # noqa: N815
    productionPartners: int  # noqa: N815
    partnerUsers: int  # noqa: N815


class WindowTotals(BaseModel):
    from_: str = Field(alias="from")
    success: int
    failed: int
    successRate: float  # noqa: N815
    avgLatencyMs: int | None  # noqa: N815


class PartnerUsage(BaseModel):
    clientId: str | None  # noqa: N815
    partnerName: str | None  # noqa: N815
    partnerCode: str | None  # noqa: N815
    success: int
    failed: int
    avgLatencyMs: int | None  # noqa: N815


class Dashboard(BaseModel):
    counts: DashboardCounts
    lastHour: WindowTotals  # noqa: N815
    topApis: list[ApiUsage]  # noqa: N815
    topPartners: list[PartnerUsage]  # noqa: N815


class PartnerCounts(BaseModel):
    apisAvailable: int  # noqa: N815
    products: int
    activeKeys: int  # noqa: N815
    productionAvailable: bool  # noqa: N815


class PartnerDashboard(BaseModel):
    partnerName: str  # noqa: N815
    partnerCode: str  # noqa: N815
    counts: PartnerCounts
    window: WindowTotals
    apis: list[ApiUsage]
    recentCalls: list[LogEntry]  # noqa: N815


# --------------------------------------------------------------------------- identity


class Me(BaseModel):
    username: str
    roles: list[str]
    partnerCode: str | None  # noqa: N815


class PartnerMe(BaseModel):
    code: str
    name: str
    accessTier: str  # noqa: N815
    status: str
    clientIdSandbox: str  # noqa: N815
    clientIdProduction: str | None = Field(  # noqa: N815
        default=None, description="Null for a sandbox-only organization, even if one has been issued"
    )
    role: str | None
    canGenerateKeys: bool = Field(description="Only a Partner Admin may rotate a key")  # noqa: N815


class CatalogueApi(BaseModel):
    id: str
    name: str
    category: str
    httpMethod: str  # noqa: N815
    proxyPath: str  # noqa: N815
    description: str | None
    rateLimitCount: int  # noqa: N815
    rateLimitWindow: str  # noqa: N815
    productionAvailable: bool  # noqa: N815


class ApiDetail(CatalogueApi):
    sandboxBaseUrl: str  # noqa: N815
    keyHeader: str = Field(description="The header a partner sends their key in")  # noqa: N815
    tryItSimulated: bool  # noqa: N815
    documentation: ApiDocumentation | None


class Captcha(BaseModel):
    challengeId: str  # noqa: N815
    image: str = Field(description="A PNG as a data: URI")
    expiresInSeconds: int  # noqa: N815


class CodeRequested(BaseModel):
    expiresInSeconds: int  # noqa: N815
    resendInSeconds: int  # noqa: N815
    delivered: bool = Field(
        description="Whether the e-mail actually left. False means the code was not sent to the inbox"
    )
    devCode: str | None = Field(  # noqa: N815
        default=None,
        description="The code itself, returned only when the e-mail did not go. Never in production",
    )


class SignedIn(BaseModel):
    token: str
    expiresAt: str  # noqa: N815
    email: str
    displayName: str  # noqa: N815
    roles: list[str]
    partnerCode: str | None  # noqa: N815


class ChangeRequestView(BaseModel):
    """A proposed change waiting for, or decided by, an administrator."""

    id: str
    objectType: str = Field(description="API today")  # noqa: N815
    objectId: str | None  # noqa: N815
    objectName: str | None = Field(  # noqa: N815
        default=None, description="The API's current name; null once it has been deleted"
    )
    objectStatus: str | None  # noqa: N815
    action: str = Field(description="PUBLISH, UPDATE or DISABLE")
    payload: dict[str, Any] | None = Field(
        default=None, description="The proposed definition. Null for PUBLISH and DISABLE"
    )
    summary: str = Field(description="One line naming the API and what would change")
    status: str = Field(description="PENDING, APPROVED, REJECTED or WITHDRAWN")
    requestedBy: str  # noqa: N815
    requestedAt: str  # noqa: N815
    decidedBy: str | None  # noqa: N815
    decidedAt: str | None  # noqa: N815
    decisionNote: str | None  # noqa: N815
    applied: dict[str, Any] | None = Field(
        default=None, description="On approval, the API as it now stands"
    )


class ApiOrChangeRequest(BaseModel):
    """Either an `ApiView` or a `ChangeRequestView`, depending on whether approval was needed.

    Editing a draft applies at once and returns the API; editing a **live** API raises a change
    request and returns that, leaving the live definition serving. Rather than pretend these are one
    shape, the document says so: read `objectType`, which only the request has.
    """

    model_config = {"json_schema_extra": {"oneOf": [
        {"$ref": "#/components/schemas/ApiView"},
        {"$ref": "#/components/schemas/ChangeRequestView"},
    ]}}


class PlatformUserView(BaseModel):
    """Someone who signs in to the management portal. No organization, and no password."""

    id: str
    email: str = Field(description="The sign-in identity; not changeable once created")
    fullName: str  # noqa: N815
    role: str = Field(description="ADMIN or DEVELOPER")
    status: str
    createdBy: str  # noqa: N815
    createdAt: str  # noqa: N815
    updatedAt: str  # noqa: N815
    lastLoginAt: str | None = Field(  # noqa: N815
        default=None, description="Null until they have signed in once"
    )


class ImportedOperation(BaseModel):
    """One operation found in an uploaded file, ready to pre-fill the Add API editor."""

    name: str
    category: str
    httpMethod: str  # noqa: N815
    proxyPath: str  # noqa: N815
    description: str | None
    documentation: ApiDocumentation | None


class ImportResult(BaseModel):
    """What an uploaded specification turned into. Nothing is saved — see CP-API-06."""

    format: str = Field(description="OPENAPI or POSTMAN")
    title: str | None
    suggestedBackendBaseUrl: str | None = Field(  # noqa: N815
        default=None, description="The server or base URL the file declared, if any"
    )
    operations: list[ImportedOperation]
    warnings: list[str] = Field(
        description="What was skipped or could not be followed, including remote $ref"
    )


class TryItResult(BaseModel):
    """What a Try-it-live call came back with (DP-03)."""

    status: int = Field(description="The status the sandbox returned, not this API's own")
    latencyMs: int  # noqa: N815
    headers: dict[str, str]
    body: str = Field(description="Truncated to 256 KB; `note` says so when it was")
    simulated: bool = Field(
        description="True when answered from the documentation rather than a real gateway call"
    )
    requestUrl: str = Field(description="The URL a partner would call from their own system")  # noqa: N815
    note: str | None


class PayloadScheme(BaseModel):
    """How to wrap a payload. Described in the response so a client needs no out-of-band document."""

    cipher: str
    ivBytes: int  # noqa: N815
    keyBytes: int  # noqa: N815
    envelope: dict[str, str]
    headers: dict[str, str]


class PublicKey(BaseModel):
    kid: str = Field(description="Names this key. Echo it in X-Encrypt-Kid so a rotation is detectable")
    algorithm: str
    publicKeyPem: str  # noqa: N815
    payload: PayloadScheme


class ComponentStatus(BaseModel):
    status: str


class Health(BaseModel):
    status: str = Field(description="UP or DOWN")
    components: dict[str, ComponentStatus]
