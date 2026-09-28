package com.apigw.platform.keys;

import java.time.Instant;
import java.util.UUID;

import com.apigw.platform.common.Env;

/**
 * Raised after a security key is issued, so notifications are sent once the rotation has actually committed
 * — never for a rotation that then failed.
 *
 * @param plaintext the new key; it exists only in memory and in this event, and is e-mailed to the
 *                  organization's Partner Admins when {@code apigw.keys.email-key-to-admin} is on
 * @param byPartner true when a partner generated it themselves, false when an APIM Admin did
 */
public record KeyGeneratedEvent(UUID partnerId, String partnerCode, String partnerName, Env environment,
                                String maskedKey, String plaintext, String clientId, Instant previousExpiresAt,
                                String actorUsername, boolean byPartner) {
}
