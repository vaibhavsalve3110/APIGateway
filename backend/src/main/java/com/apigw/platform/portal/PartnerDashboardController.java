package com.apigw.platform.portal;

import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;

import com.apigw.platform.apis.ApiService;
import com.apigw.platform.keys.KeyStatus;
import com.apigw.platform.keys.SecurityKeyService;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.products.ProductService;
import com.apigw.platform.security.CurrentActor;
import com.apigw.platform.usage.UsageService;
import com.apigw.platform.usage.UsageService.ApiUsage;
import com.apigw.platform.usage.UsageService.LastHour;
import com.apigw.platform.usage.UsageService.LogEntry;
import com.apigw.platform.usage.UsageService.StatusFilter;

/**
 * The partner's own dashboard: what they are entitled to, and what their integration has actually been
 * doing (BRD DP-02, CP-RPT-01 from the partner's side).
 *
 * <p>Everything is scoped by the Client IDs on the signed-in user's own partner account, taken from the
 * token. A partner cannot widen that by changing a parameter, and never sees another organization's traffic.
 */
@RestController
@RequestMapping("/api/partner")
class PartnerDashboardController {

    private final PartnerService partners;
    private final SecurityKeyService keys;
    private final ApiService apis;
    private final ProductService products;
    private final UsageService usage;
    private final Clock clock;

    PartnerDashboardController(PartnerService partners, SecurityKeyService keys, ApiService apis,
                               ProductService products, UsageService usage, Clock clock) {
        this.partners = partners;
        this.keys = keys;
        this.apis = apis;
        this.products = products;
        this.usage = usage;
        this.clock = clock;
    }

    record Counts(int apisAvailable, int products, long activeKeys, boolean productionAvailable) {
    }

    record PartnerDashboard(String partnerName, String partnerCode, Counts counts, LastHour window,
                            List<ApiUsage> apis, List<LogEntry> recentCalls) {
    }

    /** Defaults to the last 24 hours; the portal offers 1 h, 24 h, 7 d and 30 d. */
    @GetMapping("/dashboard")
    PartnerDashboard dashboard(@RequestParam(defaultValue = "PT24H") Duration window) {
        Partner partner = me();
        List<String> clientIds = clientIdsOf(partner);
        // The application's clock, not the wall clock: they differ under test and on a shifted host.
        Instant from = clock.instant().minus(window);

        // Everything defaults to zero on a quiet account: an empty dashboard is a fact, not an error.
        Counts counts = new Counts(
                (int) apis.list().stream().filter(a -> a.status() == com.apigw.platform.apis.ApiStatus.ACTIVE).count(),
                products.forPartner(partner.getId(), CurrentActor.get().username()).size(),
                keys.list(partner.getId()).stream()
                        .filter(k -> k.status() == KeyStatus.ACTIVE || k.status() == KeyStatus.EXPIRING).count(),
                partner.getClientIdProduction() != null);

        return new PartnerDashboard(partner.getName(), partner.getCode(), counts,
                usage.summaryFor(clientIds, window),
                usage.report(from, null, clientIds).apis(),
                usage.logs(from, null, StatusFilter.ALL, null, clientIds, 25));
    }

    /** The partner's own call history, with the same filters the Management Portal offers. */
    @GetMapping("/usage/logs")
    List<LogEntry> logs(@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
                        @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to,
                        @RequestParam(required = false) StatusFilter status,
                        @RequestParam(required = false) String search,
                        @RequestParam(defaultValue = "200") int limit) {
        return usage.logs(from, to, status, search, clientIdsOf(me()), limit);
    }

    private static List<String> clientIdsOf(Partner partner) {
        List<String> ids = new ArrayList<>();
        ids.add(partner.getClientIdSandbox());
        if (partner.getClientIdProduction() != null) {
            ids.add(partner.getClientIdProduction());
        }
        return ids;
    }

    private Partner me() {
        return partners.requireByCode(CurrentActor.requirePartnerCode());
    }
}
