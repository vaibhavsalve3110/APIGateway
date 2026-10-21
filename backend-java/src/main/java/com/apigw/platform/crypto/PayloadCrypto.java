package com.apigw.platform.crypto;

import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.interfaces.RSAPrivateCrtKey;
import java.security.interfaces.RSAPrivateKey;
import java.security.spec.MGF1ParameterSpec;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.RSAPublicKeySpec;
import java.util.Arrays;
import java.util.Base64;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import com.apigw.platform.config.ApigwProperties;

/**
 * Hybrid encryption for portal request and response payloads (VAPT: payload confidentiality).
 *
 * <p>This is the Java half of the scheme in {@code backend-python/app/common/payload_crypto.py}, and the
 * two must stay byte-compatible: nginx routes portal traffic between the two services per method and
 * path, so a payload the portal encrypted once may arrive at either. **Both therefore hold the same
 * private key**, which is why it is configured rather than generated at startup.
 *
 * <p>Per request the client makes a fresh AES-256 key, wraps it with this service's RSA public key and
 * sends it in a header; bodies and responses are AES-256-GCM under that key:
 *
 * <pre>
 * X-Encrypted:   v1
 * X-Encrypt-Kid: which public key was used
 * X-Encrypt-Key: base64( RSA-OAEP-SHA256( 32-byte AES key ) )
 *
 * body, and every response:  {"iv": "base64(12 bytes)", "data": "base64(ciphertext||tag)"}
 * </pre>
 *
 * <p>The key travels in a header rather than the body so that one code path covers every method: a GET
 * has no body to carry it, but its response still has to be encrypted. A response reuses the request's
 * key with a <em>freshly generated</em> IV — safe for GCM only so long as no IV ever repeats under one
 * key, which is why it is random per message and never derived.
 *
 * <p>It sits on top of TLS and does not replace it. What it buys is that payloads are unreadable in an
 * intercepting proxy, which is how these findings are raised; it buys nothing against someone who
 * controls the browser, since the public key is public and the page can read its own cleartext.
 *
 * @see PayloadEncryptionFilter
 */
@Component
public class PayloadCrypto {

    private static final Logger log = LoggerFactory.getLogger(PayloadCrypto.class);
    private static final SecureRandom RANDOM = new SecureRandom();

    public static final String VERSION = "v1";
    public static final String HEADER_VERSION = "X-Encrypted";
    public static final String HEADER_KEY = "X-Encrypt-Key";
    public static final String HEADER_KID = "X-Encrypt-Kid";

    private static final int AES_KEY_BYTES = 32;
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;

