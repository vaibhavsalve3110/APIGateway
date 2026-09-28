package com.apigw.platform.auth;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.stereotype.Service;

import com.apigw.platform.config.ApigwProperties;

/**
 * Mints the session token issued after a correct one-time code.
 *
 * <p>Claims deliberately mirror what Keycloak used to send ({@code preferred_username},
 * {@code realm_access.roles}, {@code groups}), so authorisation downstream is unchanged whichever way a
 * token was obtained.
 */
@Service
public class TokenService {

    private static final Logger log = LoggerFactory.getLogger(TokenService.class);
    static final String ISSUER = "apigw-platform";

    private final JwtEncoder encoder;
    private final ApigwProperties props;
    private final Clock clock;

    public TokenService(JwtEncoder encoder, ApigwProperties props, Clock clock) {
        this.encoder = encoder;
        this.props = props;
        this.clock = clock;
    }

    public record Session(String token, Instant expiresAt) {
    }

    public Session issue(LoginIdentity identity) {
        Instant now = clock.instant();
        Instant expiresAt = now.plus(props.auth().tokenTtl());
        JwtClaimsSet.Builder claims = JwtClaimsSet.builder()
                .issuer(ISSUER)
                .issuedAt(now)
                .expiresAt(expiresAt)
                .subject(identity.email())
                .claim("preferred_username", identity.email())
                .claim("name", identity.displayName())
                .claim("realm_access", Map.of("roles", List.copyOf(identity.roles())));
        if (identity.isPartner()) {
            claims.claim("groups", List.of("/partners/" + identity.partnerCode()));
        }
        String token = encoder.encode(JwtEncoderParameters.from(
                JwsHeader.with(MacAlgorithm.HS256).build(), claims.build())).getTokenValue();
        return new Session(token, expiresAt);
    }

    /** HMAC key shared by the encoder and the decoder; 32+ bytes, from {@code apigw.auth.jwt-secret}. */
    static SecretKeySpec signingKey(ApigwProperties props, Environment env) {
        String secret = props.auth().jwtSecret();
        if (secret == null || secret.isBlank()) {
            if (Arrays.asList(env.getActiveProfiles()).contains("prod")) {
                throw new IllegalStateException(
                        "apigw.auth.jwt-secret (AUTH_JWT_SECRET) must be set in production: it signs session tokens");
            }
            log.warn("apigw.auth.jwt-secret is not set — using the built-in DEVELOPMENT signing key. "
                    + "Anyone with this source can mint a session token. Set AUTH_JWT_SECRET outside local development.");
            secret = "apigw-local-development-jwt-signing-secret-32b";
        }
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32) {
            throw new IllegalStateException("apigw.auth.jwt-secret must be at least 32 characters");
        }
        return new SecretKeySpec(bytes, "HmacSHA256");
    }
}
