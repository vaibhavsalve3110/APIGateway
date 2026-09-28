package com.apigw.platform.errors;

import java.time.Clock;
import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Keeps the error log to {@code apigw.errors.retention} (30 days by default), like usage records.
 * Audit rows are never purged — those are evidence; these are diagnostics.
 */
@Component
@ConditionalOnProperty(name = "apigw.scheduling.enabled", havingValue = "true", matchIfMissing = true)
class ErrorRetentionJob {

    private static final Logger log = LoggerFactory.getLogger(ErrorRetentionJob.class);

    private final ErrorLogService errors;
    private final Clock clock;
    private final Duration retention;

    ErrorRetentionJob(ErrorLogService errors, Clock clock,
                      @Value("${apigw.errors.retention:P30D}") Duration retention) {
        this.errors = errors;
        this.clock = clock;
        this.retention = retention;
    }

    @Scheduled(cron = "${apigw.errors.retention-cron:0 45 2 * * *}")
    void run() {
        try {
            int deleted = errors.purgeBefore(clock.instant().minus(retention));
            if (deleted > 0) {
                log.info("Purged {} error records older than {}", deleted, retention);
            }
        } catch (RuntimeException e) {
            log.error("Error-log retention purge failed; will retry on the next run", e);
        }
    }
}