    /**
     * The development keypair, identical to {@code DEV_PRIVATE_KEY_PEM} in the Python service so the two
     * agree without any configuration. In the repository on purpose and worthless: anything encrypted to
     * it can be read by anyone holding this file. Production must set {@code PAYLOAD_PRIVATE_KEY}.
     */
    private static final String DEV_PRIVATE_KEY_PEM = """
            -----BEGIN PRIVATE KEY-----
            MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDI5tZwMEQvwJKY
            D73Y7DBAoNnhiIrfHpw5k64Ysp/sRggCd+w6RC8o7HP2hmhTgP9lYKbmEWiRVvP4
            r96AdetLxcoJK289EfEMLooR0qw1PRf483zgdmtG7U+pBIUnOlw44ffQq4W6x2B7
            Km14ckn3Vr6PEWJHyQBe8cupqJmWmMV0MvubkaYmS+R5mWTYvwAJFfuV2XMC6jL3
            e7eewkUVgPtbmfsVyTy2f4/zXycOYihzWnz510udrarMjcibUo5wCNYkfDufJwFw
            N1Ze714/jZLIE9u1SFXbvvUluOHmWVuJNKYuy/0FIlvZ9ft3gk/u7OYAotzcmJy9
            pB/88HVzAgMBAAECggEAHDoStwCRFASClErh6bCFtw7ijgWZPXAXkx9kvqOaRKAy
            T+Z5klYyKhXO1TxdPB5Lw/qoeHrJrmIBNVfAc1weCy9nC5LGtlXnAEcprwdimrhS
            ve+4A/GfcP+2yZCRBMn2WyekofT3fR62N5fmeZ3VNqNBcuiGXn+nRa/DZbsCmV3t
            iR5X3g3Cj3wIrv3zqKrR+whsrq2t9qNfdrHNj7/Nxvan0rnu2JfXBkLQhCZhgtCZ
            VIwW4HsMiDP4zSlnZcoBR/B4DUYrKEgNXAB8JfkO8/gUz7VGcaMWiQP8DmHoGVft
            lf0WETDSc5toxlHH/LbnL55mDZZcBe7JFdQ41lTzgQKBgQD8TrspbcZlra44lL8u
            NuEFP1JRWb2ADK4BmsQk28uuu1Bsmn8SeMzBqhnPar1Gy0ItfzZyXq7i1UGA2GhJ
            N0u3AE+s+VhBA30FdjGA2b/kqrAgjoyu3LHhw/2M52YeOYAi1HUO2mTikpkxeFw/
            x+Nf+LCxA+thAdEZdd+1IYDQaQKBgQDL14PN1KvfzA+LHWJCA4y5dS38xpu1dIek
            9e0Omo6Q04FT/44TeBoSkOfmJpPty9oG0i7YNpKVntEczLe4WfqicpDnZXZ7pur+
            wV3oBgqjs1zeUww7HGG8fHCHicdaKPSbvSA6oWOqcwpEWxRUv+NVM7BfW5C9IBhG
            4KQ0S19bewKBgQCXRqVVO6pewHnbFuRh0ymrucGjYQkLw455C9BawSYoh8q6sw9J
            hgBOhayf/kGqNqhhGwsMG9UD0BVMKXStoWfWO2uKLJ5LrMnDApC/zs8NTYH4oz+a
            gFxvHtHhL8S8joFTYMsmsq8WYgtT6/RzkWe03SkjmVQBf9NdTp1ovsO7MQKBgE2j
            EudVZfUCIrVohqD/+xwzvkU1W97buEIjDJvwT/ZnKC3W+sT9jGif2kM1VEhQyQSq
            Dv94oZHtAFZIvnyvgJ9YpUoMwfjMlVpcSajyjCDXUrq2xMTKxYrllnJ5Dn2PdcLP
            YLQT/gLQeAua6P5ya2JrInTfShxOWhC8xK3KO1J7AoGATdRejtygOrjQ+QXA/CWY
            OYsw/u+8gcDhNgP5mE9EMmVZAcSzQgKEt95mZvjzF3500ITMBEnYJgembwzzGvgy
            wqQ8YKhQT+8SGE3j19soRhfp4+mNjedxfZcPyXH/PlEfNhX08/BCVoGY0HXdL9d1
            ErK2Jl64GuR24BtdZGg+iyU=
            -----END PRIVATE KEY-----""";

    private final PrivateKey privateKey;
    private final PublicKey publicKey;
    private final String keyId;
    private final String publicKeyPem;

    public PayloadCrypto(ApigwProperties props, Environment env) {
        boolean prod = Arrays.asList(env.getActiveProfiles()).contains("prod");
        String configured = props.payload() == null ? null : props.payload().privateKey();
        String pem;
        if (configured == null || configured.isBlank()) {
            if (prod) {
                // Falling back to a published keypair in production would make the whole mechanism
                // theatre, so this is fatal rather than a warning nobody reads.
                throw new IllegalStateException(
                        "apigw.payload.private-key (PAYLOAD_PRIVATE_KEY) must be set in production: "
                                + "it decrypts every portal payload");
            }
            log.warn("apigw.payload.private-key is not set — using the built-in DEVELOPMENT keypair. "
                    + "Portal payloads are not protected. Set PAYLOAD_PRIVATE_KEY outside local development.");
            pem = DEV_PRIVATE_KEY_PEM;
        } else {
            // A PEM in an environment variable usually arrives with its newlines escaped.
            pem = configured.replace("\\n", "\n");
        }

        this.privateKey = readPrivateKey(pem);
        this.publicKey = derivePublicKey(this.privateKey);
        this.publicKeyPem = encodePublicKey(this.publicKey);
        this.keyId = computeKeyId(this.publicKey);
        log.info("Payload encryption ready, key {}", this.keyId);
    }

    private static PrivateKey readPrivateKey(String pem) {
        String body = pem.replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s", "");
        try {
            byte[] der = Base64.getDecoder().decode(body);
            PrivateKey key = KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
            if (key instanceof RSAPrivateKey rsa && rsa.getModulus().bitLength() < 2048) {
                throw new IllegalStateException("apigw.payload.private-key is "
                        + rsa.getModulus().bitLength() + "-bit; 2048 is the minimum");
            }
            return key;
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException(
                    "apigw.payload.private-key must be an unencrypted PKCS#8 RSA private key in PEM form", e);
        }
    }

    /**
     * Recovers the public key from the private one, so only the private key needs configuring.
     *
     * <p>A PKCS#8 RSA private key carries the modulus and the public exponent, which is all a public key
     * is. Requiring both halves in configuration would only create a way for them to disagree.
     */
    private static PublicKey derivePublicKey(PrivateKey privateKey) {
        if (!(privateKey instanceof RSAPrivateCrtKey crt)) {
            throw new IllegalStateException(
                    "apigw.payload.private-key does not carry its public exponent, so the public key "
                            + "cannot be derived from it; supply a standard PKCS#8 RSA key");
        }
        try {
            return KeyFactory.getInstance("RSA")
                    .generatePublic(new RSAPublicKeySpec(crt.getModulus(), crt.getPublicExponent()));
        } catch (Exception e) {
            throw new IllegalStateException("Could not derive the payload public key", e);
        }
    }

