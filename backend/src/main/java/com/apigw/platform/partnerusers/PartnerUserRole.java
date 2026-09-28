package com.apigw.platform.partnerusers;

/** What a partner user may do inside their own organisation's Developer Portal account. */
public enum PartnerUserRole {

    /** Reads documentation, generates and rotates their organisation's security keys. */
    PARTNER_ADMIN,

    /** Reads documentation and runs Sandbox tests; cannot generate keys. */
    PARTNER_DEVELOPER,

    /** Read-only access to documentation and usage. */
    PARTNER_VIEWER
}
