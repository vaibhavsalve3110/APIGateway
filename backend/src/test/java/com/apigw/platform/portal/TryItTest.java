package com.apigw.platform.portal;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.hamcrest.Matchers;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/** DP-02 / DP-03: partners read the documentation and test live — Sandbox only, with their own key. */
class TryItTest extends IntegrationTest {

    private String partnerCode;
    private String partnerId;
    private String apiId;
    private String sandboxKey;

    @BeforeEach
    void setUp() throws Exception {
        String partner = createPartner("Try It Payments");
        partnerCode = JsonPath.read(partner, "$.code");
        partnerId = JsonPath.read(partner, "$.id");
        String api = mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Transfer status","category":"Payments","httpMethod":"GET",
                         "proxyPath":"/v1/test/try/%s/{txnId}",
                         "backendUrlSandbox":"http://mock-sandbox:8080/core/status","rateLimitCount":60,"rateLimitWindow":"MINUTE",
                         "documentation":{
                           "queryParameters":[{"name":"verbose","required":true,"example":"true"}],
                           "responseHeaders":[{"name":"X-RateLimit-Remaining","example":"59"}],
                           "responses":[{"statusCode":200,"description":"Found","bodyExample":"{\\"status\\":\\"SETTLED\\"}"},
                                        {"statusCode":400,"description":"Bad input","bodyExample":"{\\"code\\":\\"BAD\\"}"}]}}
                        """.formatted(partnerCode)))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        apiId = JsonPath.read(api, "$.id");
        String key = mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(partnerCode)))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        sandboxKey = JsonPath.read(key, "$.plaintext");
    }

    @Test
    void partnerSeesTheFullDocumentation() throws Exception {
        mvc.perform(get("/api/partner/apis/{id}", apiId).with(partnerUser(partnerCode)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.keyHeader").value("X-Security-Key"))
                .andExpect(jsonPath("$.tryItSimulated").value(true))
                .andExpect(jsonPath("$.documentation.responses[*].statusCode", Matchers.contains(200, 400)))
                .andExpect(jsonPath("$.backendUrlSandbox").doesNotExist());   // internal URLs never reach partners
    }

    @Test
    void validSandboxKeyReturnsTheDocumentedSuccessResponse() throws Exception {
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"apiKey\":\"%s\",\"pathParams\":{\"txnId\":\"IMPS 1/2\"},\"query\":{\"verbose\":\"true\"}}".formatted(sandboxKey)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value(200))
                .andExpect(jsonPath("$.simulated").value(true))
                .andExpect(jsonPath("$.body").value("{\"status\":\"SETTLED\"}"))
                .andExpect(jsonPath("$.headers['X-RateLimit-Remaining']").value("59"))
                .andExpect(jsonPath("$.requestUrl").value(Matchers.containsString("/IMPS%201%2F2?verbose=true")));
    }

    @Test
    void missingRequiredQueryParameterReturnsTheDocumented400() throws Exception {
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"apiKey\":\"%s\",\"pathParams\":{\"txnId\":\"T1\"}}".formatted(sandboxKey)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value(400))
                .andExpect(jsonPath("$.body").value("{\"code\":\"BAD\"}"));
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"apiKey\":\"%s\"}".formatted(sandboxKey)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("MISSING_PATH_PARAMETER"));
    }

    @Test
    void wrongOrForeignKeysAreRejectedAndProductionKeysNeverWork() throws Exception {
        String call = "{\"apiKey\":\"%s\",\"pathParams\":{\"txnId\":\"T1\"},\"query\":{\"verbose\":\"true\"}}";
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content(call.formatted("agw_sbx_not-a-real-key")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_KEY"));

        // Another partner's valid key is not accepted either.
        String other = createPartner("Try It Other");
        String otherKey = JsonPath.read(mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(JsonPath.read(other, "$.code"))))
                .andReturn().getResponse().getContentAsString(), "$.plaintext");
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content(call.formatted(otherKey)))
                .andExpect(status().isUnauthorized());

        mvc.perform(put("/api/admin/partners/{id}/access-tier", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"accessTier\":\"PRODUCTION\"}"))
                .andExpect(status().isOk());
        String prodKey = JsonPath.read(mvc.perform(post("/api/partner/keys/PRODUCTION").with(partnerUser(partnerCode)))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString(), "$.plaintext");
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content(call.formatted(prodKey)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("SANDBOX_ONLY"));
    }

    @Test
    void disabledApisAreNotShownOrCallable() throws Exception {
        mvc.perform(post("/api/admin/apis/{id}/disable", apiId).with(admin())).andExpect(status().isOk());
        mvc.perform(get("/api/partner/apis/{id}", apiId).with(partnerUser(partnerCode))).andExpect(status().isNotFound());
        mvc.perform(post("/api/partner/apis/{id}/try", apiId).with(partnerUser(partnerCode)).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"apiKey\":\"%s\"}".formatted(sandboxKey)))
                .andExpect(status().isNotFound());
    }
}
