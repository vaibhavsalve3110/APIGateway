package com.apigw.platform.usage;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

import com.apigw.platform.common.Env;
import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/** The dashboard counts and the API log viewer (BRD CP-RPT-01, CP-RPT-02). */
class ApiLogsTest extends IntegrationTest {

    @Autowired
    private UsageRepository usage;

    /** The dashboard counts every call in the window, so this class works from an empty usage table. */
    @org.junit.jupiter.api.BeforeEach
    void clearUsage() {
        usage.deleteAll();
    }

    /** Records a call as the gateway's log shipper would, but straight into the table. */
    private void call(String apiId, String clientId, int status, int latencyMs, Instant at) {
        usage.save(new UsageEvent(at, java.util.UUID.fromString(apiId), Env.SANDBOX, clientId, status, latencyMs));
    }

    private String anApi(String name, String path) throws Exception {
        String created = mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"%s","category":"Payments","httpMethod":"POST","proxyPath":"%s",
                                 "backendUrlSandbox":"http://mock-sandbox:8080/core","rateLimitCount":100,
                                 "rateLimitWindow":"MINUTE"}
                                """.formatted(name, path)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(created, "$.id");
    }

    @Test
    void theDashboardCountsWhatIsConfiguredAndTheLastHourOfTraffic() throws Exception {
        String payments = anApi("Logs Payments", "/v1/logs/payments");
        Instant now = clock.instant();
        call(payments, "acme-sbx", 200, 120, now.minusSeconds(60));
        call(payments, "acme-sbx", 200, 140, now.minusSeconds(50));
        call(payments, "acme-sbx", 500, 900, now.minusSeconds(40));
        // Older than the window: must not be counted.
        call(payments, "acme-sbx", 500, 900, now.minusSeconds(7_200));

        mvc.perform(get("/api/admin/dashboard").with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.counts.apis").value(org.hamcrest.Matchers.greaterThanOrEqualTo(1)))
                .andExpect(jsonPath("$.counts.activeApis").value(org.hamcrest.Matchers.greaterThanOrEqualTo(1)))
                .andExpect(jsonPath("$.counts.partners").exists())
                .andExpect(jsonPath("$.counts.partnerUsers").exists())
                .andExpect(jsonPath("$.lastHour.success").value(2))
                .andExpect(jsonPath("$.lastHour.failed").value(1))
                .andExpect(jsonPath("$.lastHour.successRate").value(66.67))
                .andExpect(jsonPath("$.topApis[0].apiName").value("Logs Payments"));

        // An Editor may read the dashboard; a partner may not.
        mvc.perform(get("/api/admin/dashboard").with(editor())).andExpect(status().isOk());
        mvc.perform(get("/api/admin/dashboard").with(partnerUser("PTN-00001"))).andExpect(status().isForbidden());
    }

    @Test
    void logsCanBeFilteredByStatusApiNameAndClient() throws Exception {
        String refunds = anApi("Logs Refunds", "/v1/logs/refunds");
        String balances = anApi("Logs Balances", "/v1/logs/balances");
        Instant now = clock.instant();
        call(refunds, "acme-sbx", 200, 100, now.minusSeconds(30));
        call(refunds, "kavery-sbx", 404, 80, now.minusSeconds(20));
        call(balances, "acme-sbx", 503, 1_500, now.minusSeconds(10));

        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString()).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(3))
                // Newest first.
                .andExpect(jsonPath("$[0].apiName").value("Logs Balances"))
                .andExpect(jsonPath("$[0].statusCode").value(503));

        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString())
                        .param("status", "SERVER_ERROR").with(admin()))
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].statusCode").value(503));

        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString())
                        .param("status", "ERROR").with(admin()))
                .andExpect(jsonPath("$.length()").value(2));

        // Search matches the API name or its path.
        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString())
                        .param("search", "refunds").with(admin()))
                .andExpect(jsonPath("$.length()").value(2));

        // Per Client ID: the "who called us" view.
        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString())
                        .param("clientId", "kavery-sbx").with(admin()))
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].clientId").value("kavery-sbx"));

        // A search that matches no API returns nothing rather than everything.
        mvc.perform(get("/api/admin/usage/logs").param("from", now.minusSeconds(300).toString())
                        .param("search", "nothing-matches-this").with(admin()))
                .andExpect(jsonPath("$.length()").value(0));

        mvc.perform(get("/api/admin/usage/logs").with(partnerUser("PTN-00001"))).andExpect(status().isForbidden());
    }
}
