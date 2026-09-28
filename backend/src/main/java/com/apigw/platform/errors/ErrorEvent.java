package com.apigw.platform.errors;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One thing that went wrong. Append-only; see V6__error_event.sql for why it is not the audit log. */
@Entity
@Table(name = "error_event")
public class ErrorEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(nullable = false)
    private String source;

    @Column(nullable = false)
    private String code;

    @Column(nullable = false, length = 1000)
    private String message;

    @Column(length = 8000)
    private String detail;

    private String actor;

    private String request;

    @Column(name = "client_ip")
    private String clientIp;

    @Column(nullable = false)
    private String reference;

    protected ErrorEvent() {
    }

    ErrorEvent(Instant occurredAt, String source, String code, String message, String detail, String actor,
               String request, String clientIp, String reference) {
        this.occurredAt = occurredAt;
        this.source = source;
        this.code = code;
        this.message = message;
        this.detail = detail;
        this.actor = actor;
        this.request = request;
        this.clientIp = clientIp;
        this.reference = reference;
    }

    public Long getId() {
        return id;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }

    public String getSource() {
        return source;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }

    public String getDetail() {
        return detail;
    }

    public String getActor() {
        return actor;
    }

    public String getRequest() {
        return request;
    }

    public String getClientIp() {
        return clientIp;
    }

    public String getReference() {
        return reference;
    }
}
