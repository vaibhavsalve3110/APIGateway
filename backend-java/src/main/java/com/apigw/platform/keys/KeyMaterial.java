package com.apigw.platform.keys;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

import com.apigw.platform.common.Env;

/**
 * A freshly generated security key. The plaintext exists only in memory and is returned to the caller once
 * (CP-SEC-08); only {@link #hash()} is persisted and pushed to the gateway (CP-SEC-09).
 *
 * <p>Keys carry 256 bits of randomness, so a plain SHA-256 is non-reversible and brute-force resistant;
 * the gateway re-computes the same digest on every call and compares hashes.
 */
public record KeyMaterial(String plaintext, String hash, String masked) {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final int SECRET_BYTES = 32;

    public static KeyMaterial generate(Env env) {
        byte[] secret = new byte[SECRET_BYTES];
        RANDOM.nextBytes(secret);
        String prefix = "agw_" + env.shortCode() + "_";
        String plaintext = prefix + Base64.getUrlEncoder().withoutPadding().encodeToString(secret);
        return new KeyMaterial(plaintext, sha256Hex(plaintext),
                prefix + "••••••••" + plaintext.substring(plaintext.length() - 4));
    }

    public static String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is required by every Java runtime", e);
        }
    }

    /** Keeps the plaintext out of logs and debugger views. */
    @Override
    public String toString() {
        return "KeyMaterial[" + masked + "]";
    }
}
