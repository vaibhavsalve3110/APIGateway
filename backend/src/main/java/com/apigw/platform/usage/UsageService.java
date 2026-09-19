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
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiRepository;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.usage.UsageRepository.ApiUsageRow;

/** Usage ingestion from the gateways and the API usage report (BRD 5.1.5). */
@Service
public class UsageService {

    private static final Logger log = LoggerFactory.getLogger(UsageService.class);
    /** Gateway route ids look like {@code api-<uuid>-sbx}; see ApisixConfigFactory#routeId. */
    private static final Pattern ROUTE_ID = Pattern.compile("^api-([0-9a-f\\-]{36})-(sbx|prd)$");
    /** CP-RPT-02: default window on first load. */
    public static final Duration DEFAULT_WINDOW = Duration.ofMinutes(15);

    private final UsageRepository usage;
    private final ApiRepository apis;
    private final Clock clock;
    private final Duration retention;

    public UsageService(UsageRepository usage, ApiRepository apis, Clock clock, ApigwProperties props) {
        this.usage = usage;
        this.apis = apis;
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
