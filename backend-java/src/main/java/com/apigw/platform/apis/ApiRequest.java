package com.apigw.platform.apis;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import com.apigw.platform.apis.docs.ApiDocumentation;

/**
 * Create / update payload for an API (CP-API-01, CP-API-02, CP-API-07, CP-API-08).
 *
 * @param status only read on create: DRAFT keeps an imported API off the gateways until an Admin enables it
 */
public record ApiRequest(
        @NotBlank @Size(max = 160) String name,
        @NotBlank @Size(max = 60) String category,
        @NotBlank @Pattern(regexp = "GET|POST|PUT|PATCH|DELETE", message = "must be GET, POST, PUT, PATCH or DELETE")
        String httpMethod,
        @NotBlank @Size(max = 200) @Pattern(regexp = "/[A-Za-z0-9/_\\-{}.]*", message = "must be a path starting with /")
        String proxyPath,
        @NotBlank @Size(max = 300) @Pattern(regexp = "https?://.+", message = "must be an http(s) URL") String backendUrlSandbox,
        @Size(max = 300) @Pattern(regexp = "https?://.+", message = "must be an http(s) URL") String backendUrlProduction,
        @NotNull @Min(1) @Max(1_000_000) Integer rateLimitCount,
        @NotNull RateWindow rateLimitWindow,
        @Size(max = 120) String ownerTeam,
        @Size(max = 2000) String description,
        @Valid ApiDocumentation documentation,
        ApiStatus status) {
}
