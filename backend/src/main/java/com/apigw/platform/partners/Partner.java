package com.apigw.platform.partners;

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

/** An Integration Partner account (BRD CP-PTN-02). */
@Entity
@Table(name = "partner")
public class Partner {

    @Id
    private UUID id;

    /** Human-facing partner ID, e.g. PTN-00042. */
    @Column(nullable = false)
    private String code;

    @Column(nullable = false)
    private String name;

    @Column(name = "group_id", nullable = false)
    private UUID groupId;

    @Enumerated(EnumType.STRING)
    @Column(name = "access_tier", nullable = false)
    private AccessTier accessTier;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private RecordStatus status;

    @Column(name = "contact_email")
    private String contactEmail;

    @Column(name = "client_id_sandbox", nullable = false)
    private String clientIdSandbox;

    @Column(name = "client_id_production")
    private String clientIdProduction;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected Partner() {
    }

    public Partner(UUID id, String code, String name, UUID groupId, String contactEmail, String clientIdSandbox,
                   Instant now) {
        this.id = id;
        this.code = code;
        this.name = name;
        this.groupId = groupId;
        this.contactEmail = contactEmail;
        this.clientIdSandbox = clientIdSandbox;
        this.accessTier = AccessTier.UAT_ONLY;
        this.status = RecordStatus.ACTIVE;
        this.createdAt = now;
        this.updatedAt = now;
    }

    /** Granting Production issues a Production Client ID; revoking keeps it on record but blocks new keys. */
    public void changeTier(AccessTier tier, String productionClientId, Instant now) {
        this.accessTier = tier;
        if (tier == AccessTier.PRODUCTION && clientIdProduction == null) {
            this.clientIdProduction = productionClientId;
        }
        this.updatedAt = now;
    }

    public void setStatus(RecordStatus status, Instant now) {
        this.status = status;
        this.updatedAt = now;
    }

    public String clientId(Env env) {
        String clientId = env == Env.PRODUCTION ? clientIdProduction : clientIdSandbox;
        if (clientId == null) {
            throw ApiException.forbidden("PRODUCTION_NOT_PROVISIONED",
                    name + " has no Production Client ID — grant the Production access tier first");
        }
        return clientId;
    }

    public boolean isActive() {
        return status == RecordStatus.ACTIVE;
    }

    public UUID getId() { return id; }
    public String getCode() { return code; }
    public String getName() { return name; }
    public UUID getGroupId() { return groupId; }
    public AccessTier getAccessTier() { return accessTier; }
    public RecordStatus getStatus() { return status; }
    public String getContactEmail() { return contactEmail; }
    public String getClientIdSandbox() { return clientIdSandbox; }
    public String getClientIdProduction() { return clientIdProduction; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
}
