package com.apigw.platform.apis;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.gateway.GatewayClient;
import com.apigw.platform.security.Actor;

/** API lifecycle (BRD 5.1.2): add, update, disable, delete — each change pushed to the gateways and audited. */
@Service
public class ApiService {

    static final String AUDIT_TYPE = "API";

    private final ApiRepository repository;
    private final GatewayClient gateway;
    private final AuditService audit;
    private final Clock clock;
    private final Duration coolingPeriod;

    public ApiService(ApiRepository repository, GatewayClient gateway, AuditService audit, Clock clock,
                      ApigwProperties props) {
        this.repository = repository;
        this.gateway = gateway;
        this.audit = audit;
        this.clock = clock;
        this.coolingPeriod = props.apis().deleteCoolingPeriod();
    }

    @Transactional(readOnly = true)
    public List<ApiView> list() {
        return repository.findAllByOrderByNameAsc().stream().map(this::view).toList();
    }

    @Transactional(readOnly = true)
    public ApiView get(UUID id) {
        return view(require(id));
    }

    @Transactional
    public ApiView create(ApiRequest request, Actor actor) {
        Instant now = clock.instant();
        ApiDefinition api = new ApiDefinition(UUID.randomUUID(), now);
        apply(api, request, now);
        repository.saveAndFlush(api);
        gateway.syncApi(api);
        audit.record(actor, "CREATE", AUDIT_TYPE, api.getId(),
                api.getName() + " onboarded at " + api.getHttpMethod() + " " + api.getProxyPath());
        return view(api);
    }

    @Transactional
    public ApiView update(UUID id, ApiRequest request, Actor actor) {
        ApiDefinition api = require(id);
        apply(api, request, clock.instant());
        repository.saveAndFlush(api);
        gateway.syncApi(api);
        audit.record(actor, "UPDATE", AUDIT_TYPE, id, api.getName() + " configuration updated");
        return view(api);
    }

    @Transactional
    public ApiView setGuestVisible(UUID id, boolean visible, Actor actor) {
        ApiDefinition api = require(id);
        api.setGuestVisible(visible, clock.instant());
        audit.record(actor, "UPDATE", AUDIT_TYPE, id, "Visible to guest users set to " + (visible ? "Yes" : "No"));
        return view(api);
    }

    @Transactional
    public ApiView disable(UUID id, Actor actor) {
        ApiDefinition api = require(id);
        api.disable(clock.instant());
        gateway.syncApi(api);
        audit.record(actor, "DISABLE", AUDIT_TYPE, id, api.getName() + " disabled — cooling period started");
        return view(api);
    }

    @Transactional
    public ApiView enable(UUID id, Actor actor) {
        ApiDefinition api = require(id);
        api.enable(clock.instant());
        gateway.syncApi(api);
        audit.record(actor, "ENABLE", AUDIT_TYPE, id, api.getName() + " re-enabled");
        return view(api);
    }

    @Transactional
    public void delete(UUID id, Actor actor) {
        ApiDefinition api = require(id);
        api.assertDeletable(clock.instant(), coolingPeriod);
        repository.delete(api);
        gateway.removeApi(id);
        audit.record(actor, "DELETE", AUDIT_TYPE, id, api.getName() + " deleted permanently");
    }

    private void apply(ApiDefinition api, ApiRequest r, Instant now) {
        api.update(r.name().trim(), r.category().trim(), r.httpMethod(), r.proxyPath().trim(), r.backendUrlSandbox().trim(),
                blankToNull(r.backendUrlProduction()), r.rateLimitCount(), r.rateLimitWindow(),
                blankToNull(r.ownerTeam()), blankToNull(r.description()), now);
    }

    private ApiDefinition require(UUID id) {
        return repository.findById(id).orElseThrow(() -> ApiException.notFound("API", id));
    }

    private ApiView view(ApiDefinition api) {
        return ApiView.of(api, coolingPeriod);
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }
}
