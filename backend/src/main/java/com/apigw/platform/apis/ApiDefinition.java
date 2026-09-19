package com.apigw.platform.apis;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;

/** An API onboarded onto the gateway (BRD section 5.1.2). */
@Entity
@Table(name = "api_definition")
public class ApiDefinition {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private String category;

    @Column(name = "http_method", nullable = false)
    private String httpMethod;

    @Column(name = "proxy_path", nullable = false)
    private String proxyPath;

    @Column(name = "backend_url_sandbox", nullable = false)
    private String backendUrlSandbox;

    @Column(name = "backend_url_production")
    private String backendUrlProduction;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ApiStatus status;

    /** CP-API-05: defaults to false on creation. */
    @Column(name = "guest_visible", nullable = false)
    private boolean guestVisible;

    @Column(name = "rate_limit_count", nullable = false)
    private int rateLimitCount;

    @Enumerated(EnumType.STRING)
    @Column(name = "rate_limit_window", nullable = false)
    private RateWindow rateLimitWindow;

    @Column(name = "owner_team")
    private String ownerTeam;

    private String description;

    @Column(name = "disabled_at")
    private Instant disabledAt;

    /** JSON document; see ApiDocumentation. */
    @Column(length = 200_000)
    private String documentation;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected ApiDefinition() {
    }

    public ApiDefinition(UUID id, Instant now) {
        this.id = id;
        this.status = ApiStatus.ACTIVE;
        this.guestVisible = false;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void update(String name, String category, String httpMethod, String proxyPath, String backendUrlSandbox,
                       String backendUrlProduction, int rateLimitCount, RateWindow rateLimitWindow,
                       String ownerTeam, String description, Instant now) {
        this.name = name;
        this.category = category;
        this.httpMethod = httpMethod;
        this.proxyPath = proxyPath;
        this.backendUrlSandbox = backendUrlSandbox;
        this.backendUrlProduction = backendUrlProduction;
        this.rateLimitCount = rateLimitCount;
        this.rateLimitWindow = rateLimitWindow;
        this.ownerTeam = ownerTeam;
        this.description = description;
        this.updatedAt = now;
    }

    public void setDocumentation(String documentation, Instant now) {
        this.documentation = documentation;
        this.updatedAt = now;
    }

    /** Created from an import but not yet reviewed: kept off the gateways until enabled. */
    public void markDraft(Instant now) {
        this.status = ApiStatus.DRAFT;
        this.updatedAt = now;
    }

    public void setGuestVisible(boolean guestVisible, Instant now) {
        this.guestVisible = guestVisible;
        this.updatedAt = now;
    }

    /** CP-API-03: disabling blocks further calls immediately (the gateway route is removed). */
    public void disable(Instant now) {
        if (status != ApiStatus.DISABLED) {
            status = ApiStatus.DISABLED;
            disabledAt = now;
            updatedAt = now;
        }
    }

    public void enable(Instant now) {
        status = ApiStatus.ACTIVE;
        disabledAt = null;
        updatedAt = now;
    }

    /** CP-RPT-05: deletion only after the API has stayed Disabled for longer than the cooling period. */
    public void assertDeletable(Instant now, Duration coolingPeriod) {
        if (status != ApiStatus.DISABLED || disabledAt == null) {
            throw ApiException.conflict("API_NOT_DISABLED", "Disable the API before deleting it");
        }
        Instant eligibleFrom = disabledAt.plus(coolingPeriod);
        if (now.isBefore(eligibleFrom)) {
            throw ApiException.conflict("COOLING_PERIOD_ACTIVE",
                    "This API can be deleted from " + eligibleFrom + ", after the " + coolingPeriod.toDays()
                            + "-day cooling period");
        }
    }

    public Instant deletableFrom(Duration coolingPeriod) {
        return status == ApiStatus.DISABLED && disabledAt != null ? disabledAt.plus(coolingPeriod) : null;
    }

    public String backendUrl(Env env) {
        return env == Env.PRODUCTION ? backendUrlProduction : backendUrlSandbox;
    }

    public UUID getId() { return id; }
    public String getName() { return name; }
    public String getCategory() { return category; }
    public String getHttpMethod() { return httpMethod; }
    public String getProxyPath() { return proxyPath; }
    public String getBackendUrlSandbox() { return backendUrlSandbox; }
    public String getBackendUrlProduction() { return backendUrlProduction; }
    public ApiStatus getStatus() { return status; }
    public boolean isGuestVisible() { return guestVisible; }
    public int getRateLimitCount() { return rateLimitCount; }
    public RateWindow getRateLimitWindow() { return rateLimitWindow; }
    public String getOwnerTeam() { return ownerTeam; }
    public String getDescription() { return description; }
    public Instant getDisabledAt() { return disabledAt; }
    public String getDocumentation() { return documentation; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
}
