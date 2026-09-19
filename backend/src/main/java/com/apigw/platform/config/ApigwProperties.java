package com.apigw.platform.config;

import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Platform settings bound from the {@code apigw.*} block of application.yml. */
@ConfigurationProperties("apigw")
public record ApigwProperties(Keys keys, Apis apis, Usage usage, Security security, Gateway gateway, TryIt tryIt) {

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

    public record Keys(Duration overlapWindow) {
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
