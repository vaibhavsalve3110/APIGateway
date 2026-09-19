package com.apigw.platform.gateway;

import java.net.URI;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;

/** Builds APISIX Admin API payloads. Pure functions, so the gateway contract is unit-testable. */
public final class ApisixConfigFactory {

    /** Header partners send their security key in (see the Developer Portal documentation). */
    public static final String KEY_HEADER = "X-Security-Key";

    /**
     * Runs before key-auth: replaces the presented key with its SHA-256 hex digest, so the gateway only ever
     * compares hashes and never stores a usable key (BRD v1.3, CP-SEC-09).
     */
    static final String HASH_PRESENTED_KEY = """
            return function(conf, ctx)
              local core = require("apisix.core")
              local key = core.request.header(ctx, "%s")
              if key and #key > 0 then
                local sha256 = require("resty.sha256")
                local str = require("resty.string")
                local digest = sha256:new()
                digest:update(key)
                core.request.set_header(ctx, "%s", str.to_hex(digest:final()))
              end
            end
            """.formatted(KEY_HEADER, KEY_HEADER);

    private ApisixConfigFactory() {
    }

    public static String routeId(UUID apiId, Env env) {
        return "api-" + apiId + "-" + env.shortCode();
    }

    public static Map<String, Object> route(ApiDefinition api, Env env, ApigwProperties.Gateway gw) {
        ApigwProperties.Gateway.Environment target = env == Env.PRODUCTION ? gw.production() : gw.sandbox();
        URI backend = URI.create(api.backendUrl(env));
        int port = backend.getPort() > 0 ? backend.getPort() : ("https".equals(backend.getScheme()) ? 443 : 80);

        Map<String, Object> plugins = new LinkedHashMap<>();
        plugins.put("serverless-pre-function", Map.of("phase", "rewrite", "functions", List.of(HASH_PRESENTED_KEY)));
        plugins.put("key-auth", Map.of("header", KEY_HEADER, "hide_credentials", true));
        // Counted per consumer, and each consumer is one Client ID — so a partner's overlapping keys share one limit.
        Map<String, Object> limit = new LinkedHashMap<>();
        limit.put("count", api.getRateLimitCount());
        limit.put("time_window", api.getRateLimitWindow().seconds());
        limit.put("key_type", "var");
        limit.put("key", "consumer_name");
        limit.put("policy", "redis");
        limit.put("redis_host", gw.redisHost());
        limit.put("redis_port", gw.redisPort());
        limit.put("rejected_code", 429);
        limit.put("show_limit_quota_header", true);
        plugins.put("limit-count", limit);
        Map<String, Object> rewrite = rewrite(api.getProxyPath(), backend.getRawPath());
        if (rewrite != null) {
            plugins.put("proxy-rewrite", rewrite);
        }

        Map<String, Object> route = new LinkedHashMap<>();
        route.put("name", api.getName() + " (" + env.name().toLowerCase() + ")");
        route.put("uri", gatewayUri(api.getProxyPath()));
        route.put("methods", List.of(api.getHttpMethod()));
        if (target.hosts() != null && !target.hosts().isEmpty()) {
            route.put("hosts", target.hosts());
        }
        route.put("upstream", Map.of(
                "type", "roundrobin",
                "scheme", backend.getScheme(),
                "pass_host", "node",
                "nodes", Map.of(backend.getHost() + ":" + port, 1)));
        route.put("plugins", plugins);
        route.put("labels", Map.of("api_id", api.getId().toString(), "env", env.shortCode()));
        return route;
    }

    private static final Pattern PATH_PARAM = Pattern.compile("\\{([A-Za-z0-9_\\-.]+)}");

    /** APISIX's router matches path parameters written as {@code :name}; proxy paths use OpenAPI's {@code {name}}. */
    static String gatewayUri(String proxyPath) {
        return PATH_PARAM.matcher(proxyPath).replaceAll(m -> ":" + m.group(1).replace('-', '_').replace('.', '_'));
    }

    /**
     * How the partner-facing path maps onto the backend path:
     * a static backend path is used as-is; a backend path with {@code {params}} is filled from the matching
     * parameters of the proxy path with a regex rewrite; an empty backend path forwards the request path unchanged.
     */
    static Map<String, Object> rewrite(String proxyPath, String backendPath) {
        if (backendPath == null || backendPath.isEmpty() || "/".equals(backendPath)) {
            return null;
        }
        List<String> proxyParams = new java.util.ArrayList<>();
        Matcher m = PATH_PARAM.matcher(proxyPath);
        while (m.find()) {
            proxyParams.add(m.group(1));
        }
        if (proxyParams.isEmpty() || !PATH_PARAM.matcher(backendPath).find()) {
            return Map.of("uri", backendPath);
        }
        String regex = "^" + PATH_PARAM.matcher(proxyPath.replace(".", "\\.")).replaceAll("([^/]+)") + "$";
        String template = PATH_PARAM.matcher(backendPath).replaceAll(p -> {
            int index = proxyParams.indexOf(p.group(1));
            return index < 0 ? Matcher.quoteReplacement(p.group(0)) : "\\$" + (index + 1);
        });
        return Map.of("regex_uri", List.of(regex, template));
    }

    public static Map<String, Object> consumer(String clientId, String partnerCode, String partnerName) {
        return Map.of(
                "username", clientId,
                "desc", partnerName,
                "labels", Map.of("partner", partnerCode));
    }

    public static Map<String, Object> credential(String keyHash) {
        return Map.of("plugins", Map.of("key-auth", Map.of("key", keyHash)));
    }

    /** Global rule that ships per-call metadata (never payloads, GW-08) to the usage report (CP-RPT-01). */
    public static Map<String, Object> usageLogger(Env env, ApigwProperties gwProps) {
        Map<String, Object> format = new LinkedHashMap<>();
        format.put("env", env.name());
        format.put("route_id", "$route_id");
        format.put("client_id", "$consumer_name");
        format.put("status", "$status");
        format.put("request_time", "$request_time");
        format.put("msec", "$msec");
        Map<String, Object> logger = new LinkedHashMap<>();
        logger.put("uri", gwProps.gateway().usageSinkUrl());
        logger.put("auth_header", "Ingest " + gwProps.usage().ingestToken());
        logger.put("batch_max_size", 200);
        logger.put("inactive_timeout", 2);
        logger.put("log_format", format);
        return Map.of("plugins", Map.of("http-logger", logger));
    }
}
