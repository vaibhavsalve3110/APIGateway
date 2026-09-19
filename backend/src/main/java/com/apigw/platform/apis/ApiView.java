package com.apigw.platform.apis;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import com.apigw.platform.apis.docs.ApiDocumentation;

public record ApiView(UUID id, String name, String category, String httpMethod, String proxyPath,
                      String backendUrlSandbox, String backendUrlProduction, ApiStatus status, boolean guestVisible,
                      int rateLimitCount, RateWindow rateLimitWindow, String ownerTeam, String description,
                      Instant disabledAt, Instant deletableFrom, Instant createdAt, Instant updatedAt,
                      ApiDocumentation documentation) {

    static ApiView of(ApiDefinition api, Duration coolingPeriod, ApiDocumentation documentation) {
        return new ApiView(api.getId(), api.getName(), api.getCategory(), api.getHttpMethod(), api.getProxyPath(),
                api.getBackendUrlSandbox(), api.getBackendUrlProduction(), api.getStatus(), api.isGuestVisible(),
                api.getRateLimitCount(), api.getRateLimitWindow(), api.getOwnerTeam(), api.getDescription(),
                api.getDisabledAt(), api.deletableFrom(coolingPeriod), api.getCreatedAt(), api.getUpdatedAt(),
                documentation);
    }
}
