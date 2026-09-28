package com.apigw.platform.auth;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.partners.RecordStatus;

/** An internal Management Portal user (BRD CP-LOG-02). Partner users live in {@code partner_user}. */
@Entity
@Table(name = "platform_user")
public class PlatformUser {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String email;

    @Column(name = "full_name", nullable = false)
    private String fullName;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private PlatformRole role;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private RecordStatus status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "last_login_at")
    private Instant lastLoginAt;

    protected PlatformUser() {
    }

    public PlatformUser(UUID id, String email, String fullName, PlatformRole role, String createdBy, Instant now) {
        this.id = id;
        this.email = email;
        this.fullName = fullName;
        this.role = role;
        this.status = RecordStatus.ACTIVE;
        this.createdBy = createdBy;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void update(String fullName, String email, PlatformRole role, Instant now) {
        this.fullName = fullName;
        this.email = email;
        this.role = role;
        this.updatedAt = now;
    }

    public void setStatus(RecordStatus status, Instant now) {
        this.status = status;
        this.updatedAt = now;
    }

    public void signedIn(Instant now) {
        this.lastLoginAt = now;
    }

    public UUID getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }

    public String getFullName() {
        return fullName;
    }

    public PlatformRole getRole() {
        return role;
    }

    public RecordStatus getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public String getCreatedBy() {
        return createdBy;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public Instant getLastLoginAt() {
        return lastLoginAt;
    }
}
