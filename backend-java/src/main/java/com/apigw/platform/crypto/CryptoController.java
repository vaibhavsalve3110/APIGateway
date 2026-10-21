package com.apigw.platform.crypto;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Where the portals get the public key they encrypt to.
 *
 * <p>Unauthenticated and exempt from encryption itself, necessarily: a client cannot encrypt its first
 * request until it has this, and it has no session yet either. Nothing here is a secret — a public key
 * is public, and publishing it is what lets a browser use it.
 *
 * <p>Answers identically to the Python service's {@code /api/crypto/public-key}, including the same
 * {@code kid}, because both hold the same keypair and the portal may reach either.
 */
@RestController
@RequestMapping("/api/crypto")
public class CryptoController {

    private final PayloadCrypto crypto;

    public CryptoController(PayloadCrypto crypto) {
        this.crypto = crypto;
    }

    @GetMapping("/public-key")
    public Map<String, Object> publicKey() {
        return Map.of(
                "kid", crypto.keyId(),
                "algorithm", "RSA-OAEP-256",
                "publicKeyPem", crypto.publicKeyPem(),
                "payload", Map.of(
                        "cipher", "AES-256-GCM",
                        "ivBytes", crypto.ivBytes(),
                        "keyBytes", crypto.keyBytes(),
                        "envelope", Map.of("iv", "base64(iv)", "data", "base64(ciphertext||tag)"),
                        "headers", Map.of(
                                PayloadCrypto.HEADER_VERSION, PayloadCrypto.VERSION,
                                PayloadCrypto.HEADER_KID, "the kid above",
                                PayloadCrypto.HEADER_KEY, "base64(RSA-OAEP-SHA256(32-byte AES key))")));
    }
}
