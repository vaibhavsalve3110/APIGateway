package com.apigw.platform.crypto;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import com.apigw.platform.config.ApigwProperties;

/**
 * AES-256-GCM for the few secrets the platform must be able to read back — today the partner users'
 * IPV salt (BRD 6.2: sensitive values are encrypted at rest, never stored in plain text).
 *
 * <p>Values that nobody ever needs back, such as security keys, are hashed instead
 * ({@link com.apigw.platform.keys.KeyMaterial}); this class is deliberately not used for them.
 *
 * <p>The master key is 32 random bytes, base64-encoded, in {@code apigw.crypto.master-key}
 * (environment variable {@code CRYPTO_MASTER_KEY}). Without it the application starts only outside
 * production, using a fixed development key, and says so loudly.
 */
@Component
public class SecretCipher {

    private static final Logger log = LoggerFactory.getLogger(SecretCipher.class);
    private static final String PREFIX = "v1:";
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;
    private static final int KEY_BYTES = 32;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final SecretKeySpec key;

    public SecretCipher(ApigwProperties props, Environment env) {
        this.key = new SecretKeySpec(readKey(props.crypto().masterKey(), env), "AES");
    }

    private static byte[] readKey(String configured, Environment env) {
        boolean prod = Arrays.asList(env.getActiveProfiles()).contains("prod");
        if (configured == null || configured.isBlank()) {
            if (prod) {
                throw new IllegalStateException(
                        "apigw.crypto.master-key (CRYPTO_MASTER_KEY) must be set in production: "
                                + "32 random bytes, base64-encoded");
            }
            log.warn("apigw.crypto.master-key is not set — using the built-in DEVELOPMENT key. "
                    + "Stored secrets are not protected. Set CRYPTO_MASTER_KEY outside local development.");
            byte[] dev = new byte[KEY_BYTES];
            System.arraycopy("apigw-local-development-master-key".getBytes(StandardCharsets.UTF_8), 0, dev, 0, KEY_BYTES);
            return dev;
        }
        byte[] decoded;
        try {
            decoded = Base64.getDecoder().decode(configured.trim());
        } catch (IllegalArgumentException e) {
            throw new IllegalStateException("apigw.crypto.master-key must be base64-encoded", e);
        }
        if (decoded.length != KEY_BYTES) {
            throw new IllegalStateException("apigw.crypto.master-key must decode to " + KEY_BYTES
                    + " bytes (AES-256); got " + decoded.length);
        }
        return decoded;
    }

    /** Returns {@code v1:base64(iv|ciphertext|tag)}. */
    public String encrypt(String plaintext) {
        try {
            byte[] iv = new byte[IV_BYTES];
            RANDOM.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            byte[] out = new byte[iv.length + ciphertext.length];
            System.arraycopy(iv, 0, out, 0, iv.length);
            System.arraycopy(ciphertext, 0, out, iv.length, ciphertext.length);
            return PREFIX + Base64.getEncoder().encodeToString(out);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("Unable to encrypt secret", e);
        }
    }

    public String decrypt(String stored) {
        if (stored == null || !stored.startsWith(PREFIX)) {
            throw new IllegalStateException("Stored secret is not in the expected " + PREFIX + " format");
        }
        try {
            byte[] raw = Base64.getDecoder().decode(stored.substring(PREFIX.length()));
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, raw, 0, IV_BYTES));
            byte[] plain = cipher.doFinal(raw, IV_BYTES, raw.length - IV_BYTES);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("Unable to decrypt secret — has the master key changed?", e);
        }
    }
}
