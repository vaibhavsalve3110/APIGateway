package com.apigw.platform.security;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

import com.apigw.platform.common.ApiException;

/** Resolves the {@link Actor} behind the current request, whichever way it signed in. */
public final class CurrentActor {

    /** Keycloak group path that marks a partner user, e.g. {@code /partners/PTN-00042}. */
    static final String PARTNER_GROUP_PREFIX = "/partners/";

    private CurrentActor() {
    }

    public static Actor get() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !auth.isAuthenticated()) {
            throw ApiException.forbidden("NOT_SIGNED_IN", "Sign in to continue");
        }
        Set<String> roles = auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .filter(a -> a.startsWith("ROLE_"))
                .map(a -> a.substring("ROLE_".length()))
                .collect(Collectors.toUnmodifiableSet());
        return new Actor(auth.getName(), roles, partnerCode(auth));
    }

    /** The partner the signed-in partner user belongs to, or a 403 if the user is not linked to one. */
    public static String requirePartnerCode() {
        String code = get().partnerCode();
        if (code == null) {
            throw ApiException.forbidden("NOT_A_PARTNER_USER", "This user is not linked to a partner account");
        }
        return code;
    }

    private static String partnerCode(Authentication auth) {
        if (auth instanceof DevAuthentication dev) {
            return dev.partnerCode();
        }
        if (auth instanceof JwtAuthenticationToken jwt) {
            List<String> groups = jwt.getToken().getClaimAsStringList("groups");
            if (groups != null) {
                for (String group : groups) {
                    if (group.startsWith(PARTNER_GROUP_PREFIX)) {
                        return group.substring(PARTNER_GROUP_PREFIX.length());
                    }
                }
            }
        }
        return null;
    }
}
