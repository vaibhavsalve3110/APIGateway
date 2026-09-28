package com.apigw.platform.partners;

import java.text.Normalizer;
import java.time.Clock;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.gateway.GatewayClient;
import com.apigw.platform.partners.PartnerDtos.GroupRequest;
import com.apigw.platform.partners.PartnerDtos.GroupView;
import com.apigw.platform.partners.PartnerDtos.PartnerRequest;
import com.apigw.platform.partners.PartnerDtos.IssuedCredentials;
import com.apigw.platform.partners.PartnerDtos.PartnerView;
import com.apigw.platform.partners.PartnerDtos.UpdateRequest;
import com.apigw.platform.security.Actor;

/** Partner groups, partners and their access tier (BRD 5.1.3). */
@Service
public class PartnerService {

    static final String AUDIT_PARTNER = "PARTNER";
    static final String AUDIT_GROUP = "PARTNER_GROUP";

    private final PartnerRepository partners;
    private final PartnerGroupRepository groups;
    private final GatewayClient gateway;
    private final PartnerCredentialService credentials;
    private final AuditService audit;
    private final ApplicationEventPublisher events;
    private final Clock clock;

    public PartnerService(PartnerRepository partners, PartnerGroupRepository groups, GatewayClient gateway,
                          PartnerCredentialService credentials, AuditService audit,
                          ApplicationEventPublisher events, Clock clock) {
        this.partners = partners;
        this.groups = groups;
        this.gateway = gateway;
        this.credentials = credentials;
        this.audit = audit;
        this.events = events;
        this.clock = clock;
    }

    // ---------------------------------------------------------------- groups

    @Transactional(readOnly = true)
    public List<GroupView> listGroups() {
        return groups.findAllByOrderByNameAsc().stream()
                .map(g -> new GroupView(g.getId(), g.getName(), g.getDescription(), g.getStatus(),
                        partners.countByGroupId(g.getId())))
                .toList();
    }

    @Transactional
    public GroupView createGroup(GroupRequest request, Actor actor) {
        PartnerGroup group = new PartnerGroup(UUID.randomUUID(), request.name().trim(), request.description(), clock.instant());
        groups.saveAndFlush(group);
        audit.record(actor, "CREATE", AUDIT_GROUP, group.getId(), "Partner group " + group.getName() + " created");
        return new GroupView(group.getId(), group.getName(), group.getDescription(), group.getStatus(), 0);
    }

    // ---------------------------------------------------------------- partners

    @Transactional(readOnly = true)
    public List<PartnerView> listPartners() {
        Map<UUID, String> groupNames = groups.findAll().stream()
                .collect(Collectors.toMap(PartnerGroup::getId, PartnerGroup::getName));
        return partners.findAllByOrderByNameAsc().stream()
                .map(p -> PartnerView.of(p, groupNames.get(p.getGroupId())))
                .toList();
    }

    @Transactional(readOnly = true)
    public PartnerView view(UUID id) {
        return toView(require(id));
    }

    @Transactional(readOnly = true)
    public Partner require(UUID id) {
        return partners.findById(id).orElseThrow(() -> ApiException.notFound("Partner", id));
    }

    @Transactional(readOnly = true)
    public Partner requireByCode(String code) {
        return partners.findByCode(code).orElseThrow(() -> ApiException.notFound("Partner", code));
    }

    /**
     * Registers an organization: issues its Client ID, gateway consumer, signature key pair and IPV salt.
     * The private key and salt are returned once, here, and never again.
     */
    @Transactional
    public IssuedCredentials create(PartnerRequest request, Actor actor) {
        PartnerGroup group = groups.findById(request.groupId())
                .orElseThrow(() -> ApiException.notFound("Partner group", request.groupId()));
        String name = request.name().trim();
        Partner partner = new Partner(UUID.randomUUID(), nextCode(), name, group.getId(), request.contactEmail(),
                uniqueClientId(name, Env.SANDBOX), clock.instant());
        // The id is assigned, so save() merges: keep the managed copy, or later changes are lost.
        Partner saved = partners.saveAndFlush(partner);
        gateway.ensureConsumer(Env.SANDBOX, saved.getClientIdSandbox(), saved.getCode(), saved.getName());
        audit.record(actor, "CREATE", AUDIT_PARTNER, saved.getId(),
                saved.getName() + " (" + saved.getCode() + ") added to " + group.getName()
                        + " with UAT-only access; sandbox Client ID " + saved.getClientIdSandbox());
        IssuedCredentials issued = credentials.issueInitial(saved, actor);
        return credentials.withView(issued, PartnerView.of(saved, group.getName()));
    }

