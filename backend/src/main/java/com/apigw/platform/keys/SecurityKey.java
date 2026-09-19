package com.apigw.platform.keys;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.common.Env;

/** A partner security key. Holds the SHA-256 hash and a masked form only — never the key itself. */
@Entity
@Table(name = "security_key")
public class SecurityKey {

    @Id
    private UUID id;

    @Column(name = "partner_id", nullable = false)
    private UUID partnerId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Env environment;

    @Column(name = "key_hash", nullable = false)
    private String keyHash;

    @Column(name = "masked_key", nullable = false)
    private String maskedKey;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private KeyStatus status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    /** Set while EXPIRING: the end of the overlap window. */
    @Column(name = "expires_at")
    private Instant expiresAt;

    /** When the key stopped being accepted (EXPIRED or REVOKED). */
    @Column(name = "ended_at")
    private Instant endedAt;

    protected SecurityKey() {
    }

    SecurityKey(UUID id, UUID partnerId, Env environment, KeyMaterial material, String createdBy, Instant now) {
        this.id = id;
        this.partnerId = partnerId;
        this.environment = environment;
        this.keyHash = material.hash();
        this.maskedKey = material.masked();
        this.status = KeyStatus.ACTIVE;
        this.createdBy = createdBy;
        this.createdAt = now;
    }

    void startOverlap(Instant expiresAt) {
        this.status = KeyStatus.EXPIRING;
        this.expiresAt = expiresAt;
    }

    /** The replacement was revoked inside the window, so this key becomes the sole active key again. */
    void reinstate() {
        this.status = KeyStatus.ACTIVE;
        this.expiresAt = null;
    }

    void expire(Instant now) {
        this.status = KeyStatus.EXPIRED;
        this.endedAt = now;
    }

    void revoke(Instant now) {
        this.status = KeyStatus.REVOKED;
        this.expiresAt = null;
        this.endedAt = now;
    }

    public UUID getId() { return id; }
    public UUID getPartnerId() { return partnerId; }
    public Env getEnvironment() { return environment; }
    public String getKeyHash() { return keyHash; }
    public String getMaskedKey() { return maskedKey; }
    public KeyStatus getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
    public String getCreatedBy() { return createdBy; }
    public Instant getExpiresAt() { return expiresAt; }
    public Instant getEndedAt() { return endedAt; }
}
