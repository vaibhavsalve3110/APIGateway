package com.apigw.platform.partners;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** A group of partners sharing the same Product / API access (BRD CP-PTN-01). */
@Entity
@Table(name = "partner_group")
public class PartnerGroup {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String name;

    private String description;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private RecordStatus status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected PartnerGroup() {
    }

    public PartnerGroup(UUID id, String name, String description, Instant now) {
        this.id = id;
        this.name = name;
        this.description = description;
        this.status = RecordStatus.ACTIVE;
        this.createdAt = now;
    }

    public UUID getId() { return id; }
    public String getName() { return name; }
    public String getDescription() { return description; }
    public RecordStatus getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
}
