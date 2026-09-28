package com.apigw.platform.partnerusers;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.partners.RecordStatus;

/**
 * A Developer Portal user account belonging to one partner (BRD CP-PTN-04).
 *
 * <p>A login only: the signature key pair and IPV salt belong to the organization (see {@code Partner}),
 * so several users of one organization share the same credentials.
 */
@Entity
@Table(name = "partner_user")
public class PartnerUser {

    @Id
    private UUID id;

    @Column(name = "partner_id", nullable = false)
    private UUID partnerId;

    @Column(nullable = false)
    private String email;

    @Column(name = "full_name", nullable = false)
    private String fullName;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private PartnerUserRole role;

    /** ACTIVE = access granted, DISABLED = access revoked (CP-PTN-04). */
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private RecordStatus status;


    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected PartnerUser() {
    }

    public PartnerUser(UUID id, UUID partnerId, String email, String fullName, PartnerUserRole role,
                       String createdBy, Instant now) {
        this.id = id;
        this.partnerId = partnerId;
        this.email = email;
        this.fullName = fullName;
        this.role = role;
        this.status = RecordStatus.ACTIVE;
        this.createdBy = createdBy;
        this.createdAt = now;
        this.updatedAt = now;
    }


    public void updateProfile(String fullName, String email, PartnerUserRole role, Instant now) {
        this.fullName = fullName;
        this.email = email;
        this.role = role;
        this.updatedAt = now;
    }

    public void setStatus(RecordStatus status, Instant now) {
        this.status = status;
        this.updatedAt = now;
    }

    public UUID getId() {
        return id;
    }

    public UUID getPartnerId() {
        return partnerId;
    }

    public String getEmail() {
        return email;
    }

    public String getFullName() {
        return fullName;
    }

    public PartnerUserRole getRole() {
        return role;
    }

    public RecordStatus getStatus() {
        return status;
    }


    public String getCreatedBy() {
        return createdBy;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
