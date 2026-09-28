package com.apigw.platform.auth;

import java.time.Clock;
import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.apigw.platform.errors.ErrorLogService;

/** Expired one-time codes are of no further use; clear them hourly so the table stays small. */
@Component
@ConditionalOnProperty(name = "apigw.scheduling.enabled", havingValue = "true", matchIfMissing = true)
class OtpCleanupJob {

    private static final Logger log = LoggerFactory.getLogger(OtpCleanupJob.class);

    private final OtpChallengeRepository challenges;
    private final ErrorLogService errors;
    private final Clock clock;

    OtpCleanupJob(OtpChallengeRepository challenges, ErrorLogService errors, Clock clock) {
        this.challenges = challenges;
        this.errors = errors;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "PT1H")
    void purge() {
        try {
            int removed = challenges.deleteExpired(clock.instant().minus(Duration.ofHours(1)));
            if (removed > 0) {
                log.debug("Purged {} expired sign-in codes", removed);
            }
        } catch (RuntimeException e) {
            log.error("Sign-in code cleanup failed; will retry on the next run", e);
            errors.record(ErrorLogService.SCHEDULER, "OTP_PURGE_FAILED",
                    "The sign-in code cleanup failed: " + e.getMessage(), e);
        }
    }
}
