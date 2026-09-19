package com.apigw.platform.usage;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.common.Env;

/** One gateway call: metadata only, never payloads (GW-08). */
@Entity
@Table(name = "usage_event")
public class UsageEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(name = "api_id")
    private UUID apiId;

    @Enumerated(EnumType.STRING)
    private Env environment;

    @Column(name = "client_id")
    private String clientId;

    @Column(name = "status_code", nullable = false)
    private int statusCode;

    @Column(name = "latency_ms", nullable = false)
    private int latencyMs;

    protected UsageEvent() {
    }

    public UsageEvent(Instant occurredAt, UUID apiId, Env environment, String clientId, int statusCode, int latencyMs) {
        this.occurredAt = occurredAt;
        this.apiId = apiId;
        this.environment = environment;
        this.clientId = clientId;
        this.statusCode = statusCode;
        this.latencyMs = latencyMs;
    }

    public Long getId() { return id; }
    public Instant getOccurredAt() { return occurredAt; }
    public UUID getApiId() { return apiId; }
    public Env getEnvironment() { return environment; }
    public String getClientId() { return clientId; }
    public int getStatusCode() { return statusCode; }
    public int getLatencyMs() { return latencyMs; }
}
