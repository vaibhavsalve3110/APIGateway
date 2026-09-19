package com.apigw.platform.partners;

import com.apigw.platform.security.Actor;

/** Published inside the partner's transaction so dependent modules (keys) react atomically. */
public final class PartnerEvents {

    private PartnerEvents() {
    }

    /** Production access was withdrawn: every Production key must stop working (BRD constraint 8.2). */
    public record ProductionAccessRevoked(Partner partner, Actor actor) {
    }

    /** The partner account was disabled: none of its keys may authenticate any more. */
    public record PartnerDisabled(Partner partner, Actor actor) {
    }
}