    /** CP-PTN-02: correct the organization's name or contact address. */
    @Transactional
    public PartnerView update(UUID id, UpdateRequest request, Actor actor) {
        Partner partner = require(id);
        String before = partner.getName() + " <" + (partner.getContactEmail() == null ? "" : partner.getContactEmail()) + ">";
        partner.updateDetails(request.name().trim(),
                request.contactEmail() == null || request.contactEmail().isBlank() ? null : request.contactEmail().trim(),
                clock.instant());
        audit.record(actor, "UPDATE", AUDIT_PARTNER, id,
                "Organization details changed from " + before + " to " + partner.getName()
                        + " <" + (partner.getContactEmail() == null ? "" : partner.getContactEmail()) + ">");
        return toView(partner);
    }

    /** CP-PTN-05 / CP-PTN-06. Granting Production issues a Production Client ID on the Production gateway. */
    @Transactional
    public PartnerView changeTier(UUID id, AccessTier tier, Actor actor) {
        Partner partner = require(id);
        AccessTier previous = partner.getAccessTier();
        if (previous == tier) {
            return toView(partner);
        }
        String productionClientId = partner.getClientIdProduction() != null
                ? partner.getClientIdProduction() : uniqueClientId(partner.getName(), Env.PRODUCTION);
        partner.changeTier(tier, productionClientId, clock.instant());
        if (tier == AccessTier.PRODUCTION) {
            gateway.ensureConsumer(Env.PRODUCTION, partner.getClientIdProduction(), partner.getCode(), partner.getName());
        } else {
            events.publishEvent(new PartnerEvents.ProductionAccessRevoked(partner, actor));
        }
        audit.record(actor, "ACCESS_TIER", AUDIT_PARTNER, id, "Access tier changed from " + previous + " to " + tier);
        return toView(partner);
    }

    @Transactional
    public PartnerView setStatus(UUID id, RecordStatus status, Actor actor) {
        Partner partner = require(id);
        if (partner.getStatus() == status) {
            return toView(partner);
        }
        partner.setStatus(status, clock.instant());
        if (status == RecordStatus.DISABLED) {
            events.publishEvent(new PartnerEvents.PartnerDisabled(partner, actor));
        }
        audit.record(actor, status == RecordStatus.DISABLED ? "DISABLE" : "ENABLE", AUDIT_PARTNER, id,
                partner.getName() + (status == RecordStatus.DISABLED ? " disabled — all keys revoked" : " re-enabled"));
        return toView(partner);
    }

    private PartnerView toView(Partner p) {
        String groupName = groups.findById(p.getGroupId()).map(PartnerGroup::getName).orElse(null);
        return PartnerView.of(p, groupName);
    }

    private String nextCode() {
        long n = partners.count() + 1;
        String code;
        do {
            code = String.format("PTN-%05d", n++);
        } while (partners.existsByCode(code));
        return code;
    }

    /** Client IDs double as gateway consumer names, so they are restricted to [a-z0-9-]. */
    private String uniqueClientId(String partnerName, Env env) {
        String slug = Normalizer.normalize(partnerName, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("\\b(pvt|private|ltd|limited|llp|inc)\\b", "")
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("(^-+|-+$)", "");
        if (slug.length() > 40) {
            slug = slug.substring(0, 40).replaceAll("-+$", "");
        }
        if (slug.isEmpty()) {
            slug = "partner";
        }
        for (int i = 1; ; i++) {
            String clientId = (i == 1 ? slug : slug + "-" + i) + "-" + env.shortCode();
            if (!partners.existsByClientIdSandboxOrClientIdProduction(clientId, clientId)) {
                return clientId;
            }
        }
    }
}