    private static String encodePublicKey(PublicKey key) {
        String base64 = Base64.getMimeEncoder(64, "\n".getBytes(StandardCharsets.US_ASCII))
                .encodeToString(key.getEncoded());
        return "-----BEGIN PUBLIC KEY-----\n" + base64 + "\n-----END PUBLIC KEY-----\n";
    }

    /**
     * A short, stable name for the current public key, so a rotation is detectable.
     *
     * <p>SHA-256 over the DER public key, base64url, first 16 characters — the same construction as the
     * Python service, because the portal compares the two and a difference means the services disagree.
     */
    private static String computeKeyId(PublicKey key) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(key.getEncoded());
            String encoded = Base64.getUrlEncoder().withoutPadding().encodeToString(digest);
            return "sha256-" + encoded.substring(0, 16);
        } catch (Exception e) {
            throw new IllegalStateException("Could not compute the payload key id", e);
        }
    }

    public String keyId() {
        return keyId;
    }

    public String publicKeyPem() {
        return publicKeyPem;
    }

    public int ivBytes() {
        return IV_BYTES;
    }

    public int keyBytes() {
        return AES_KEY_BYTES;
    }

    /** Recovers the request's AES key from the RSA-wrapped value in {@code X-Encrypt-Key}. */
    public SecretKeySpec unwrapKey(String wrappedBase64) throws PayloadCryptoException {
        byte[] wrapped;
        try {
            wrapped = Base64.getDecoder().decode(wrappedBase64);
        } catch (IllegalArgumentException e) {
            throw new PayloadCryptoException("X-Encrypt-Key is not valid base64", e);
        }
        byte[] key;
        try {
            Cipher cipher = Cipher.getInstance("RSA/ECB/OAEPPadding");
            // Spelled out rather than using "OAEPWithSHA-256AndMGF1Padding", whose MGF1 digest defaults
            // to SHA-1 in some providers. That mismatch fails to decrypt what Python's OAEP produced.
            cipher.init(Cipher.DECRYPT_MODE, privateKey, new OAEPParameterSpec(
                    "SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT));
            key = cipher.doFinal(wrapped);
        } catch (Exception e) {
            // Deliberately not reporting why: distinguishing bad padding from a wrong key is what a
            // padding oracle is built out of. Every failure here gets the same message.
            throw new PayloadCryptoException("the encrypted key could not be unwrapped", e);
        }
        if (key.length != AES_KEY_BYTES) {
            throw new PayloadCryptoException(
                    "the unwrapped key is " + key.length + " bytes; expected " + AES_KEY_BYTES);
        }
        return new SecretKeySpec(key, "AES");
    }

    public byte[] decrypt(SecretKeySpec key, String ivBase64, String dataBase64) throws PayloadCryptoException {
        byte[] iv;
        byte[] data;
        try {
            iv = Base64.getDecoder().decode(ivBase64);
            data = Base64.getDecoder().decode(dataBase64);
        } catch (IllegalArgumentException e) {
            throw new PayloadCryptoException("iv or data is not valid base64", e);
        }
        if (iv.length != IV_BYTES) {
            throw new PayloadCryptoException("iv is " + iv.length + " bytes; expected " + IV_BYTES);
        }
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            return cipher.doFinal(data);
        } catch (Exception e) {
            // GCM authenticates, so this also fires when the body was altered in transit.
            throw new PayloadCryptoException("the payload failed to decrypt or its tag did not verify", e);
        }
    }

    /** Encrypts a response under the request's key, with an IV that has never been used with it. */
    public Envelope encrypt(SecretKeySpec key, byte[] plaintext) throws PayloadCryptoException {
        byte[] iv = new byte[IV_BYTES];
        RANDOM.nextBytes(iv);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            byte[] data = cipher.doFinal(plaintext);
            Base64.Encoder encoder = Base64.getEncoder();
            return new Envelope(encoder.encodeToString(iv), encoder.encodeToString(data));
        } catch (Exception e) {
            throw new PayloadCryptoException("the response could not be encrypted", e);
        }
    }

    /** The wire form of an encrypted payload, in either direction. */
    public record Envelope(String iv, String data) {
    }

    /** A payload that could not be unwrapped, decrypted or authenticated. */
    public static class PayloadCryptoException extends Exception {

        public PayloadCryptoException(String message) {
            super(message);
        }

        public PayloadCryptoException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
