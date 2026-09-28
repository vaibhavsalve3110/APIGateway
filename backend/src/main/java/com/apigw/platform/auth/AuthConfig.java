package com.apigw.platform.auth;

import java.time.Clock;

import javax.crypto.spec.SecretKeySpec;

import com.nimbusds.jose.jwk.source.ImmutableSecret;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;

import com.apigw.platform.config.ApigwProperties;

/**
 * Session tokens are minted and verified by the platform itself (HS256), now that sign-in is e-mail OTP
 * rather than Keycloak. Defining these beans also makes Spring's resource-server auto-configuration stand down.
 */
@Configuration
class AuthConfig {

    @Bean
    JwtEncoder jwtEncoder(ApigwProperties props, Environment env) {
        return new NimbusJwtEncoder(new ImmutableSecret<>(TokenService.signingKey(props, env)));
    }

    @Bean
    JwtDecoder jwtDecoder(ApigwProperties props, Environment env, Clock clock) {
        SecretKeySpec key = TokenService.signingKey(props, env);
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(key).macAlgorithm(MacAlgorithm.HS256).build();
        // Expiry is judged by the application's own Clock, the same one that set it — otherwise a test or a
        // deployment running on a shifted clock issues tokens it then rejects.
        JwtTimestampValidator timestamps = new JwtTimestampValidator();
        timestamps.setClock(clock);
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                timestamps, new JwtIssuerValidator(TokenService.ISSUER)));
        return decoder;
    }
}
