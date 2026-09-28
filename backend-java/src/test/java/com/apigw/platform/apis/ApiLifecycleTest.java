package com.apigw.platform.apis;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

class ApiLifecycleTest extends IntegrationTest {

    @Test
    void newApiIsHiddenFromGuestsAndSyncedToTheGateway() throws Exception {
        String body = createApi("/v1/test/guest-default");
        String id = JsonPath.read(body, "$.id");

        assertThat((Boolean) JsonPath.read(body, "$.guestVisible")).isFalse();      // CP-API-05
        assertThat((String) JsonPath.read(body, "$.status")).isEqualTo("ACTIVE");
        assertThat(gateway.calls).contains("syncApi:" + id + ":ACTIVE");
    }

    @Test
    void deletionIsBlockedUntilTheSevenDayCoolingPeriodHasPassed() throws Exception {
        String id = JsonPath.read(createApi("/v1/test/cooling"), "$.id");

        mvc.perform(delete("/api/admin/apis/{id}", id).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("API_NOT_DISABLED"));

        mvc.perform(post("/api/admin/apis/{id}/disable", id).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DISABLED"))
                .andExpect(jsonPath("$.deletableFrom").value(clock.instant().plus(Duration.ofDays(7)).toString()));
        assertThat(gateway.calls).contains("syncApi:" + id + ":DISABLED");   // CP-API-03: route removed

        clock.advance(Duration.ofDays(6));
        mvc.perform(delete("/api/admin/apis/{id}", id).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("COOLING_PERIOD_ACTIVE"));

        clock.advance(Duration.ofDays(1));
        mvc.perform(delete("/api/admin/apis/{id}", id).with(admin()))
                .andExpect(status().isNoContent());
        assertThat(gateway.calls).contains("removeApi:" + id);
        mvc.perform(get("/api/admin/apis/{id}", id).with(admin())).andExpect(status().isNotFound());
    }

    @Test
    void invalidInputIsRejectedWithFieldMessages() throws Exception {
        mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"\",\"category\":\"X\",\"httpMethod\":\"FETCH\",\"proxyPath\":\"no-slash\","
                                + "\"backendUrlSandbox\":\"ftp://x\",\"rateLimitCount\":0,\"rateLimitWindow\":\"MINUTE\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields.httpMethod").exists())
                .andExpect(jsonPath("$.fields.proxyPath").exists())
                .andExpect(jsonPath("$.fields.rateLimitCount").exists());
    }

    @Test
    void rolesAreEnforced() throws Exception {
        mvc.perform(get("/api/admin/apis")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/admin/apis").with(editor())).andExpect(status().isOk());
        mvc.perform(post("/api/admin/apis").with(editor()).contentType(MediaType.APPLICATION_JSON).content(apiJson("/v1/test/editor")))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/admin/partners").with(partnerUser("PTN-99999"))).andExpect(status().isForbidden());
        mvc.perform(get("/api/admin/partners").with(editor())).andExpect(status().isForbidden());
    }

    private String createApi(String path) throws Exception {
        return mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content(apiJson(path)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
    }

    private static String apiJson(String path) {
        return """
                {"name":"Test API %s","category":"Payments","httpMethod":"POST","proxyPath":"%s",
                 "backendUrlSandbox":"http://mock-sandbox:8080/core/test","rateLimitCount":300,"rateLimitWindow":"MINUTE"}
                """.formatted(path, path);
    }
}
