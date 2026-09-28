package com.apigw.platform.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.RateWindow;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;

class ApisixConfigFactoryTest {

    private final ApigwProperties.Gateway gw = new ApigwProperties.Gateway(true, "valkey", 6379, "http://sink",
            new ApigwProperties.Gateway.Environment("http://sbx:9180", "k1", List.of("sandbox-api.apigw.com")),
            new ApigwProperties.Gateway.Environment("http://prd:9180", "k2", List.of("api.apigw.com")));

    @Test
    @SuppressWarnings("unchecked")
    void routeHashesTheKeyAuthenticatesAndLimitsPerClientId() {
        ApiDefinition api = new ApiDefinition(UUID.randomUUID(), Instant.EPOCH);
        api.update("Fund Transfer — IMPS", "Payments", "POST", "/v1/payments/imps", "http://mock-sandbox:8080/core/imps",
                "https://core.example.in/core/imps", 300, RateWindow.MINUTE, null, null, Instant.EPOCH);

        Map<String, Object> sandbox = ApisixConfigFactory.route(api, Env.SANDBOX, gw);
        Map<String, Object> plugins = (Map<String, Object>) sandbox.get("plugins");

        assertThat(sandbox).containsEntry("uri", "/v1/payments/imps").containsEntry("methods", List.of("POST"))
                .containsEntry("hosts", List.of("sandbox-api.apigw.com"));
        assertThat((Map<String, Object>) plugins.get("key-auth")).containsEntry("header", "X-Security-Key")
                .containsEntry("hide_credentials", true);
        assertThat(plugins.get("serverless-pre-function").toString()).contains("resty.sha256", "X-Security-Key");
        assertThat((Map<String, Object>) plugins.get("limit-count"))
                .containsEntry("count", 300).containsEntry("time_window", 60)
                .containsEntry("key", "consumer_name").containsEntry("policy", "redis");
        assertThat((Map<String, Object>) plugins.get("proxy-rewrite")).containsEntry("uri", "/core/imps");
        assertThat((Map<String, Object>) sandbox.get("upstream"))
                .containsEntry("scheme", "http").containsEntry("nodes", Map.of("mock-sandbox:8080", 1));

        Map<String, Object> production = ApisixConfigFactory.route(api, Env.PRODUCTION, gw);
        assertThat(production).containsEntry("hosts", List.of("api.apigw.com"));
        assertThat((Map<String, Object>) production.get("upstream"))
                .containsEntry("scheme", "https").containsEntry("nodes", Map.of("core.example.in:443", 1));
    }

    @Test
    void pathParametersBecomeRouterParamsAndReachTheBackend() {
        assertThat(ApisixConfigFactory.gatewayUri("/v1/payments/imps/{txnId}")).isEqualTo("/v1/payments/imps/:txnId");
        assertThat(ApisixConfigFactory.rewrite("/v1/accounts/{accountId}/txns/{txnId}", "/core/{accountId}/t/{txnId}"))
                .isEqualTo(Map.of("regex_uri", List.of("^/v1/accounts/([^/]+)/txns/([^/]+)$", "/core/$1/t/$2")));
        // Static backend path: rewrite to it; no backend path: forward the request path unchanged.
        assertThat(ApisixConfigFactory.rewrite("/v1/x/{id}", "/core/x")).isEqualTo(Map.of("uri", "/core/x"));
        assertThat(ApisixConfigFactory.rewrite("/v1/x/{id}", "")).isNull();
    }

    @Test
    void routeIdsEncodeApiAndEnvironment() {
        UUID id = UUID.fromString("0f2c7d1b-64a8-4350-8c91-d472bf0ae618");
        assertThat(ApisixConfigFactory.routeId(id, Env.PRODUCTION)).isEqualTo("api-0f2c7d1b-64a8-4350-8c91-d472bf0ae618-prd");
    }

    @Test
    void credentialCarriesOnlyTheHash() {
        assertThat(ApisixConfigFactory.credential("abc123"))
                .isEqualTo(Map.of("plugins", Map.of("key-auth", Map.of("key", "abc123"))));
    }

    @Test
    @SuppressWarnings("unchecked")
    void usageLoggerShipsMetadataWithTheIngestToken() {
        ApigwProperties props = new ApigwProperties(new ApigwProperties.Keys(Duration.ofMinutes(20), true),
                new ApigwProperties.Apis(Duration.ofDays(7)), new ApigwProperties.Usage(Duration.ofDays(30), "t0k"),
                new ApigwProperties.Security(false), gw,
                new ApigwProperties.TryIt("SIMULATE", "http://sbx:9080", "http://sandbox-api:9080", Duration.ofSeconds(5)),
                new ApigwProperties.Crypto(null),
                new ApigwProperties.Auth(null, Duration.ofHours(8), Duration.ofMinutes(5), 6, 5,
                        Duration.ofSeconds(30), 5, Duration.ofMinutes(15), "no-reply@apigw.local", true));
        Map<String, Object> logger = (Map<String, Object>) ((Map<String, Object>) ApisixConfigFactory
                .usageLogger(Env.SANDBOX, props).get("plugins")).get("http-logger");
        assertThat(logger).containsEntry("uri", "http://sink").containsEntry("auth_header", "Ingest t0k");
        assertThat((Map<String, Object>) logger.get("log_format"))
                .containsKeys("route_id", "client_id", "status", "request_time")
                .doesNotContainKeys("request_body", "response_body");
    }
}
