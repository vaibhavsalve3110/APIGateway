# Database — entity-relationship diagram

PostgreSQL schema for the control plane (the Management Portal and Developer Portal backend).
The gateways keep their own runtime configuration in etcd; this database is the system of record
that the backend pushes to them.

- **Implemented** tables come from `backend/src/main/resources/db/migration/V1__baseline.sql` and
  `V2__api_documentation.sql`.
- **Planned** tables cover the BRD modules not yet built (Products, access mapping, domains, portal pages).
  Column lists for planned tables are a design proposal, to be confirmed when each module is built.

## Implemented (migrations V1, V2)

```mermaid
erDiagram
    PARTNER_GROUP ||--o{ PARTNER : "contains"
    PARTNER ||--o{ SECURITY_KEY : "holds"
    API_DEFINITION ||--o{ USAGE_EVENT : "logical: api_id"
    PARTNER ||--o{ USAGE_EVENT : "logical: client_id"

    PARTNER_GROUP {
        uuid id PK
        varchar name UK "e.g. Tier-1 Aggregators"
        varchar description
        varchar status "ACTIVE | DISABLED"
        timestamptz created_at
    }

    PARTNER {
        uuid id PK
        varchar code UK "PTN-00001"
        varchar name
        uuid group_id FK
        varchar access_tier "UAT_ONLY | PRODUCTION"
        varchar status "ACTIVE | DISABLED"
        varchar contact_email
        varchar client_id_sandbox UK "rate limits counted per Client ID"
        varchar client_id_production UK "null until Production is granted"
        timestamptz created_at
        timestamptz updated_at
    }

    SECURITY_KEY {
        uuid id PK "also the gateway credential id"
        uuid partner_id FK
        varchar environment "SANDBOX | PRODUCTION"
        varchar key_hash UK "SHA-256 only — key never stored"
        varchar masked_key "agw_sbx_........abcd"
        varchar status "ACTIVE | EXPIRING | EXPIRED | REVOKED"
        timestamptz created_at
        varchar created_by
        timestamptz expires_at "end of 20-min overlap"
        timestamptz ended_at
    }

    API_DEFINITION {
        uuid id PK
        varchar name
        varchar category
        varchar http_method "UK with proxy_path"
        varchar proxy_path "UK with http_method"
        varchar backend_url_sandbox
        varchar backend_url_production
        varchar status "DRAFT | ACTIVE | DISABLED"
        boolean guest_visible "defaults to false"
        int rate_limit_count
        varchar rate_limit_window "MINUTE | HOUR | DAY"
        varchar owner_team
        varchar description
        varchar documentation "V2 - JSON contract, see below"
        timestamptz disabled_at "starts the 7-day cooling period"
        timestamptz created_at
        timestamptz updated_at
    }

    USAGE_EVENT {
        bigint id PK
        timestamptz occurred_at "indexed; purged after 30 days"
        uuid api_id "from gateway route id"
        varchar environment
        varchar client_id
        int status_code
        int latency_ms
    }

    AUDIT_EVENT {
        bigint id PK
        timestamptz occurred_at
        varchar actor "username or System"
        varchar actor_role
        varchar action "CREATE, GENERATE, REVOKE, EXPIRE ..."
        varchar object_type "API, PARTNER, SECURITY_KEY ..."
        varchar object_id
        varchar detail
    }
```

`USAGE_EVENT` and `AUDIT_EVENT` are append-only and deliberately carry no foreign keys: usage rows must
survive an API being deleted, and audit rows must survive anything.

### API documentation (CP-API-06, CP-API-07)

Each API's contract is stored as one JSON document in `api_definition.documentation` (up to 200,000 characters),
not as child tables. The contract is always read and written whole: by the editor in the Management Portal,
by the Swagger / OpenAPI / Postman importer, and by the Developer Portal's API page and *Try it live* console.
One column means one row version per edit and no joins on the partner-facing read path.

```json
{
  "source": "MANUAL | OPENAPI | POSTMAN",
  "queryParameters":   [{ "name": "accountNumber", "type": "string", "required": true, "example": "...", "description": "..." }],
  "requestHeaders":    [ "...same field shape..." ],
  "requestBodyFields": [ "...same field shape; dotted names for nesting, e.g. payee.ifsc..." ],
  "requestBodyExample": "{ ... }",
  "responseHeaders":   [ "...same field shape..." ],
  "responses": [
    { "statusCode": 200, "description": "Accepted", "bodyExample": "{ ... }", "bodyFields": [] },
    { "statusCode": 409, "description": "Duplicate X-Request-Id", "bodyExample": "{ ... }", "bodyFields": [] }
  ]
}
```

