package com.apigw.platform.partnerusers;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;

/**
 * A freshly generated request-signing key pair for a partner user.
 *
 * <p>The partner signs request payloads with the private key; the platform (and the gateway) verify with the
 * public key. Following the security-key rule (CP-SEC-08), the private key is returned to the caller once, at
 * creation, and never stored — only {@link #publicKeyPem()} and {@link #fingerprint()} are persisted. If a
 * partner loses the private key, an Admin regenerates the pair, which invalidates the previous one.
 */
public record SignatureKeyMaterial(String algorithm, String privateKeyPem, String publicKeyPem, String fingerprint) {

    static final String ALGORITHM = "RSA-2048/SHA-256";
    private static final int KEY_SIZE = 2048;

    public static SignatureKeyMaterial generate() {
        KeyPair pair = newPair();
        return new SignatureKeyMaterial(ALGORITHM,
                pem("PRIVATE KEY", pair.getPrivate().getEncoded()),   // PKCS#8
                pem("PUBLIC KEY", pair.getPublic().getEncoded()),     // X.509 SubjectPublicKeyInfo
                fingerprintOf(pair.getPublic().getEncoded()));
    }

    private static KeyPair newPair() {
        try {
            KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(KEY_SIZE);
            return generator.generateKeyPair();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("RSA is required by every Java runtime", e);
        }
    }

    /** OpenSSH-style fingerprint of the public key, short enough to compare by eye. */
    private static String fingerprintOf(byte[] derPublicKey) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(derPublicKey);
            return "SHA256:" + Base64.getEncoder().withoutPadding().encodeToString(digest);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is required by every Java runtime", e);
        }
    }

    private static String pem(String label, byte[] der) {
        String body = Base64.getMimeEncoder(64, new byte[] {'\n'}).encodeToString(der);
        return "-----BEGIN " + label + "-----\n" + body + "\n-----END " + label + "-----\n";
    }

    /** Keeps the private key out of logs and debugger views. */
    @Override
    public String toString() {
        return "SignatureKeyMaterial[" + algorithm + " " + fingerprint + "]";
    }
}
