package com.apigw.platform.portal;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.util.UriComponentsBuilder;
import org.springframework.web.util.UriUtils;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiService;
import com.apigw.platform.apis.ApiStatus;
import com.apigw.platform.apis.docs.ApiDocumentation;
import com.apigw.platform.apis.docs.ApiField;
import com.apigw.platform.apis.docs.ApiResponseDoc;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.gateway.ApisixConfigFactory;
import com.apigw.platform.keys.SecurityKeyService;
import com.apigw.platform.partners.Partner;

/**
 * "Try it live" for the Developer Portal (BRD DP-03). Calls go to the Sandbox only: the backend holds the Sandbox
 * gateway address and nothing else, and the partner's key must be one of their own live Sandbox keys.
 */
@Service
public class TryItService {

    private static final Pattern PATH_PARAM = Pattern.compile("\\{([A-Za-z0-9_\\-.]+)}");
    private static final int MAX_BODY = 256 * 1024;
    /** Headers the partner may not set: the gateway address and key are fixed by the platform. */
    private static final Set<String> BLOCKED_HEADERS = Set.of("host", "content-length", "connection", "transfer-encoding",
            "upgrade", "expect", "te", "trailer", "keep-alive", "proxy-authorization", ApisixConfigFactory.KEY_HEADER.toLowerCase(Locale.ROOT));
    private static final Set<String> HOP_BY_HOP = Set.of("connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade");

    public record TryItRequest(@NotBlank @Size(max = 200) String apiKey,
                               Map<String, String> pathParams,
                               Map<String, String> query,
                               Map<String, String> headers,
                               @Size(max = 100_000) String body) {
    }

    public record TryItResponse(int status, long latencyMs, Map<String, String> headers, String body,
                                boolean simulated, String requestUrl, String note) {
    }

    private final ApiService apis;
    private final SecurityKeyService keys;
    private final ApigwProperties props;
    private final HttpClient http;

