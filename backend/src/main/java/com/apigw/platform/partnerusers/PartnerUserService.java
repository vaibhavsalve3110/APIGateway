package com.apigw.platform.partnerusers;

import java.time.Clock;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.partners.RecordStatus;
import com.apigw.platform.partnerusers.PartnerUserDtos.CreateRequest;
import com.apigw.platform.partnerusers.PartnerUserDtos.PartnerUserView;
import com.apigw.platform.partnerusers.PartnerUserDtos.UpdateRequest;
import com.apigw.platform.security.Actor;

/**
 * Portal logins belonging to an organization (CP-PTN-04).
 *
 * <p>Users are logins only. The signature key pair and IPV salt belong to the organization
 * ({@link com.apigw.platform.partners.PartnerCredentialService}), so every user of one organization shares
 * them, and adding or removing a user never changes the credentials the partner integrates with.
 */
@Service
public class PartnerUserService {

    static final String AUDIT_TYPE = "PARTNER_USER";

    private final PartnerUserRepository users;
    private final PartnerService partners;
    private final AuditService audit;
    private final Clock clock;

    public PartnerUserService(PartnerUserRepository users, PartnerService partners,
                              AuditService audit, Clock clock) {
        this.users = users;
        this.partners = partners;
        this.audit = audit;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<PartnerUserView> list(UUID partnerId) {
        List<PartnerUser> found = partnerId == null
                ? users.findAllByOrderByFullNameAsc()
                : users.findByPartnerIdOrderByFullNameAsc(partners.require(partnerId).getId());
        return found.stream().map(this::toView).toList();
    }

    @Transactional(readOnly = true)
    public PartnerUserView view(UUID id) {
        return toView(require(id));
    }

    /** Adds a login for an organization. Credentials are the organization's and are not touched here. */
    @Transactional
    public PartnerUserView create(UUID partnerId, CreateRequest request, Actor actor) {
        Partner partner = partners.require(partnerId);
        if (partner.getStatus() == RecordStatus.DISABLED) {
            throw ApiException.conflict("PARTNER_DISABLED",
                    "Partner " + partner.getName() + " is disabled — re-enable it before adding users");
        }
        String email = normalise(request.email());
        if (users.existsByEmail(email)) {
            throw ApiException.conflict("EMAIL_IN_USE", "A partner user with email " + email + " already exists");
        }

        PartnerUser user = new PartnerUser(UUID.randomUUID(), partner.getId(), email, request.fullName().trim(),
                request.role(), actor.username(), clock.instant());
        users.saveAndFlush(user);

        audit.record(actor, "CREATE", AUDIT_TYPE, user.getId(),
                "Portal user " + email + " added to " + partner.getName() + " (" + partner.getCode()
                        + ") as " + request.role());
        return toView(user, partner);
    }

    /** Name, role and email can all be corrected; the email is the portal sign-in, so it stays unique. */
    @Transactional
    public PartnerUserView update(UUID id, UpdateRequest request, Actor actor) {
        PartnerUser user = require(id);
        String previousEmail = user.getEmail();
        String email = normalise(request.email());
        if (!email.equals(previousEmail) && users.existsByEmail(email)) {
            throw ApiException.conflict("EMAIL_IN_USE", "A partner user with email " + email + " already exists");
        }
        user.updateProfile(request.fullName().trim(), email, request.role(), clock.instant());
        audit.record(actor, "UPDATE", AUDIT_TYPE, id, email.equals(previousEmail)
                ? "Portal user " + email + " updated; role " + request.role()
                : "Portal user email changed from " + previousEmail + " to " + email + "; role " + request.role());
        return toView(user);
    }

    /** CP-PTN-04: grant or revoke this user's access to the Developer Portal. */
    @Transactional
    public PartnerUserView setAccess(UUID id, RecordStatus status, Actor actor) {
        PartnerUser user = require(id);
        if (user.getStatus() == status) {
            return toView(user);
        }
        user.setStatus(status, clock.instant());
        audit.record(actor, status == RecordStatus.DISABLED ? "REVOKE_ACCESS" : "GRANT_ACCESS", AUDIT_TYPE, id,
                "Developer Portal access " + (status == RecordStatus.DISABLED ? "revoked from " : "granted to ")
                        + user.getEmail());
        return toView(user);
    }

    /**
     * Removes a login for good. Access must be revoked first, so deletion is always a deliberate second step
     * on an account already known to be out of use — the same shape as deleting an API, which must be
     * disabled first (CP-RPT-05). The audit trail of what the user did stays behind.
     */
    @Transactional
    public void delete(UUID id, Actor actor) {
        PartnerUser user = require(id);
        if (user.getStatus() != RecordStatus.DISABLED) {
            throw ApiException.conflict("ACCESS_NOT_REVOKED",
                    "Revoke " + user.getEmail() + "'s access before deleting the account");
        }
        Partner partner = partners.require(user.getPartnerId());
        users.delete(user);
        audit.record(actor, "DELETE", AUDIT_TYPE, id,
                "Portal user " + user.getEmail() + " deleted from " + partner.getName()
                        + " (" + partner.getCode() + ")");
    }

    private PartnerUser require(UUID id) {
        return users.findById(id).orElseThrow(() -> ApiException.notFound("Partner user", id));
    }

    private static String normalise(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    private PartnerUserView toView(PartnerUser user) {
        return toView(user, partners.require(user.getPartnerId()));
    }

    private PartnerUserView toView(PartnerUser user, Partner partner) {
        return PartnerUserView.of(user, partner.getCode(), partner.getName());
    }
}
