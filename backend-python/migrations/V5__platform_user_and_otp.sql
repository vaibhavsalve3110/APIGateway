-- Sign-in is e-mail OTP with a CAPTCHA, for both portals. Internal staff (Admin, Editor) need records of
-- their own, since they are no longer held in Keycloak; partner users already exist in partner_user.

CREATE TABLE platform_user (
    id            UUID          PRIMARY KEY,
    email         VARCHAR(200)  NOT NULL UNIQUE,
    full_name     VARCHAR(160)  NOT NULL,
    role          VARCHAR(20)   NOT NULL,   -- ADMIN | EDITOR
    status        VARCHAR(20)   NOT NULL,   -- ACTIVE | DISABLED
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by    VARCHAR(120)  NOT NULL,
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    last_login_at TIMESTAMP WITH TIME ZONE
);

-- One row per code sent. Only the hash is stored, the row is consumed on success, and attempts are counted
-- so a code cannot be brute-forced. Expired rows are purged by OtpCleanupJob.
CREATE TABLE otp_challenge (
    id          UUID          PRIMARY KEY,
    email       VARCHAR(200)  NOT NULL,
    code_hash   VARCHAR(80)   NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    attempts    INTEGER       NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    client_ip   VARCHAR(60)
);

CREATE INDEX idx_otp_email_created ON otp_challenge (email, created_at);
