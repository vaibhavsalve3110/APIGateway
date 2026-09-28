package com.apigw.platform.auth;

/** Internal roles (BRD CP-LOG-04). Partner users carry the PARTNER role instead. */
public enum PlatformRole {

    /** Full control: APIs, partners, users, keys. */
    ADMIN,

    /** Reads APIs and usage; edits documentation. */
    EDITOR
}
