package com.apigw.platform.gateway;

import java.util.EnumMap;
import java.util.Map;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiStatus;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.common.Env;
import com.apigw.platform.config.ApigwProperties;

/** Talks to the APISIX Admin API of the sandbox and production gateways. */
public class ApisixGatewayClient implements GatewayClient {

    private static final Logger log = LoggerFactory.getLogger(ApisixGatewayClient.class);

    private final ApigwProperties props;
    private final Map<Env, RestClient> admin = new EnumMap<>(Env.class);

    public ApisixGatewayClient(ApigwProperties props, RestClient.Builder builder) {
        this.props = props;
        admin.put(Env.SANDBOX, client(builder, props.gateway().sandbox()));
        admin.put(Env.PRODUCTION, client(builder, props.gateway().production()));
    }

    private static RestClient client(RestClient.Builder builder, ApigwProperties.Gateway.Environment env) {
        return builder.clone()
                .baseUrl(env.adminUrl() + "/apisix/admin")
                .defaultHeader("X-API-KEY", env.adminKey())
                .build();
    }

    /** Installs the usage logger on both gateways; a gateway that is down must not stop the portal starting. */
    @EventListener(ApplicationReadyEvent.class)
    public void bootstrap() {
        for (Env env : Env.values()) {
            try {
                put(env, "/global_rules/usage-logger", ApisixConfigFactory.usageLogger(env, props));
                log.info("Usage logger installed on the {} gateway", env);
            } catch (ApiException e) {
                log.warn("Could not configure the {} gateway yet: {}", env, e.getMessage());
            }
        }
    }

    @Override
    public void syncApi(ApiDefinition api) {
        for (Env env : Env.values()) {
            String routeId = ApisixConfigFactory.routeId(api.getId(), env);
            if (api.getStatus() == ApiStatus.ACTIVE && api.backendUrl(env) != null && !api.backendUrl(env).isBlank()) {
                put(env, "/routes/" + routeId, ApisixConfigFactory.route(api, env, props.gateway()));
            } else {
                delete(env, "/routes/" + routeId);
            }
        }
    }

    @Override
    public void removeApi(UUID apiId) {
        for (Env env : Env.values()) {
            delete(env, "/routes/" + ApisixConfigFactory.routeId(apiId, env));
        }
    }

    @Override
    public void ensureConsumer(Env env, String clientId, String partnerCode, String partnerName) {
        put(env, "/consumers", ApisixConfigFactory.consumer(clientId, partnerCode, partnerName));
    }

    @Override
    public void putCredential(Env env, String clientId, UUID credentialId, String keyHash) {
        put(env, "/consumers/" + clientId + "/credentials/" + credentialId, ApisixConfigFactory.credential(keyHash));
    }

    @Override
    public void deleteCredential(Env env, String clientId, UUID credentialId) {
        delete(env, "/consumers/" + clientId + "/credentials/" + credentialId);
    }

    private void put(Env env, String path, Object body) {
        try {
            admin.get(env).put().uri(path).contentType(MediaType.APPLICATION_JSON).body(body).retrieve().toBodilessEntity();
        } catch (RestClientException e) {
            throw unavailable(env, e);
        }
    }

    private void delete(Env env, String path) {
        try {
            admin.get(env).delete().uri(path).retrieve().toBodilessEntity();
        } catch (HttpClientErrorException.NotFound e) {
            // already absent — deleting is idempotent
        } catch (RestClientException e) {
            throw unavailable(env, e);
        }
    }

    private static ApiException unavailable(Env env, RestClientException e) {
        log.error("{} gateway rejected or did not answer an admin call", env, e);
        return new ApiException(HttpStatus.BAD_GATEWAY, "GATEWAY_UNAVAILABLE",
                "The " + env.name().toLowerCase() + " gateway could not be updated: " + e.getMessage());
    }
}
