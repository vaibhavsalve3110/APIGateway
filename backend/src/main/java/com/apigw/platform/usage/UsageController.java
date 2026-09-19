package com.apigw.platform.usage;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.common.ApiException;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.usage.UsageService.UsageReport;

@RestController
class UsageController {

    private final UsageService usage;
    private final byte[] ingestHeader;

    UsageController(UsageService usage, ApigwProperties props) {
        this.usage = usage;
        this.ingestHeader = ("Ingest " + props.usage().ingestToken()).getBytes(StandardCharsets.UTF_8);
    }

    /** CP-RPT-01/02: filter by date-time range and Client ID; defaults to the last 15 minutes. */
    @GetMapping("/api/admin/usage/report")
    UsageReport report(@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
                       @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to,
                       @RequestParam(required = false) String clientId) {
        return usage.report(from, to, clientId == null || clientId.isBlank() ? null : List.of(clientId.trim()));
    }

    /** CP-RPT-04: who depends on this API, from 30 days of traffic. */
    @GetMapping("/api/admin/usage/apis/{apiId}/consumers")
    List<String> consumers(@PathVariable UUID apiId) {
        return usage.consumersOf(apiId);
    }

    /** Receives http-logger batches from the gateways. */
    @PostMapping("/internal/usage/batch")
    Map<String, Integer> ingest(@RequestHeader(name = "Authorization", required = false) String authorization,
                                @RequestBody List<Map<String, Object>> entries) {
        if (authorization == null
                || !MessageDigest.isEqual(ingestHeader, authorization.getBytes(StandardCharsets.UTF_8))) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "BAD_INGEST_TOKEN", "Invalid ingest token");
        }
        return Map.of("accepted", usage.ingest(entries));
    }
}
