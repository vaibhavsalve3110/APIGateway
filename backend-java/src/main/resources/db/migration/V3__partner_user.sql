-- CP-PTN-04: Developer Portal user accounts belonging to a partner, with the signature key pair and
-- IPV salt issued to each user. Runs on PostgreSQL and on H2 in PostgreSQL mode.
--
-- Only the PUBLIC signature key is kept: the private key is shown once, at creation, and never stored.
-- The IPV salt is a shared secret, so it is stored encrypted (AES-GCM), never in plain text.

CREATE TABLE partner_user (
    id                    UUID          PRIMARY KEY,
    partner_id            UUID          NOT NULL REFERENCES partner (id),
    email                 VARCHAR(200)  NOT NULL UNIQUE,
    full_name             VARCHAR(160)  NOT NULL,
    role                  VARCHAR(30)   NOT NULL,
    status                VARCHAR(20)   NOT NULL,

    signature_algorithm   VARCHAR(40)   NOT NULL,
    signature_public_key  VARCHAR(4000) NOT NULL,
    signature_fingerprint VARCHAR(120)  NOT NULL,
    signature_created_at  TIMESTAMP WITH TIME ZONE NOT NULL,

    ipv_salt_cipher       VARCHAR(500)  NOT NULL,
    ipv_salt_masked       VARCHAR(60)   NOT NULL,
    ipv_salt_created_at   TIMESTAMP WITH TIME ZONE NOT NULL,

    created_at            TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by            VARCHAR(120)  NOT NULL,
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_partner_user_partner ON partner_user (partner_id);
