package com.apigw.platform.partnerusers;

import java.security.SecureRandom;
import java.util.Base64;

/**
 * The IPV salt issued to a partner user: 256 bits of randomness used with the partner's payload
 * encryption / verification routine.
 *
 * <p>Unlike a security key, both sides need the value, so it is stored encrypted (AES-GCM, see
 * {@link com.apigw.platform.crypto.SecretCipher}) rather than hashed, and an Admin can reveal it again —
 * an action that is audited.
 */
public record IpvSaltMaterial(String plaintext, String masked) {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final int SALT_BYTES = 32;
    private static final String PREFIX = "ipv_";

    public static IpvSaltMaterial generate() {
        byte[] salt = new byte[SALT_BYTES];
        RANDOM.nextBytes(salt);
        String plaintext = PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(salt);
        return new IpvSaltMaterial(plaintext, mask(plaintext));
    }

    public static String mask(String plaintext) {
        return PREFIX + "••••••••" + plaintext.substring(plaintext.length() - 4);
    }

    /** Keeps the salt out of logs and debugger views. */
    @Override
    public String toString() {
        return "IpvSaltMaterial[" + masked + "]";
    }
}
