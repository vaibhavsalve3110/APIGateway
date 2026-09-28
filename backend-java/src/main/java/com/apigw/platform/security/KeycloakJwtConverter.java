package com.apigw.platform.security;

import java.util.Collection;
import java.util.List;
import java.util.Map;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

/** Maps Keycloak realm roles (ADMIN, EDITOR, PARTNER) to Spring Security roles. */
public class KeycloakJwtConverter implements Converter<Jwt, AbstractAuthenticationToken> {

    @Override
    public AbstractAuthenticationToken convert(Jwt jwt) {
        String name = jwt.getClaimAsString("preferred_username");
        return new JwtAuthenticationToken(jwt, authorities(jwt), name != null ? name : jwt.getSubject());
    }

    @SuppressWarnings("unchecked")
    private static Collection<GrantedAuthority> authorities(Jwt jwt) {
        Map<String, Object> realmAccess = jwt.getClaimAsMap("realm_access");
        if (realmAccess == null || !(realmAccess.get("roles") instanceof List<?> roles)) {
            return List.of();
        }
        return ((List<Object>) roles).stream()
                .map(String::valueOf)
                .filter(role -> role.equals("ADMIN") || role.equals("EDITOR") || role.equals("PARTNER"))
                .map(role -> (GrantedAuthority) new SimpleGrantedAuthority("ROLE_" + role))
                .toList();
    }
}
