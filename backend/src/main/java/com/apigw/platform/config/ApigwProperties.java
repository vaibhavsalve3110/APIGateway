package com.apigw.platform.config;

import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Platform settings bound from the {@code apigw.*} block of application.yml. */
@ConfigurationProperties("apigw")
public record ApigwProperties(Keys keys, Apis apis, Usage usage, Security security, Gateway gateway) {

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
