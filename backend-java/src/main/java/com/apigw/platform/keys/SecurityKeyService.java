package com.apigw.platform.keys;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.gateway.GatewayClient;
import com.apigw.platform.keys.KeyViews.GeneratedKey;
import com.apigw.platform.keys.KeyViews.KeyView;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerEvents;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.security.Actor;

/**
 * Security key lifecycle per BRD v1.3:
 * <ul>
 *   <li>CP-SEC-08 — the key is returned once, at generation, and never again;</li>
 *   <li>CP-SEC-09 — only its SHA-256 hash is stored (here and at the gateway);</li>
 *   <li>CP-SEC-04/05 — a new key starts a 20-minute overlap during which the previous key still works,
 *       and no further key can be generated until that window closes;</li>
 *   <li>CP-SEC-06 — an Admin may revoke the new key inside the window, reinstating the previous one;</li>
 *   <li>CP-SEC-07 — every step is audited, with "System" as the actor for automatic expiry.</li>
 * </ul>
 */
@Service
public class SecurityKeyService {

    private static final Logger log = LoggerFactory.getLogger(SecurityKeyService.class);
    static final String AUDIT_TYPE = "SECURITY_KEY";
    private static final Set<KeyStatus> LIVE = EnumSet.of(KeyStatus.ACTIVE, KeyStatus.EXPIRING);

    private final SecurityKeyRepository keys;
    private final PartnerService partners;
    private final GatewayClient gateway;
    private final AuditService audit;
    private final Clock clock;
    private final Duration overlap;
    private final org.springframework.context.ApplicationEventPublisher events;

    public SecurityKeyService(SecurityKeyRepository keys, PartnerService partners, GatewayClient gateway,
                              AuditService audit, org.springframework.context.ApplicationEventPublisher events,
                              Clock clock, ApigwProperties props) {
        this.keys = keys;
        this.partners = partners;
        this.gateway = gateway;
        this.audit = audit;
        this.events = events;
        this.clock = clock;
        this.overlap = props.keys().overlapWindow();
    }

