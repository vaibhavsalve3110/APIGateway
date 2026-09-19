package com.apigw.platform.security;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Developer sign-in without Keycloak: the portals send {@code X-Dev-User}, {@code X-Dev-Roles}
 * and (for partner users) {@code X-Dev-Partner}. Registered only when dev auth is enabled, and
 * {@link SecurityConfig} refuses to start with it under the {@code prod} profile.
 */
class DevAuthFilter extends OncePerRequestFilter {

    static final String USER = "X-Dev-User";
    static final String ROLES = "X-Dev-Roles";
    static final String PARTNER = "X-Dev-Partner";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String user = request.getHeader(USER);
        if (user != null && !user.isBlank()
                && SecurityContextHolder.getContext().getAuthentication() == null) {
            List<SimpleGrantedAuthority> authorities = Arrays.stream(String.valueOf(request.getHeader(ROLES)).split(","))
                    .map(String::trim)
                    .filter(role -> role.equals("ADMIN") || role.equals("EDITOR") || role.equals("PARTNER"))
                    .map(role -> new SimpleGrantedAuthority("ROLE_" + role))
                    .toList();
            String partner = request.getHeader(PARTNER);
            SecurityContextHolder.getContext().setAuthentication(
                    new DevAuthentication(user.trim(), partner == null || partner.isBlank() ? null : partner.trim(), authorities));
        }
        chain.doFilter(request, response);
    }
}
