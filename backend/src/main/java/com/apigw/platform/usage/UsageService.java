package com.apigw.platform.usage;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiRepository;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerRepository;
import com.apigw.platform.usage.UsageRepository.ApiUsageRow;

/** Usage ingestion from the gateways and the API usage report (BRD 5.1.5). */
@Service
public class UsageService {

    private static final Logger log = LoggerFactory.getLogger(UsageService.class);
    /** Gateway route ids look like {@code api-<uuid>-sbx}; see ApisixConfigFactory#routeId. */
    private static final Pattern ROUTE_ID = Pattern.compile("^api-([0-9a-f\\-]{36})-(sbx|prd)$");
    /** CP-RPT-02: default window on first load. */
    public static final Duration DEFAULT_WINDOW = Duration.ofMinutes(15);

    /** Placeholder id for the "all APIs" case: JPQL needs a non-empty list even when the flag ignores it. */
    private static final UUID ZERO_UUID = new UUID(0, 0);

    private final UsageRepository usage;
    private final ApiRepository apis;
    private final PartnerRepository partners;
    private final Clock clock;
    private final Duration retention;

    public UsageService(UsageRepository usage, ApiRepository apis, PartnerRepository partners, Clock clock,
                        ApigwProperties props) {
        this.usage = usage;
        this.apis = apis;
        this.partners = partners;
        this.clock = clock;
        this.retention = props.usage().retention();
    }

    public record ApiUsage(UUID apiId, String apiName, String proxyPath, long success, long failed,
                           double successRate, Integer minLatencyMs, Integer maxLatencyMs, Integer avgLatencyMs) {
    }

    public record UsageReport(Instant from, Instant to, long totalSuccess, long totalFailed, List<ApiUsage> apis) {
    }

    @Transactional(readOnly = true)
    public UsageReport report(Instant from, Instant to, Collection<String> clientIds) {
        Instant end = to != null ? to : clock.instant();
        Instant start = from != null ? from : end.minus(DEFAULT_WINDOW);
        if (!start.isBefore(end)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_RANGE", "'from' must be before 'to'");
        }
        if (start.isBefore(clock.instant().minus(retention))) {
            start = clock.instant().minus(retention);   // CP-RPT-03: older data is no longer held
        }
        List<ApiUsageRow> rows = clientIds == null
                ? usage.aggregateAll(start, end)
                : clientIds.isEmpty() ? List.of() : usage.aggregateForClients(start, end, clientIds);

        Map<UUID, ApiDefinition> byId = apis.findAllById(rows.stream().map(ApiUsageRow::getApiId).toList()).stream()
                .collect(Collectors.toMap(ApiDefinition::getId, Function.identity()));
        List<ApiUsage> result = new ArrayList<>();
        long success = 0;
        long failed = 0;
        for (ApiUsageRow r : rows) {
            ApiDefinition api = byId.get(r.getApiId());
            long total = r.getSuccess() + r.getFailed();
            result.add(new ApiUsage(r.getApiId(), api != null ? api.getName() : "Deleted API",
                    api != null ? api.getProxyPath() : null, r.getSuccess(), r.getFailed(),
                    total == 0 ? 0 : BigDecimal.valueOf(r.getSuccess() * 100.0 / total).setScale(2, RoundingMode.HALF_UP).doubleValue(),
                    r.getMinLatency(), r.getMaxLatency(),
                    r.getAvgLatency() == null ? null : (int) Math.round(r.getAvgLatency())));
            success += r.getSuccess();
            failed += r.getFailed();
        }
        result.sort(Comparator.comparingLong((ApiUsage u) -> u.success() + u.failed()).reversed());
        return new UsageReport(start, end, success, failed, result);
    }

    @Transactional(readOnly = true)
    public List<String> consumersOf(UUID apiId) {
        return usage.clientsOfApi(apiId, clock.instant().minus(retention));
    }

    /** One line per call, for the log viewer. */
    public record LogEntry(long id, Instant occurredAt, UUID apiId, String apiName, String httpMethod,
                           String proxyPath, Env environment, String clientId, String partnerName,
                           String partnerCode, int statusCode, int latencyMs) {
    }

