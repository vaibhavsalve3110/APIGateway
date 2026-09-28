package com.apigw.platform.usage;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.apigw.platform.errors.ErrorLogService;

/** CP-RPT-03: deletes usage records older than the retention period, nightly at 02:30. */
@Component
class UsageRetentionJob {

    private static final Logger log = LoggerFactory.getLogger(UsageRetentionJob.class);

    private final UsageService usage;

    private final ErrorLogService errors;

    UsageRetentionJob(UsageService usage, ErrorLogService errors) {
        this.usage = usage;
        this.errors = errors;
    }

    @Scheduled(cron = "${apigw.usage.retention-cron:0 30 2 * * *}")
    void run() {
        try {
            int deleted = usage.purgeExpired();
            if (deleted > 0) {
                log.info("Purged {} usage records past the retention period", deleted);
            }
        } catch (RuntimeException e) {
            // Retention silently stopping is how a disk fills up, so it is recorded where an operator looks.
            log.error("Usage retention purge failed; will retry on the next run", e);
            errors.record(ErrorLogService.SCHEDULER, "USAGE_PURGE_FAILED",
                    "The usage retention purge failed: " + e.getMessage(), e);
        }
    }
}
