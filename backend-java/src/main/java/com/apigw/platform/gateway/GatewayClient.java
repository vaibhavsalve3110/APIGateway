package com.apigw.platform.gateway;

import java.util.UUID;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.common.Env;

/**
 * Pushes the control plane's configuration to the runtime gateways. Each environment is a separate
 * gateway deployment, so a sandbox credential never exists on the Production gateway (GW-05).
 */
public interface GatewayClient {

    /** Creates or updates the API's route on every environment it has a backend for; removes it where it is not active. */
    void syncApi(ApiDefinition api);

    void removeApi(UUID apiId);

    /** One gateway consumer per Client ID; rate limits are counted per consumer (GW-04). */
    void ensureConsumer(Env env, String clientId, String partnerCode, String partnerName);

    /** Stores only the SHA-256 hash of the key as the credential (CP-SEC-09). */
    void putCredential(Env env, String clientId, UUID credentialId, String keyHash);

    void deleteCredential(Env env, String clientId, UUID credentialId);
}