    /** Which status codes a filter covers; {@code ALL} is everything the gateway reported. */
    public enum StatusFilter {
        ALL(0, 999), SUCCESS(0, 399), CLIENT_ERROR(400, 499), SERVER_ERROR(500, 599), ERROR(400, 999);

        private final int min;
        private final int max;

        StatusFilter(int min, int max) {
            this.min = min;
            this.max = max;
        }
    }

    /**
     * Calls matching the filters, newest first. {@code apiNameLike} matches the API's name or proxy path, so
     * an operator can search the way they think about an API rather than by id.
     */
    @Transactional(readOnly = true)
    public List<LogEntry> logs(Instant from, Instant to, StatusFilter status, String apiNameLike,
                               Collection<String> clientIds, int limit) {
        Instant end = to != null ? to : clock.instant();
        Instant start = from != null ? from : end.minus(DEFAULT_WINDOW);
        if (!start.isBefore(end)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_RANGE", "'from' must be before 'to'");
        }
        StatusFilter effective = status == null ? StatusFilter.ALL : status;

        List<ApiDefinition> allApis = apis.findAll();
        Map<UUID, ApiDefinition> apiById = allApis.stream()
                .collect(Collectors.toMap(ApiDefinition::getId, Function.identity()));
        // An empty search means every API; a search that matches nothing must return nothing, not everything.
        boolean allApiIds = apiNameLike == null || apiNameLike.isBlank();
        List<UUID> apiIds = allApiIds ? List.of() : matching(allApis, apiNameLike);
        if (!allApiIds && apiIds.isEmpty()) {
            return List.of();
        }

        // No client ids means every caller; an empty list means this caller has none, so nothing matches.
        boolean allClients = clientIds == null;
        if (!allClients && clientIds.isEmpty()) {
            return List.of();
        }
        Map<String, Partner> byClientId = partnersByClientId();
        return usage.search(start, end, allClients, allClients ? List.of("") : clientIds,
                        allApiIds, allApiIds ? List.of(ZERO_UUID) : apiIds, effective.min, effective.max,
                        PageRequest.of(0, Math.min(Math.max(limit, 1), 1000)))
                .stream()
                .map(e -> toLogEntry(e, apiById, byClientId))
                .toList();
    }

    /** Counts for the dashboard: the last hour of traffic, plus how much is configured. */
    public record LastHour(Instant from, long success, long failed, double successRate, Integer avgLatencyMs) {
    }

    @Transactional(readOnly = true)
    public LastHour lastHour(Duration window) {
        return summarise(clock.instant().minus(window == null ? Duration.ofHours(1) : window), null);
    }

    /** The same summary for one partner's Client IDs — what they see on their own dashboard. */
    @Transactional(readOnly = true)
    public LastHour summaryFor(Collection<String> clientIds, Duration window) {
        return summarise(clock.instant().minus(window == null ? Duration.ofHours(1) : window), clientIds);
    }

    private LastHour summarise(Instant from, Collection<String> clientIds) {
        var totals = clientIds == null ? usage.totalsSince(from)
                : clientIds.isEmpty() ? null : usage.totalsSinceForClients(from, clientIds);
        long success = totals == null || totals.getSuccess() == null ? 0 : totals.getSuccess();
        long failed = totals == null || totals.getFailed() == null ? 0 : totals.getFailed();
        long total = success + failed;
        Double avg = totals == null ? null : totals.getAvgLatency();
        return new LastHour(from, success, failed,
                total == 0 ? 0 : BigDecimal.valueOf(success * 100.0 / total).setScale(2, RoundingMode.HALF_UP).doubleValue(),
                avg == null ? null : (int) Math.round(avg));
    }

    /** Calls per partner in a window — who is actually using the platform. */
    public record PartnerUsage(String clientId, String partnerName, String partnerCode, long success, long failed,
                               Integer avgLatencyMs) {
    }

