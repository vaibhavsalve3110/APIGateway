package com.apigw.platform.security;

import java.util.Arrays;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;

import com.apigw.platform.config.ApigwProperties;

/**
 * Role-based access (BRD CP-LOG-04): Admin manages everything, Editor reads APIs and usage,
 * partner users reach only their own account under {@code /api/partner}.
 *
 * <p>Sessions come from {@code /api/auth} (CAPTCHA plus an e-mailed one-time code) and are carried as a
 * bearer token this service signs and verifies itself.
 */
@Configuration
public class SecurityConfig {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    SecurityFilterChain apiSecurity(HttpSecurity http, ApigwProperties props, Environment env) throws Exception {
        http.csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/actuator/health/**", "/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                        // Sign-in: CAPTCHA and one-time code. Throttled inside OtpService.
                        .requestMatchers("/api/auth/captcha", "/api/auth/otp/**").permitAll()
                        .requestMatchers("/api/auth/me").authenticated()
                        // Gateway log shipping; authenticated with the ingest token inside the controller.
                        .requestMatchers(HttpMethod.POST, "/internal/usage/batch").permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/admin/apis/**", "/api/admin/usage/**",
                                "/api/admin/dashboard/**", "/api/admin/dashboard").hasAnyRole("ADMIN", "EDITOR")
                        .requestMatchers("/api/admin/**").hasRole("ADMIN")
                        .requestMatchers("/api/partner/**").hasRole("PARTNER")
                        .requestMatchers("/api/me").authenticated()
                        .anyRequest().denyAll())
                .oauth2ResourceServer(oauth -> oauth.jwt(jwt -> jwt.jwtAuthenticationConverter(new KeycloakJwtConverter())));

        if (props.security().devAuthEnabled()) {
            if (Arrays.asList(env.getActiveProfiles()).contains("prod")) {
                throw new IllegalStateException("apigw.security.dev-auth-enabled must not be used with the prod profile");
            }
            log.warn("Developer header sign-in is ENABLED — for local development only");
            http.addFilterBefore(new DevAuthFilter(), BearerTokenAuthenticationFilter.class);
        }
        return http.build();
    }
}
