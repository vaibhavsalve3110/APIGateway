package com.apigw.platform.usage;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** CP-RPT-03: deletes usage records older than the retention period, nightly at 02:30. */
@Component
class UsageRetentionJob {

    private static final Logger log = LoggerFactory.getLogger(UsageRetentionJob.class);

    private final UsageService usage;

    UsageRetentionJob(UsageService usage) {
        this.usage = usage;
    }

    @Scheduled(cron = "${apigw.usage.retention-cron:0 30 2 * * *}")
    void run() {
        int deleted = usage.purgeExpired();
        if (deleted > 0) {
            log.info("Purged {} usage records past the retention period", deleted);
        }
    }
}
