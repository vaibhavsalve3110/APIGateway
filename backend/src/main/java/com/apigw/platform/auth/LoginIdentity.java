package com.apigw.platform.auth;

import java.util.Set;

/**
 * Who an e-mail address belongs to: an internal user, or a partner user and the organization behind them.
 *
 * @param partnerCode the organization (PTN-00042) for a partner user; {@code null} for internal users
 */
public record LoginIdentity(String email, String displayName, Set<String> roles, String partnerCode) {

    public boolean isPartner() {
        return partnerCode != null;
    }
}
