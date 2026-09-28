package com.apigw.platform.security;

import java.util.Collection;

import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;

/** Authentication created from developer sign-in headers when {@code apigw.security.dev-auth-enabled=true}. */
public class DevAuthentication extends AbstractAuthenticationToken {

    private final String username;
    private final String partnerCode;

    public DevAuthentication(String username, String partnerCode, Collection<? extends GrantedAuthority> authorities) {
        super(authorities);
        this.username = username;
        this.partnerCode = partnerCode;
        setAuthenticated(true);
    }

    @Override
    public Object getCredentials() {
        return "";
    }

    @Override
    public Object getPrincipal() {
        return username;
    }

    public String partnerCode() {
        return partnerCode;
    }
}