The backend validates it on every save: every row needs a name, and status codes must be 100-599 and unique per API.
If documentation later needs search across APIs or per-field history, split it into endpoint / field / return-code
tables. On PostgreSQL the column can also become `jsonb` with a GIN index without changing the application.

## Planned (remaining BRD modules)

```mermaid
erDiagram
    PRODUCT ||--o{ PRODUCT_API : "bundles"
    API_DEFINITION ||--o{ PRODUCT_API : "is in"
    PARTNER_GROUP ||--o{ ACCESS_MAPPING : "is granted"
    PARTNER ||--o{ ACCESS_MAPPING : "is granted"
    PRODUCT ||--o{ ACCESS_MAPPING : "via product"
    API_DEFINITION ||--o{ ACCESS_MAPPING : "or directly"
    ACCESS_MAPPING ||--|| APPROVAL_EVIDENCE : "requires"
    DOMAIN ||--o{ DOMAIN_API : "exposes"
    API_DEFINITION ||--o{ DOMAIN_API : "exposed on"
    DOMAIN ||--o{ DOMAIN_RESTRICTION : "limits"
    PARTNER ||--o{ DOMAIN_RESTRICTION : "limited to"
    DOMAIN ||--o| TLS_CERTIFICATE : "serves"
    PORTAL_PAGE ||--o{ PORTAL_PAGE_VERSION : "versions"

    PRODUCT {
        uuid id PK
        varchar name UK
        varchar slug UK
        varchar status "DRAFT | PUBLISHED"
        varchar description
    }
    PRODUCT_API {
        uuid product_id PK, FK
        uuid api_id PK, FK
    }
    ACCESS_MAPPING {
        uuid id PK
        uuid partner_group_id FK "one of group / partner"
        uuid partner_id FK
        uuid product_id FK "one of product / api"
        uuid api_id FK
        varchar environments "SANDBOX | BOTH"
        uuid evidence_id FK "CP-RPT-06 — mandatory"
        varchar mapped_by
        timestamptz mapped_at
    }
    APPROVAL_EVIDENCE {
        uuid id PK
        varchar file_name
        varchar content_type
        varchar storage_ref "object store key"
        varchar sha256 "tamper evidence"
        varchar reference_note
        varchar uploaded_by
        timestamptz uploaded_at
    }
    DOMAIN {
        uuid id PK
        varchar fqdn UK
        varchar purpose "GATEWAY | DEVELOPER_PORTAL"
        varchar environment "SANDBOX | PRODUCTION"
        varchar status "PENDING_VERIFICATION | ACTIVE | DISABLED"
        varchar verification_token
        boolean is_default
        varchar owner_team
    }
    TLS_CERTIFICATE {
        uuid id PK
        uuid domain_id FK
        varchar subject
        varchar issuer
        timestamptz not_after "alerts at 30/15/7 days"
        varchar storage_ref
    }
    DOMAIN_API {
        uuid domain_id PK, FK
        uuid api_id PK, FK
    }
    DOMAIN_RESTRICTION {
        uuid domain_id PK, FK
        uuid partner_id PK, FK
    }
    PORTAL_PAGE {
        uuid id PK
        varchar slug UK
        varchar title
        varchar audience
        varchar status "DRAFT | PUBLISHED"
    }
    PORTAL_PAGE_VERSION {
        uuid id PK
        uuid page_id FK
        text body_markdown
        varchar edited_by
        timestamptz edited_at
        boolean published
    }
```

## Notes for production

- **Usage volume.** At ~5 million calls a day, `usage_event` holds ~150 million rows at the 30-day retention limit.
  Before go-live, convert it to monthly range partitions (`pg_partman`, supported on Amazon RDS) so retention
  becomes a partition drop rather than a `DELETE`, or move analytics to ClickHouse / TimescaleDB.
- **Keys.** `key_hash` is unique, so a hash collision or a replayed key cannot be registered twice. The plaintext
  key exists only in the HTTP response that created it (BRD v1.3, CP-SEC-08/09).
- **Audit.** For tamper evidence, add a hash chain column (each row stores the hash of the previous row), or ship
  rows to a WORM archive, depending on what your Information Security team requires.
