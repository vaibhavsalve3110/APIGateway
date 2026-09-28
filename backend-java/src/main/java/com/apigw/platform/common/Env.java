package com.apigw.platform.common;

/** The two isolated runtime environments a partner can be provisioned on (BRD GW-05). */
public enum Env {
    SANDBOX("sbx"),
    PRODUCTION("prd");

    private final String shortCode;

    Env(String shortCode) {
        this.shortCode = shortCode;
    }

    /** Used in gateway route ids and key prefixes, e.g. {@code agw_sbx_…}. */
    public String shortCode() {
        return shortCode;
    }
}