    @Transactional(readOnly = true)
    public List<PartnerUsage> byPartner(Duration window) {
        Instant from = clock.instant().minus(window == null ? Duration.ofHours(1) : window);
        Map<String, Partner> byClientId = partnersByClientId();
        return usage.aggregateByClientSince(from).stream()
                .map(r -> {
                    Partner p = byClientId.get(r.getClientId());
                    return new PartnerUsage(r.getClientId(), p == null ? null : p.getName(),
                            p == null ? null : p.getCode(), r.getSuccess(), r.getFailed(),
                            r.getAvgLatency() == null ? null : (int) Math.round(r.getAvgLatency()));
                })
                .sorted(Comparator.comparingLong((PartnerUsage u) -> u.success() + u.failed()).reversed())
                .toList();
    }

    private Map<String, Partner> partnersByClientId() {
        Map<String, Partner> byClientId = new java.util.HashMap<>();
        for (Partner p : partners.findAll()) {
            byClientId.put(p.getClientIdSandbox(), p);
            if (p.getClientIdProduction() != null) {
                byClientId.put(p.getClientIdProduction(), p);
            }
        }
        return byClientId;
    }

    private static List<UUID> matching(List<ApiDefinition> allApis, String search) {
        String needle = search.trim().toLowerCase(java.util.Locale.ROOT);
        return allApis.stream()
                .filter(a -> a.getName().toLowerCase(java.util.Locale.ROOT).contains(needle)
                        || a.getProxyPath().toLowerCase(java.util.Locale.ROOT).contains(needle))
                .map(ApiDefinition::getId)
                .toList();
    }

    private static LogEntry toLogEntry(UsageEvent e, Map<UUID, ApiDefinition> apiById, Map<String, Partner> byClientId) {
        ApiDefinition api = e.getApiId() == null ? null : apiById.get(e.getApiId());
        Partner partner = e.getClientId() == null ? null : byClientId.get(e.getClientId());
        return new LogEntry(e.getId(), e.getOccurredAt(), e.getApiId(),
                api != null ? api.getName() : "Deleted API", api != null ? api.getHttpMethod() : null,
                api != null ? api.getProxyPath() : null, e.getEnvironment(), e.getClientId(),
                partner != null ? partner.getName() : null, partner != null ? partner.getCode() : null,
                e.getStatusCode(), e.getLatencyMs());
    }

    /** Accepts an http-logger batch. Unparseable entries are skipped rather than failing the batch. */
    @Transactional
    public int ingest(List<Map<String, Object>> entries) {
        List<UsageEvent> events = new ArrayList<>(entries.size());
        for (Map<String, Object> e : entries) {
            try {
                events.add(toEvent(e));
            } catch (RuntimeException ex) {
                log.debug("Skipping unparseable usage entry {}", e, ex);
            }
        }
        usage.saveAll(events);
        return events.size();
    }

    @Transactional
    public int purgeExpired() {
        return usage.deleteOlderThan(clock.instant().minus(retention));
    }

    private UsageEvent toEvent(Map<String, Object> e) {
        String routeId = str(e.get("route_id"));
        UUID apiId = null;
        Env env = parseEnv(str(e.get("env")));
        if (routeId != null) {
            Matcher m = ROUTE_ID.matcher(routeId);
            if (m.matches()) {
                apiId = UUID.fromString(m.group(1));
                env = "prd".equals(m.group(2)) ? Env.PRODUCTION : Env.SANDBOX;
            }
        }
        double seconds = num(e.get("request_time"), 0);
        double msec = num(e.get("msec"), clock.millis() / 1000.0);
        String client = str(e.get("client_id"));
        return new UsageEvent(Instant.ofEpochMilli(Math.round(msec * 1000)), apiId, env,
                client == null || client.isBlank() ? null : client,
                (int) num(e.get("status"), 0), (int) Math.round(seconds * 1000));
    }

    private static Env parseEnv(String s) {
        if (s == null) {
            return null;
        }
        try {
            return Env.valueOf(s.toUpperCase());
        } catch (IllegalArgumentException ex) {
            return null;
        }
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private static double num(Object o, double fallback) {
        if (o instanceof Number n) {
            return n.doubleValue();
        }
        if (o instanceof String s && !s.isBlank() && !s.equals("-")) {
            return Double.parseDouble(s);
        }
        return fallback;
    }
}
