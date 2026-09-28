package com.apigw.platform.keys;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.apigw.platform.errors.ErrorLogService;

/**
 * Closes elapsed overlap windows. Runs every 15 seconds, so a replaced key stops working within
 * 15 seconds of its 20-minute window ending.
 */
@Component
class KeyExpiryJob {

    private static final Logger log = LoggerFactory.getLogger(KeyExpiryJob.class);

    private final SecurityKeyService keys;
    private final ErrorLogService errors;

    KeyExpiryJob(SecurityKeyService keys, ErrorLogService errors) {
        this.keys = keys;
        this.errors = errors;
    }

    @Scheduled(fixedDelayString = "${apigw.keys.expiry-check-interval:PT15S}")
    void run() {
        try {
            keys.expireDueKeys();
        } catch (RuntimeException e) {
            // A gateway outage must not kill the scheduler; the key stays EXPIRING and is retried next run.
            log.error("Key expiry run failed; will retry", e);
            errors.record(ErrorLogService.SCHEDULER, "KEY_EXPIRY_FAILED",
                    "The key expiry sweep failed and will be retried: " + e.getMessage(), e);
        }
    }
}
