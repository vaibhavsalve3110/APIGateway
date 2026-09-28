package com.apigw.platform.auth;

import java.time.Clock;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerRepository;
import com.apigw.platform.partners.RecordStatus;
import com.apigw.platform.partnerusers.PartnerUser;
import com.apigw.platform.partnerusers.PartnerUserRepository;

/**
 * Resolves the e-mail entered at sign-in to an account, across both portals.
 *
 * <p>A partner user can sign in only while their own access is granted and their organization is active, so
 * revoking either (CP-PTN-04) stops sign-in at the next code request.
 */
@Service
public class LoginIdentityService {

    private final PlatformUserRepository platformUsers;
    private final PartnerUserRepository partnerUsers;
    private final PartnerRepository partners;
    private final Clock clock;

    public LoginIdentityService(PlatformUserRepository platformUsers, PartnerUserRepository partnerUsers,
                                PartnerRepository partners, Clock clock) {
        this.platformUsers = platformUsers;
        this.partnerUsers = partnerUsers;
        this.partners = partners;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public Optional<LoginIdentity> find(String rawEmail) {
        String email = rawEmail == null ? "" : rawEmail.trim().toLowerCase(Locale.ROOT);
        if (email.isEmpty()) {
            return Optional.empty();
        }
        Optional<LoginIdentity> internal = platformUsers.findByEmail(email)
                .filter(u -> u.getStatus() == RecordStatus.ACTIVE)
                .map(u -> new LoginIdentity(u.getEmail(), u.getFullName(), Set.of(u.getRole().name()), null));
        if (internal.isPresent()) {
            return internal;
        }
        return partnerUsers.findByEmail(email)
                .filter(u -> u.getStatus() == RecordStatus.ACTIVE)
                .flatMap(this::toPartnerIdentity);
    }

    private Optional<LoginIdentity> toPartnerIdentity(PartnerUser user) {
        return partners.findById(user.getPartnerId())
                .filter(p -> p.getStatus() == RecordStatus.ACTIVE)
                .map((Partner p) -> new LoginIdentity(user.getEmail(), user.getFullName(), Set.of("PARTNER"), p.getCode()));
    }

    /** Records a successful sign-in for internal users; partner sign-ins are covered by the audit log. */
    @Transactional
    public void recordSignIn(LoginIdentity identity) {
        if (!identity.isPartner()) {
            platformUsers.findByEmail(identity.email()).ifPresent(u -> u.signedIn(clock.instant()));
        }
    }
}
