package com.apigw.platform.audit;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One entry in the append-only audit trail (BRD CP-LOG-05, CP-SEC-07, NFR Auditability). */
@Entity
@Table(name = "audit_event")
public class AuditEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(nullable = false)
    private String actor;

    @Column(name = "actor_role")
    private String actorRole;

    @Column(nullable = false)
    private String action;

    @Column(name = "object_type", nullable = false)
    private String objectType;

    @Column(name = "object_id")
    private String objectId;

    private String detail;

    protected AuditEvent() {
    }

    AuditEvent(Instant occurredAt, String actor, String actorRole, String action, String objectType,
               String objectId, String detail) {
        this.occurredAt = occurredAt;
        this.actor = actor;
        this.actorRole = actorRole;
        this.action = action;
        this.objectType = objectType;
        this.objectId = objectId;
        this.detail = detail;
    }

    public Long getId() { return id; }
    public Instant getOccurredAt() { return occurredAt; }
    public String getActor() { return actor; }
    public String getActorRole() { return actorRole; }
    public String getAction() { return action; }
    public String getObjectType() { return objectType; }
    public String getObjectId() { return objectId; }
    public String getDetail() { return detail; }
}
