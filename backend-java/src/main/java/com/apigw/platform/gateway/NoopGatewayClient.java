package com.apigw.platform.gateway;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.common.Env;

/** Used when gateway sync is switched off (the no-Docker profile): configuration stays in the database only. */
public class NoopGatewayClient implements GatewayClient {

    private static final Logger log = LoggerFactory.getLogger(NoopGatewayClient.class);

    @Override
    public void syncApi(ApiDefinition api) {
        log.debug("gateway sync disabled — skipped route sync for API {}", api.getId());
    }

    @Override
    public void removeApi(UUID apiId) {
        log.debug("gateway sync disabled — skipped route removal for API {}", apiId);
    }

    @Override
    public void ensureConsumer(Env env, String clientId, String partnerCode, String partnerName) {
        log.debug("gateway sync disabled — skipped consumer {} on {}", clientId, env);
    }

    @Override
    public void putCredential(Env env, String clientId, UUID credentialId, String keyHash) {
        log.debug("gateway sync disabled — skipped credential {} for {}", credentialId, clientId);
    }

    @Override
    public void deleteCredential(Env env, String clientId, UUID credentialId) {
        log.debug("gateway sync disabled — skipped credential removal {} for {}", credentialId, clientId);
    }
}
