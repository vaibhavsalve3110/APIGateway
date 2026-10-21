package com.apigw.platform.auth;

/**
 * Internal roles (BRD CP-LOG-04). Partner users carry the PARTNER role instead.
 *
 * <p>Renamed from EDITOR in V8. The role already meant "someone who works on APIs", but it could
 * publish an API, change a live one and manage partner organizations with nobody else involved; the
 * name now matches what it is, and the permissions were narrowed to match the name.
 */
public enum PlatformRole {

    /**
     * Everything: approving changes, partner organizations, Developer Portal users, and the APIM
     * users and roles themselves.
     */
    ADMIN,

    /**
     * Drafts and edits APIs, and reads the logs. Publishing an API, changing one that is already
     * live, and withdrawing one all raise a change request for an ADMIN instead of taking effect —
     * and an ADMIN other than the requester has to approve it.
     */
    DEVELOPER
}
