package com.apigw.platform.keys;

public enum KeyStatus {
    /** Accepted at the gateway, with no end date. */
    ACTIVE,
    /** Replaced by a newer key; still accepted until {@code expiresAt} (the 20-minute overlap window). */
    EXPIRING,
    /** Overlap window elapsed; no longer accepted. */
    EXPIRED,
    /** Withdrawn by an Admin within the overlap window, or because the partner lost access. */
    REVOKED;

    public boolean isLive() {
        return this == ACTIVE || this == EXPIRING;
    }
}
