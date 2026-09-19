package com.apigw.platform.support;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.common.Env;
import com.apigw.platform.gateway.GatewayClient;

/** Controllable time and a gateway that records every call, shared by the integration tests. */
@TestConfiguration(proxyBeanMethods = false)
public class TestSupport {

    @Bean
    @Primary
    public MutableClock mutableClock() {
        return new MutableClock(Instant.parse("2026-09-14T08:00:00Z"));
    }

    @Bean
    @Primary
    public RecordingGateway recordingGateway() {
        return new RecordingGateway();
    }

    public static final class MutableClock extends Clock {

        private volatile Instant now;

        MutableClock(Instant start) {
            this.now = start;
        }

        public void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public Instant instant() {
            return now;
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }
    }

    public static final class RecordingGateway implements GatewayClient {

        public final List<String> calls = new CopyOnWriteArrayList<>();

        @Override
        public void syncApi(ApiDefinition api) {
            calls.add("syncApi:" + api.getId() + ":" + api.getStatus());
        }

        @Override
        public void removeApi(UUID apiId) {
            calls.add("removeApi:" + apiId);
        }

        @Override
        public void ensureConsumer(Env env, String clientId, String partnerCode, String partnerName) {
            calls.add("ensureConsumer:" + env + ":" + clientId);
        }

        @Override
        public void putCredential(Env env, String clientId, UUID credentialId, String keyHash) {
            calls.add("putCredential:" + env + ":" + clientId + ":" + credentialId + ":" + keyHash);
        }

        @Override
        public void deleteCredential(Env env, String clientId, UUID credentialId) {
            calls.add("deleteCredential:" + env + ":" + clientId + ":" + credentialId);
        }
    }
}
