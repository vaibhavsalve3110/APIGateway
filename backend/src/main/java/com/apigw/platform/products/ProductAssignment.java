package com.apigw.platform.products;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * Who may see a Product in the Developer Portal.
 *
 * <p>{@code partnerUserId == null} means the whole organization. A row naming a user narrows the Product to
 * that person, for journeys only part of a partner's team should work with.
 */
@Entity
@Table(name = "product_assignment")
public class ProductAssignment {

    @Id
    private UUID id;

    @Column(name = "product_id", nullable = false)
    private UUID productId;

    @Column(name = "partner_id", nullable = false)
    private UUID partnerId;

    @Column(name = "partner_user_id")
    private UUID partnerUserId;

    @Column(name = "assigned_by", nullable = false)
    private String assignedBy;

    @Column(name = "assigned_at", nullable = false)
    private Instant assignedAt;

    protected ProductAssignment() {
    }

    public ProductAssignment(UUID id, UUID productId, UUID partnerId, UUID partnerUserId, String assignedBy,
                             Instant now) {
        this.id = id;
        this.productId = productId;
        this.partnerId = partnerId;
        this.partnerUserId = partnerUserId;
        this.assignedBy = assignedBy;
        this.assignedAt = now;
    }

    public boolean isWholeOrganization() {
        return partnerUserId == null;
    }

    public UUID getId() {
        return id;
    }

    public UUID getProductId() {
        return productId;
    }

    public UUID getPartnerId() {
        return partnerId;
    }

    public UUID getPartnerUserId() {
        return partnerUserId;
    }

    public String getAssignedBy() {
        return assignedBy;
    }

    public Instant getAssignedAt() {
        return assignedAt;
    }
}
