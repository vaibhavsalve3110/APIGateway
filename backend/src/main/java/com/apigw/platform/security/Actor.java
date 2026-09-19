package com.apigw.platform.security;

import java.util.Set;

/**
 * Who is making a request: an internal Admin/Editor, a partner user, or the platform itself.
 *
 * @param partnerCode the partner (e.g. PTN-00042) a partner user belongs to; {@code null} for internal users
 */
public record Actor(String username, Set<String> roles, String partnerCode) {

    public static final Actor SYSTEM = new Actor("System", Set.of("SYSTEM"), null);

    public boolean hasRole(String role) {
        return roles.contains(role);
    }

    /** The single role recorded in the audit log. */
    public String primaryRole() {
        for (String role : new String[] {"ADMIN", "EDITOR", "PARTNER", "SYSTEM"}) {
            if (roles.contains(role)) {
                return role;
            }
        }
        return null;
    }
}
