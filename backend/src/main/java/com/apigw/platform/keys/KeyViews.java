package com.apigw.platform.keys;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import com.apigw.platform.common.Env;

public final class KeyViews {

    private KeyViews() {
    }

    /** What any screen may show about a key: masked value and lifecycle — never the key (CP-SEC-08). */
    public record KeyView(UUID id, Env environment, String maskedKey, KeyStatus status, Instant createdAt,
                          String createdBy, Instant expiresAt, Long secondsRemaining, Instant endedAt) {

        static KeyView of(SecurityKey k, Instant now) {
            Long remaining = k.getStatus() == KeyStatus.EXPIRING && k.getExpiresAt() != null
                    ? Math.max(0, Duration.between(now, k.getExpiresAt()).toSeconds()) : null;
            return new KeyView(k.getId(), k.getEnvironment(), k.getMaskedKey(), k.getStatus(), k.getCreatedAt(),
                    k.getCreatedBy(), k.getExpiresAt(), remaining, k.getEndedAt());
        }
    }

    /**
     * Returned exactly once, by the generate call. {@code key} is the only time the full value leaves the
     * platform; {@code previousKeyExpiresAt} tells the caller how long the old key keeps working.
     */
    public record GeneratedKey(KeyView key, String plaintext, String clientId, Instant previousKeyExpiresAt) {
    }
}
