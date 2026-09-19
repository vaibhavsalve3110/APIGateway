package com.apigw.platform.usage;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

class UsageReportTest extends IntegrationTest {

    private static final String INGEST = "Ingest change-me-ingest-token";

    @Test
    void ingestRequiresTheIngestToken() throws Exception {
        mvc.perform(post("/internal/usage/batch").contentType(MediaType.APPLICATION_JSON).content("[]"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/internal/usage/batch").header("Authorization", "Ingest wrong")
                        .contentType(MediaType.APPLICATION_JSON).content("[]"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void reportAggregatesSuccessFailureAndLatencyPerApiForTheChosenClient() throws Exception {
        String api = mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Usage Test API","category":"Accounts","httpMethod":"GET","proxyPath":"/v1/test/usage",
                         "backendUrlSandbox":"http://mock-sandbox:8080/core/balance","rateLimitCount":100,"rateLimitWindow":"MINUTE"}
                        """))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        String apiId = JsonPath.read(api, "$.id");
        double nowSeconds = clock.instant().getEpochSecond();
        String route = "api-" + apiId + "-sbx";

        // http-logger sends every value as a string when log_format is used.
        String batch = """
                [
                 {"env":"SANDBOX","route_id":"%1$s","client_id":"usage-a-sbx","status":"200","request_time":"0.080","msec":"%2$s"},
                 {"env":"SANDBOX","route_id":"%1$s","client_id":"usage-a-sbx","status":"200","request_time":"0.120","msec":"%2$s"},
                 {"env":"SANDBOX","route_id":"%1$s","client_id":"usage-a-sbx","status":"429","request_time":"0.004","msec":"%2$s"},
                 {"env":"SANDBOX","route_id":"%1$s","client_id":"usage-b-sbx","status":"200","request_time":"0.300","msec":"%2$s"},
                 {"env":"SANDBOX","route_id":"","client_id":"","status":"404","request_time":"0.001","msec":"%2$s"},
                 {"garbage":true}
                ]
                """.formatted(route, nowSeconds - 60);
        mvc.perform(post("/internal/usage/batch").header("Authorization", INGEST)
                        .contentType(MediaType.APPLICATION_JSON).content(batch))
                .andExpect(status().isOk());

        clock.advance(Duration.ofSeconds(1));
        mvc.perform(get("/api/admin/usage/report").param("clientId", "usage-a-sbx").with(editor()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.apis.length()").value(1))
                .andExpect(jsonPath("$.apis[0].apiName").value("Usage Test API"))
                .andExpect(jsonPath("$.apis[0].success").value(2))
                .andExpect(jsonPath("$.apis[0].failed").value(1))
                .andExpect(jsonPath("$.apis[0].minLatencyMs").value(4))
                .andExpect(jsonPath("$.apis[0].maxLatencyMs").value(120))
                .andExpect(jsonPath("$.apis[0].avgLatencyMs").value(68));

        // Default window is the last 15 minutes: once the calls are older, they drop out.
        clock.advance(Duration.ofMinutes(16));
        mvc.perform(get("/api/admin/usage/report").param("clientId", "usage-a-sbx").with(admin()))
                .andExpect(jsonPath("$.apis.length()").value(0));
    }
}
