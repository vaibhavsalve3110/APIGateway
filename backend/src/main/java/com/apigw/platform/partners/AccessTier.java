package com.apigw.platform.partners;

import com.apigw.platform.common.Env;

/** BRD CP-PTN-05 / CP-PTN-06. */
public enum AccessTier {
    /** Sandbox (UAT) URL only. */
    UAT_ONLY,
    /** Both Sandbox and Production URLs. */
    PRODUCTION;

    public boolean allows(Env env) {
        return env == Env.SANDBOX || this == PRODUCTION;
    }
}