    public TryItService(ApiService apis, SecurityKeyService keys, ApigwProperties props) {
        this.apis = apis;
        this.keys = keys;
        this.props = props;
        this.http = HttpClient.newBuilder()
                .connectTimeout(props.tryIt().timeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    public TryItResponse call(Partner partner, ApiDefinition api, TryItRequest request) {
        if (api.getStatus() != ApiStatus.ACTIVE) {
            throw ApiException.conflict("API_NOT_AVAILABLE", api.getName() + " is not available at the moment");
        }
        keys.assertUsableSandboxKey(partner.getId(), request.apiKey());

        String path = fillPath(api.getProxyPath(), request.pathParams() == null ? Map.of() : request.pathParams());
        UriComponentsBuilder uri = UriComponentsBuilder.fromUriString(props.tryIt().publicSandboxUrl()).path(path);
        if (request.query() != null) {
            request.query().forEach((k, v) -> {
                if (k != null && !k.isBlank() && v != null && !v.isBlank()) {
                    uri.queryParam(UriUtils.encodeQueryParam(k.trim(), StandardCharsets.UTF_8),
                            UriUtils.encodeQueryParam(v, StandardCharsets.UTF_8));
                }
            });
        }
        String shownUrl = uri.build(true).toUriString();

        ApiDocumentation docs = apis.documentationOf(api);
        return props.tryIt().simulate()
                ? simulate(docs, request, shownUrl)
                : viaGateway(api, request, path, uri, shownUrl);
    }

    /** Answers from the documentation, applying the same required-parameter check the backend would. */
    private TryItResponse simulate(ApiDocumentation docs, TryItRequest request, String shownUrl) {
        long latency = ThreadLocalRandom.current().nextLong(35, 180);
        String note = "Simulated from the API documentation — the Sandbox gateway is not connected in this environment.";
        for (ApiField q : docs.queryParameters()) {
            String value = request.query() == null ? null : request.query().get(q.name());
            if (q.required() && (value == null || value.isBlank())) {
                ApiResponseDoc documented400 = docs.responses().stream().filter(r -> r.statusCode() == 400).findFirst().orElse(null);
                String body = documented400 != null && documented400.bodyExample() != null ? documented400.bodyExample()
                        : "{\n  \"code\": \"MISSING_PARAMETER\",\n  \"detail\": \"Query parameter '" + q.name() + "' is required\"\n}";
                return new TryItResponse(400, latency, Map.of("Content-Type", "application/json"), body, true, shownUrl, note);
            }
        }
        ApiResponseDoc success = docs.primarySuccess();
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Content-Type", "application/json");
        for (ApiField h : docs.responseHeaders()) {
            headers.put(h.name(), h.example() == null ? "" : h.example());
        }
        if (success == null) {
            return new TryItResponse(200, latency, headers, "{}", true, shownUrl,
                    note + " No success response is documented for this API yet.");
        }
        return new TryItResponse(success.statusCode(), latency, headers,
                success.bodyExample() == null ? "" : success.bodyExample(), true, shownUrl, note);
    }

    private TryItResponse viaGateway(ApiDefinition api, TryItRequest request, String path, UriComponentsBuilder shown,
                                     String shownUrl) {
        URI target = UriComponentsBuilder.fromUriString(props.tryIt().sandboxUrl())
                .path(path)
                .query(shown.build(true).getQuery())
                .build(true)
                .toUri();
        HttpRequest.Builder builder = HttpRequest.newBuilder(target).timeout(props.tryIt().timeout());
        List<String> hosts = props.gateway().sandbox().hosts();
        if (hosts != null && !hosts.isEmpty()) {
            builder.header("Host", hosts.get(0));  // allowed via jdk.httpclient.allowRestrictedHeaders (see PlatformApplication)
        }
        builder.header(ApisixConfigFactory.KEY_HEADER, request.apiKey().trim());
        boolean hasBody = request.body() != null && !request.body().isBlank();
        boolean contentTypeSet = false;
        if (request.headers() != null) {
            for (Map.Entry<String, String> h : request.headers().entrySet()) {
                String name = h.getKey() == null ? "" : h.getKey().trim();
                if (name.isEmpty() || h.getValue() == null || BLOCKED_HEADERS.contains(name.toLowerCase(Locale.ROOT))) {
                    continue;
                }
                contentTypeSet |= name.equalsIgnoreCase("Content-Type");
                builder.header(name, h.getValue());
            }
        }
        if (hasBody && !contentTypeSet) {
            builder.header("Content-Type", "application/json");
        }
        builder.method(api.getHttpMethod(), hasBody && !"GET".equals(api.getHttpMethod())
                ? HttpRequest.BodyPublishers.ofString(request.body(), StandardCharsets.UTF_8)
                : HttpRequest.BodyPublishers.noBody());

        long start = System.nanoTime();
        try {
            HttpResponse<byte[]> response = http.send(builder.build(), HttpResponse.BodyHandlers.ofByteArray());
            long latency = (System.nanoTime() - start) / 1_000_000;
            Map<String, String> headers = new LinkedHashMap<>();
            response.headers().map().forEach((k, v) -> {
                if (!HOP_BY_HOP.contains(k.toLowerCase(Locale.ROOT)) && !v.isEmpty()) {
                    headers.put(k, v.get(0));
                }
            });
            byte[] bytes = response.body();
            boolean truncated = bytes.length > MAX_BODY;
            String body = new String(bytes, 0, Math.min(bytes.length, MAX_BODY), StandardCharsets.UTF_8);
            return new TryItResponse(response.statusCode(), latency, headers, body, false, shownUrl,
                    truncated ? "Response truncated to 256 KB." : null);
        } catch (IOException e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "SANDBOX_UNREACHABLE",
                    "The Sandbox gateway did not answer (" + e.getClass().getSimpleName() + "). Try again shortly.");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "INTERRUPTED", "The test call was interrupted");
        }
    }

    /** Fills {@code {param}} segments, encoding each value as a single path segment. */
    static String fillPath(String proxyPath, Map<String, String> params) {
        Matcher m = PATH_PARAM.matcher(proxyPath);
        StringBuilder out = new StringBuilder();
        while (m.find()) {
            String value = params.get(m.group(1));
            if (value == null || value.isBlank()) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "MISSING_PATH_PARAMETER",
                        "Enter a value for the path parameter '" + m.group(1) + "'");
            }
            m.appendReplacement(out, Matcher.quoteReplacement(UriUtils.encodePathSegment(value.trim(), StandardCharsets.UTF_8)));
        }
        m.appendTail(out);
        return out.toString();
    }
}
