package com.apigw.platform.demo;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import com.apigw.platform.apis.ApiRequest;
import com.apigw.platform.apis.ApiService;
import com.apigw.platform.apis.ApiView;
import com.apigw.platform.apis.RateWindow;
import com.apigw.platform.common.Env;
import com.apigw.platform.partners.AccessTier;
import com.apigw.platform.partners.PartnerDtos.GroupRequest;
import com.apigw.platform.partners.PartnerDtos.GroupView;
import com.apigw.platform.partners.PartnerDtos.PartnerRequest;
import com.apigw.platform.partners.PartnerDtos.PartnerView;
import com.apigw.platform.partners.PartnerRepository;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.security.Actor;
import com.apigw.platform.usage.UsageEvent;
import com.apigw.platform.usage.UsageRepository;

/**
 * Seeds the partners, APIs and 24 hours of synthetic traffic shown in the screen designs. Runs only under the
 * {@code demo} profile and only into an empty database. Partner codes are deterministic (Acme = PTN-00001) because
 * the Keycloak demo realm maps the partner user to that code.
 */
@Component
@Profile("demo")
class DemoDataSeeder implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(DemoDataSeeder.class);
    private static final Actor SEED = new Actor("demo-seed", Set.of("ADMIN"), null);
    private static final String MOCK_SANDBOX = "http://mock-sandbox:8080";
    private static final String MOCK_PRODUCTION = "http://mock-production:8080";

    private final PartnerService partners;
    private final PartnerRepository partnerRepository;
    private final ApiService apis;
    private final UsageRepository usage;
    private final Clock clock;

    DemoDataSeeder(PartnerService partners, PartnerRepository partnerRepository, ApiService apis,
                   UsageRepository usage, Clock clock) {
        this.partners = partners;
        this.partnerRepository = partnerRepository;
        this.apis = apis;
        this.usage = usage;
        this.clock = clock;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (partnerRepository.count() > 0) {
            log.info("Demo data already present — skipping seed");
            return;
        }
        try {
            seed();
        } catch (RuntimeException e) {
            log.error("Demo seed failed (is the gateway running? set GATEWAY_SYNC_ENABLED=false to seed without it)", e);
        }
    }

    private void seed() {
        GroupView tier1 = partners.createGroup(new GroupRequest("Tier-1 Aggregators", "Large payment aggregators"), SEED);
        GroupView tier2 = partners.createGroup(new GroupRequest("Tier-2 Partners", "Regional fintech partners"), SEED);
        GroupView broking = partners.createGroup(new GroupRequest("Broking Partners", "Stock-broking integrations"), SEED);
        partners.createGroup(new GroupRequest("Internal Consumers", "In-house channels using the gateway"), SEED);

        PartnerView acme = partners.create(new PartnerRequest("Acme Fintech Pvt Ltd", tier1.id(), "integrations@acmefintech.in"), SEED);
        PartnerView kavery = partners.create(new PartnerRequest("Kavery Payments", tier2.id(), "integrations@kaverypayments.in"), SEED);
        partners.create(new PartnerRequest("Northstar Capital", tier1.id(), "api@northstarcapital.in"), SEED);
        partners.create(new PartnerRequest("Meridian Broking", broking.id(), "apisupport@meridianbroking.in"), SEED);
        partners.changeTier(kavery.id(), AccessTier.PRODUCTION, SEED);

        List<ApiView> created = new ArrayList<>();
        created.add(api("Fund Transfer — IMPS", "Payments", "POST", "/v1/payments/imps", "/core/imps", 300,
                "Initiates an immediate IMPS credit to a beneficiary registered under the partner's own account."));
        created.add(api("Fund Transfer — NEFT", "Payments", "POST", "/v1/payments/neft", "/core/neft", 300,
                "Batch-settled NEFT transfer; settlement confirmed by callback."));
        created.add(api("Account Balance Enquiry", "Accounts", "GET", "/v1/accounts/balance", "/core/balance", 1200,
                "Current and available balance for an account linked to the partner."));
        created.add(api("Statement Download", "Accounts", "GET", "/v1/accounts/statement", "/core/statement", 120,
                "Transaction statement for up to 90 days."));
        ApiView ifsc = api("IFSC Branch Lookup", "Reference", "GET", "/v1/reference/ifsc", "/ref/ifsc", 240,
                "Branch and bank details for an IFSC code.");
        apis.setGuestVisible(ifsc.id(), true, SEED);
        created.add(ifsc);
        ApiView mandate = api("Mandate Registration", "Payments", "POST", "/v1/mandates/register", "/core/mandates", 60,
                "Registers a recurring debit mandate.");
        apis.disable(mandate.id(), SEED);

        seedUsage(created, List.of(acme.clientIdSandbox(), kavery.clientIdSandbox(),
                partnerRepository.findById(kavery.id()).orElseThrow().getClientIdProduction()));
        log.info("Demo data seeded: 4 partner groups, 4 partners, 6 APIs, 24 h of synthetic usage");
    }

    private ApiView api(String name, String category, String method, String path, String backendPath, int limit,
                        String description) {
        return apis.create(new ApiRequest(name, category, method, path, MOCK_SANDBOX + backendPath,
                MOCK_PRODUCTION + backendPath, limit, RateWindow.MINUTE, "Integrations", description), SEED);
    }

    /** Deterministic synthetic traffic so the usage report has something to show on first run. */
    private void seedUsage(List<ApiView> apiViews, List<String> clientIds) {
        Random random = new Random(42);
        Map<String, Integer> baseLatency = Map.of("Payments", 210, "Accounts", 90, "Reference", 25);
        Instant now = clock.instant();
        List<UsageEvent> events = new ArrayList<>();
        for (int i = 0; i < 3_000; i++) {
            ApiView api = apiViews.get(random.nextInt(apiViews.size()));
            String client = clientIds.get(random.nextInt(clientIds.size()));
            int base = baseLatency.getOrDefault(api.category(), 100);
            int latency = (int) Math.max(5, base * (0.5 + random.nextDouble() * 1.4));
            int status = random.nextDouble() < 0.03 ? (random.nextBoolean() ? 429 : 503) : 200;
            Instant at = now.minus(Duration.ofSeconds(random.nextInt(86_400)));
            events.add(new UsageEvent(at, api.id(), client.endsWith("-prd") ? Env.PRODUCTION : Env.SANDBOX,
                    client, status, latency));
        }
        usage.saveAll(events);
    }
}