    /**
     * Checks a key a partner pasted into the Developer Portal's "Try it" panel. It must be theirs, live, and a
     * Sandbox key — Production is never callable from the portal (DP-03).
     */
    @Transactional(readOnly = true)
    public void assertUsableSandboxKey(UUID partnerId, String plaintext) {
        SecurityKey key = plaintext == null ? null
                : keys.findByKeyHash(KeyMaterial.sha256Hex(plaintext.trim())).orElse(null);
        if (key == null || !key.getPartnerId().equals(partnerId)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_KEY",
                    "This key is not valid for your account. Paste the Sandbox key you stored when you created it.");
        }
        if (key.getEnvironment() != Env.SANDBOX) {
            throw ApiException.forbidden("SANDBOX_ONLY",
                    "Production keys cannot be used from the portal — use a Sandbox key. Test calls only reach the Sandbox.");
        }
        if (!key.getStatus().isLive()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "KEY_NOT_ACTIVE",
                    "This key is " + key.getStatus().name().toLowerCase() + ". Use your current Sandbox key.");
        }
    }

    @Transactional(readOnly = true)
    public List<KeyView> list(UUID partnerId) {
        Instant now = clock.instant();
        return keys.findByPartnerIdOrderByCreatedAtDesc(partnerId).stream().map(k -> KeyView.of(k, now)).toList();
    }

    @Transactional
    public GeneratedKey generate(UUID partnerId, Env env, Actor actor) {
        Partner partner = partners.require(partnerId);
        if (!partner.isActive()) {
            throw ApiException.conflict("PARTNER_DISABLED", partner.getName() + " is disabled — keys cannot be issued");
        }
        if (!partner.getAccessTier().allows(env)) {
            throw ApiException.forbidden("PRODUCTION_NOT_PROVISIONED",
                    partner.getName() + " is on the UAT-only access tier — Production keys cannot be issued");
        }
        List<SecurityKey> live = keys.findByPartnerIdAndEnvironmentAndStatusIn(partnerId, env, LIVE);
        live.stream().filter(k -> k.getStatus() == KeyStatus.EXPIRING).findFirst().ifPresent(k -> {
            throw ApiException.conflict("ROTATION_WINDOW_OPEN",
                    "A key rotation is already in progress. The previous key expires at " + k.getExpiresAt()
                            + "; a new key can be generated after that.");
        });

        Instant now = clock.instant();
        Instant previousExpiresAt = null;
        for (SecurityKey current : live) {            // at most one ACTIVE key exists here
            previousExpiresAt = now.plus(overlap);
            current.startOverlap(previousExpiresAt);
        }

        KeyMaterial material = KeyMaterial.generate(env);
        SecurityKey key = new SecurityKey(UUID.randomUUID(), partnerId, env, material, actor.username(), now);
        keys.saveAndFlush(key);

        String clientId = partner.clientId(env);
        gateway.ensureConsumer(env, clientId, partner.getCode(), partner.getName());
        gateway.putCredential(env, clientId, key.getId(), material.hash());

        audit.record(actor, "GENERATE", AUDIT_TYPE, key.getId(),
                env + " key " + material.masked() + " generated for " + partner.getCode()
                        + (previousExpiresAt == null ? "" : "; previous key stays valid until " + previousExpiresAt));
        // Notifications go out after this transaction commits — see KeyNotificationListener.
        events.publishEvent(new KeyGeneratedEvent(partnerId, partner.getCode(), partner.getName(), env,
                material.masked(), material.plaintext(), clientId, previousExpiresAt, actor.username(),
                actor.hasRole("PARTNER")));
        return new GeneratedKey(KeyView.of(key, now), material.plaintext(), clientId, previousExpiresAt);
    }

    /** CP-SEC-06: only a key that replaced another, and only while the previous key is still in its window. */
    @Transactional
    public KeyView revokeNewKey(UUID keyId, Actor actor) {
        SecurityKey key = keys.findById(keyId).orElseThrow(() -> ApiException.notFound("Security key", keyId));
        Instant now = clock.instant();
        SecurityKey previous = keys.findByPartnerIdAndEnvironmentAndStatusIn(key.getPartnerId(), key.getEnvironment(),
                        EnumSet.of(KeyStatus.EXPIRING)).stream()
                .filter(k -> k.getExpiresAt() != null && now.isBefore(k.getExpiresAt()))
                .findFirst()
                .orElse(null);
        if (key.getStatus() != KeyStatus.ACTIVE || previous == null) {
            throw ApiException.conflict("REVOKE_WINDOW_CLOSED",
                    "Only a newly generated key can be revoked, and only while the previous key is still within "
                            + "its " + overlap.toMinutes() + "-minute overlap window");
        }
        Partner partner = partners.require(key.getPartnerId());
        key.revoke(now);
        previous.reinstate();
        gateway.deleteCredential(key.getEnvironment(), partner.clientId(key.getEnvironment()), key.getId());
        audit.record(actor, "REVOKE", AUDIT_TYPE, key.getId(),
                key.getEnvironment() + " key " + key.getMaskedKey() + " revoked within the overlap window; "
                        + previous.getMaskedKey() + " reinstated as the active key");
        return KeyView.of(key, now);
    }

    /** Ends overlap windows that have elapsed. Called by {@link KeyExpiryJob}. */
    @Transactional
    public int expireDueKeys() {
        Instant now = clock.instant();
        List<SecurityKey> due = keys.findByStatusAndExpiresAtLessThanEqual(KeyStatus.EXPIRING, now);
        for (SecurityKey key : due) {
            Partner partner = partners.require(key.getPartnerId());
            key.expire(now);
            gateway.deleteCredential(key.getEnvironment(), partner.clientId(key.getEnvironment()), key.getId());
            audit.record(Actor.SYSTEM, "EXPIRE", AUDIT_TYPE, key.getId(),
                    key.getEnvironment() + " key " + key.getMaskedKey() + " expired at the end of the "
                            + overlap.toMinutes() + "-minute overlap window");
        }
        if (!due.isEmpty()) {
            log.info("Expired {} security key(s) at the end of their overlap window", due.size());
        }
        return due.size();
    }

    @EventListener
    void onProductionAccessRevoked(PartnerEvents.ProductionAccessRevoked event) {
        revokeAll(event.partner(), EnumSet.of(Env.PRODUCTION), event.actor(), "Production access withdrawn");
    }

    @EventListener
    void onPartnerDisabled(PartnerEvents.PartnerDisabled event) {
        revokeAll(event.partner(), EnumSet.allOf(Env.class), event.actor(), "partner disabled");
    }

    private void revokeAll(Partner partner, Set<Env> envs, Actor actor, String reason) {
        Instant now = clock.instant();
        for (SecurityKey key : keys.findByPartnerIdAndStatusIn(partner.getId(), LIVE)) {
            if (!envs.contains(key.getEnvironment())) {
                continue;
            }
            key.revoke(now);
            if (key.getEnvironment() == Env.SANDBOX || partner.getClientIdProduction() != null) {
                gateway.deleteCredential(key.getEnvironment(), partner.clientId(key.getEnvironment()), key.getId());
            }
            audit.record(actor, "REVOKE", AUDIT_TYPE, key.getId(),
                    key.getEnvironment() + " key " + key.getMaskedKey() + " revoked — " + reason);
        }
    }
}
