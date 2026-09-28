package com.apigw.platform.auth;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One one-time code sent to an e-mail address. Only the hash is kept, and attempts are counted. */
@Entity
@Table(name = "otp_challenge")
public class OtpChallenge {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String email;

    @Column(name = "code_hash", nullable = false)
    private String codeHash;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false)
    private Instant expiresAt;

    @Column(nullable = false)
    private int attempts;

    @Column(name = "consumed_at")
    private Instant consumedAt;

    @Column(name = "client_ip")
    private String clientIp;

    protected OtpChallenge() {
    }

    public OtpChallenge(UUID id, String email, String codeHash, Instant now, Instant expiresAt, String clientIp) {
        this.id = id;
        this.email = email;
        this.codeHash = codeHash;
        this.createdAt = now;
        this.expiresAt = expiresAt;
        this.attempts = 0;
        this.clientIp = clientIp;
    }

    public boolean isUsable(Instant now, int maxAttempts) {
        return consumedAt == null && attempts < maxAttempts && now.isBefore(expiresAt);
    }

    public void countAttempt() {
        this.attempts++;
    }

    public void consume(Instant now) {
        this.consumedAt = now;
    }

    public UUID getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }

    public String getCodeHash() {
        return codeHash;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public int getAttempts() {
        return attempts;
    }

    public Instant getConsumedAt() {
        return consumedAt;
    }

    public String getClientIp() {
        return clientIp;
    }
}
