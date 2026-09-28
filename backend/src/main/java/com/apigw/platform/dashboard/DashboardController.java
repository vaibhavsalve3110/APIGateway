package com.apigw.platform.dashboard;

import java.time.Duration;
import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.apis.ApiRepository;
import com.apigw.platform.apis.ApiStatus;
import com.apigw.platform.partners.PartnerRepository;
import com.apigw.platform.partners.RecordStatus;
import com.apigw.platform.partnerusers.PartnerUserRepository;
import com.apigw.platform.usage.UsageService;
import com.apigw.platform.usage.UsageService.ApiUsage;
import com.apigw.platform.usage.UsageService.LastHour;
import com.apigw.platform.usage.UsageService.PartnerUsage;

/**
 * The Management Portal landing page: what is configured, and what the gateways did in the last hour.
 * Readable by Admin and Editor (see SecurityConfig), like the API list and usage report.
 */
@RestController
@RequestMapping("/api/admin/dashboard")
class DashboardController {

    private final ApiRepository apis;
    private final PartnerRepository partners;
    private final PartnerUserRepository partnerUsers;
    private final UsageService usage;

    DashboardController(ApiRepository apis, PartnerRepository partners, PartnerUserRepository partnerUsers,
                        UsageService usage) {
        this.apis = apis;
        this.partners = partners;
        this.partnerUsers = partnerUsers;
        this.usage = usage;
    }

    record Counts(long apis, long activeApis, long draftApis, long disabledApis,
                  long partners, long activePartners, long productionPartners, long partnerUsers) {
    }

    record Dashboard(Counts counts, LastHour lastHour, List<ApiUsage> topApis, List<PartnerUsage> topPartners) {
    }

    @GetMapping
    Dashboard summary(@RequestParam(defaultValue = "PT1H") Duration window) {
        var allApis = apis.findAll();
        var allPartners = partners.findAll();
        Counts counts = new Counts(
                allApis.size(),
                allApis.stream().filter(a -> a.getStatus() == ApiStatus.ACTIVE).count(),
                allApis.stream().filter(a -> a.getStatus() == ApiStatus.DRAFT).count(),
                allApis.stream().filter(a -> a.getStatus() == ApiStatus.DISABLED).count(),
                allPartners.size(),
                allPartners.stream().filter(p -> p.getStatus() == RecordStatus.ACTIVE).count(),
                allPartners.stream().filter(p -> p.getClientIdProduction() != null).count(),
                partnerUsers.count());

        LastHour lastHour = usage.lastHour(window);
        // The same window as the headline figures, so the tables explain the numbers above them.
        List<ApiUsage> topApis = usage.report(lastHour.from(), null, null).apis().stream().limit(5).toList();
        List<PartnerUsage> topPartners = usage.byPartner(window).stream().limit(5).toList();
        return new Dashboard(counts, lastHour, topApis, topPartners);
    }
}
