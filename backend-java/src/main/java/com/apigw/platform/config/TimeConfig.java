package com.apigw.platform.config;

import java.time.Clock;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

@Configuration
public class TimeConfig {

    /** All time-dependent rules (key overlap, cooling period, retention) read the time from this clock. */
    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }

    @Configuration
    @EnableScheduling
    @ConditionalOnProperty(name = "apigw.scheduling.enabled", havingValue = "true", matchIfMissing = true)
    static class SchedulingConfig {
    }
}
