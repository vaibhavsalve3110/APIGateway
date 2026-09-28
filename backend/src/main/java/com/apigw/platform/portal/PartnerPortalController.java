package com.apigw.platform.portal;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import jakarta.validation.Valid;

import org.springframework.web.bind.annotation.RequestBody;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiStatus;
import com.apigw.platform.apis.ApiView;
import com.apigw.platform.apis.ApiService;
import com.apigw.platform.apis.docs.ApiDocumentation;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.gateway.ApisixConfigFactory;
import com.apigw.platform.portal.TryItService.TryItRequest;
import com.apigw.platform.portal.TryItService.TryItResponse;
import com.apigw.platform.keys.KeyViews.GeneratedKey;
import com.apigw.platform.keys.KeyViews.KeyView;
import com.apigw.platform.keys.SecurityKeyService;
import com.apigw.platform.partners.AccessTier;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.partnerusers.PartnerUser;
import com.apigw.platform.partnerusers.PartnerUserRepository;
import com.apigw.platform.partnerusers.PartnerUserRole;
import com.apigw.platform.partners.RecordStatus;
import com.apigw.platform.security.CurrentActor;
import com.apigw.platform.usage.UsageService;
import com.apigw.platform.usage.UsageService.UsageReport;

/**
 * Developer Portal backend. Everything is scoped to the signed-in user's own partner account — the partner id
 * comes from the token, never from the request (DP-08).
 */
@RestController
@RequestMapping("/api/partner")
class PartnerPortalController {

    private final PartnerService partners;
    private final SecurityKeyService keys;
    private final ApiService apis;
    private final UsageService usage;
    private final TryItService tryIt;
    private final PartnerUserRepository partnerUsers;
    private final ApigwProperties props;

    PartnerPortalController(PartnerService partners, SecurityKeyService keys, ApiService apis, UsageService usage,
                            TryItService tryIt, PartnerUserRepository partnerUsers, ApigwProperties props) {
        this.partners = partners;
        this.keys = keys;
        this.apis = apis;
        this.usage = usage;
        this.tryIt = tryIt;
        this.partnerUsers = partnerUsers;
        this.props = props;
    }

    record Me(String code, String name, AccessTier accessTier, RecordStatus status, String clientIdSandbox,
              String clientIdProduction, PartnerUserRole role, boolean canGenerateKeys) {
    }

    record CatalogueApi(UUID id, String name, String category, String httpMethod, String proxyPath, String description,
                        int rateLimitCount, String rateLimitWindow, boolean productionAvailable) {
    }

    @GetMapping("/me")
    Me me() {
        Partner p = current();
        PartnerUserRole role = signedInUser(p).map(PartnerUser::getRole).orElse(null);
        return new Me(p.getCode(), p.getName(), p.getAccessTier(), p.getStatus(), p.getClientIdSandbox(),
                p.getAccessTier() == AccessTier.PRODUCTION ? p.getClientIdProduction() : null,
                role, role == PartnerUserRole.PARTNER_ADMIN);
    }

    /**
     * The partner's catalogue. Until Product / API mapping (CP-PTN-03) is built, every active API is listed;
     * mapping will narrow this to the partner's own entitlements.
     */
    @GetMapping("/apis")
    List<CatalogueApi> catalogue() {
        Partner p = current();
        List<CatalogueApi> result = new ArrayList<>();
        for (ApiView api : apis.list()) {
            if (api.status() == ApiStatus.ACTIVE) {
                result.add(new CatalogueApi(api.id(), api.name(), api.category(), api.httpMethod(), api.proxyPath(),
                        api.description(), api.rateLimitCount(), api.rateLimitWindow().name(),
                        p.getAccessTier() == AccessTier.PRODUCTION && api.backendUrlProduction() != null));
            }
        }
        return result;
    }

    record ApiDetail(UUID id, String name, String category, String httpMethod, String proxyPath, String description,
                     int rateLimitCount, String rateLimitWindow, boolean productionAvailable, String sandboxBaseUrl,
                     String keyHeader, boolean tryItSimulated, ApiDocumentation documentation) {
    }

    /** DP-02: the full documentation of one API in the partner's catalogue. */
    @GetMapping("/apis/{id}")
    ApiDetail api(@PathVariable UUID id) {
        Partner p = current();
        ApiDefinition api = visibleApi(id);
        return new ApiDetail(api.getId(), api.getName(), api.getCategory(), api.getHttpMethod(), api.getProxyPath(),
                api.getDescription(), api.getRateLimitCount(), api.getRateLimitWindow().name(),
                p.getAccessTier() == AccessTier.PRODUCTION && api.getBackendUrlProduction() != null,
                props.tryIt().publicSandboxUrl(), ApisixConfigFactory.KEY_HEADER, props.tryIt().simulate(),
                apis.documentationOf(api));
    }

    /** DP-03: a live test call against the Sandbox, with the partner's own Sandbox key. */
    @PostMapping("/apis/{id}/try")
    TryItResponse tryIt(@PathVariable UUID id, @Valid @RequestBody TryItRequest request) {
        return tryIt.call(current(), visibleApi(id), request);
    }

    /** Same visibility rule as the catalogue: active APIs only (mapping will narrow this further). */
    private ApiDefinition visibleApi(UUID id) {
        ApiDefinition api = apis.requireDefinition(id);
        if (api.getStatus() != ApiStatus.ACTIVE) {
            throw ApiException.notFound("API", id);
        }
        return api;
    }

    @GetMapping("/keys")
    List<KeyView> keys() {
        return keys.list(current().getId());
    }

    /**
     * DP-05: self-service regeneration, for Partner Admins only — a developer or viewer can read the
     * documentation and test, but rotating a live credential is the account owner's decision.
     * The response is the only time the key is shown in the portal.
     */
    @PostMapping("/keys/{environment}")
    @ResponseStatus(HttpStatus.CREATED)
    GeneratedKey generate(@PathVariable Env environment) {
        Partner partner = current();
        requirePartnerAdmin(partner);
        return keys.generate(partner.getId(), environment, CurrentActor.get());
    }

    /** The signed-in user's own record, looked up by the address in their token. */
    private Optional<PartnerUser> signedInUser(Partner partner) {
        return partnerUsers.findByEmail(CurrentActor.get().username().toLowerCase(java.util.Locale.ROOT))
                .filter(u -> u.getPartnerId().equals(partner.getId()));
    }

    private void requirePartnerAdmin(Partner partner) {
        boolean isAdmin = signedInUser(partner)
                .map(u -> u.getRole() == PartnerUserRole.PARTNER_ADMIN && u.getStatus() == RecordStatus.ACTIVE)
                .orElse(false);
        if (!isAdmin) {
            throw ApiException.forbidden("NOT_PARTNER_ADMIN",
                    "Only a Partner Admin of " + partner.getName() + " can generate security keys. "
                            + "Ask your Partner Admin, or your APIM Admin, to rotate the key.");
        }
    }

    @GetMapping("/usage")
    UsageReport usage(@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
                      @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to) {
        Partner p = current();
        List<String> clientIds = new ArrayList<>(List.of(p.getClientIdSandbox()));
        if (p.getClientIdProduction() != null) {
            clientIds.add(p.getClientIdProduction());
        }
        return usage.report(from, to, clientIds);
    }

    private Partner current() {
        return partners.requireByCode(CurrentActor.requirePartnerCode());
    }
}
