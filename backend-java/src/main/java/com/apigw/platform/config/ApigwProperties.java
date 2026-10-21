package com.apigw.platform.config;

import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Platform settings bound from the {@code apigw.*} block of application.yml. */
@ConfigurationProperties("apigw")
public record ApigwProperties(Keys keys, Apis apis, Usage usage, Security security, Gateway gateway, TryIt tryIt,
                              Crypto crypto, Auth auth, Payload payload) {

    /**
     * Hybrid encryption of portal request and response payloads (VAPT).
     *
     * <p><strong>backend-python must hold the same private key</strong>: nginx routes portal traffic
     * between the two services per method and path, so a payload the portal encrypted once may arrive
     * at either. Required under the prod profile; outside it both services fall back to the same
     * built-in development keypair.
     *
     * @param privateKey          unencrypted PKCS#8 RSA private key, PEM, 2048-bit or stronger
     * @param encryptionEnforced  refuse unencrypted {@code /api} requests. Always on under prod
     *                            whatever this says; off by default elsewhere so Swagger UI, curl and
     *                            the test gates keep working
     * @see com.apigw.platform.crypto.PayloadCrypto
     */
    public record Payload(String privateKey, boolean encryptionEnforced) {
    }

    /**
     * Sign-in: a CAPTCHA, then a one-time code by e-mail (no passwords are held by the platform).
     *
     * @param jwtSecret           signs session tokens; at least 32 characters, required under prod
     * @param tokenTtl            how long a session lasts before the user signs in again
     * @param otpTtl              how long a code stays valid
     * @param otpLength           digits in a code
     * @param maxAttempts         wrong guesses allowed before a code is dead
     * @param resendCooldown      wait between two codes for one address
     * @param maxRequestsPerWindow codes per address inside requestWindow
     */
    public record Auth(String jwtSecret, Duration tokenTtl, Duration otpTtl, int otpLength, int maxAttempts,
                       Duration resendCooldown, int maxRequestsPerWindow, Duration requestWindow,
                       String mailFrom, boolean revealUnknownEmail) {
    }

    /**
     * Master key for secrets the platform must read back, such as a partner user's IPV salt:
     * 32 random bytes, base64-encoded. Required under the prod profile; see
     * {@link com.apigw.platform.crypto.SecretCipher}.
     */
    public record Crypto(String masterKey) {
    }

    /**
     * Developer Portal "Try it live" (BRD DP-03) — always the Sandbox, never Production.
     *
     * @param mode            GATEWAY calls the Sandbox gateway; SIMULATE answers from the API documentation
     *                        (for running without a gateway)
     * @param sandboxUrl      where the backend reaches the Sandbox gateway
     * @param publicSandboxUrl the Sandbox base URL shown to partners in documentation and code samples
     */
    public record TryIt(String mode, String sandboxUrl, String publicSandboxUrl, Duration timeout) {

        public boolean simulate() {
            return "SIMULATE".equalsIgnoreCase(mode);
        }
    }

    /**
     * @param overlapWindow    how long the replaced key keeps working (BRD CP-SEC-04)
     * @param emailKeyToAdmin  e-mail the new key to the organisation's Partner Admins. Convenient, but it
     *                         puts a live credential in a mailbox; turn it off to send only the notice and
     *                         leave the key to the one-time reveal in the portal.
     */
    public record Keys(Duration overlapWindow, boolean emailKeyToAdmin) {
    }

    public record Apis(Duration deleteCoolingPeriod) {
    }

    public record Usage(Duration retention, String ingestToken) {
    }

    public record Security(boolean devAuthEnabled) {
    }

    public record Gateway(boolean enabled, String redisHost, int redisPort, String usageSinkUrl,
                          Environment sandbox, Environment production) {

        /** One APISIX deployment per environment, so sandbox credentials can never reach Production (GW-05). */
        public record Environment(String adminUrl, String adminKey, List<String> hosts) {
        }
    }
}
