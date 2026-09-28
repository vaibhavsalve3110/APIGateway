package com.apigw.platform.apis;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/** CP-API-07: headers, request body and one response per HTTP status code are stored with the API. */
class ApiDocumentationTest extends IntegrationTest {

    @Test
    void documentationIsSavedAndReturnedWithTheApi() throws Exception {
        String created = mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Documented Transfer","category":"Payments","httpMethod":"POST","proxyPath":"/v1/test/documented",
                         "backendUrlSandbox":"http://mock-sandbox:8080/core/imps","rateLimitCount":300,"rateLimitWindow":"MINUTE",
                         "documentation":{
                           "queryParameters":[{"name":"dryRun","type":"boolean","required":false,"example":"true"}],
                           "requestHeaders":[{"name":"X-Request-Id","type":"string(uuid)","required":true,"description":"Idempotency key"}],
                           "requestBodyFields":[{"name":"amount","type":"string","required":true,"example":"250.00"}],
                           "requestBodyExample":"{\\"amount\\":\\"250.00\\"}",
                           "responseHeaders":[{"name":"X-RateLimit-Remaining","type":"integer","required":true,"example":"299"}],
                           "responses":[
                             {"statusCode":200,"description":"Accepted","bodyExample":"{\\"status\\":\\"ACCEPTED\\"}",
                              "bodyFields":[{"name":"status","type":"string","required":true}]},
                             {"statusCode":400,"description":"Invalid amount","bodyExample":"{\\"code\\":\\"VALIDATION_FAILED\\"}"}
                           ]}}
                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.documentation.source").value("MANUAL"))
                .andReturn().getResponse().getContentAsString();
        String id = JsonPath.read(created, "$.id");

        mvc.perform(get("/api/admin/apis/{id}", id).with(editor()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.documentation.queryParameters[0].name").value("dryRun"))
                .andExpect(jsonPath("$.documentation.requestHeaders[0].required").value(true))
                .andExpect(jsonPath("$.documentation.requestBodyFields[0].name").value("amount"))
                .andExpect(jsonPath("$.documentation.requestBodyExample").value("{\"amount\":\"250.00\"}"))
                .andExpect(jsonPath("$.documentation.responseHeaders[0].name").value("X-RateLimit-Remaining"))
                .andExpect(jsonPath("$.documentation.responses.length()").value(2))
                .andExpect(jsonPath("$.documentation.responses[1].statusCode").value(400))
                .andExpect(jsonPath("$.documentation.responses[0].bodyFields[0].type").value("string"))
                .andExpect(jsonPath("$.documentation.statusCodesUnique").doesNotExist());
    }

    @Test
    void eachStatusCodeMayOnlyBeDocumentedOnce() throws Exception {
        mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Twice 200","category":"Payments","httpMethod":"GET","proxyPath":"/v1/test/twice",
                         "backendUrlSandbox":"http://mock-sandbox:8080/x","rateLimitCount":10,"rateLimitWindow":"MINUTE",
                         "documentation":{"responses":[{"statusCode":200},{"statusCode":200}]}}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields['documentation.statusCodesUnique']").exists());

        mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Bad code","category":"Payments","httpMethod":"GET","proxyPath":"/v1/test/badcode",
                         "backendUrlSandbox":"http://mock-sandbox:8080/x","rateLimitCount":10,"rateLimitWindow":"MINUTE",
                         "documentation":{"responses":[{"statusCode":999}],"requestHeaders":[{"name":""}]}}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.fields['documentation.responses[0].statusCode']").exists())
                .andExpect(jsonPath("$.fields['documentation.requestHeaders[0].name']").exists());
    }

    @Test
    void anApiCanBeCreatedAsADraftAndStaysOffTheGateway() throws Exception {
        String created = mvc.perform(post("/api/admin/apis").with(admin()).contentType(MediaType.APPLICATION_JSON).content("""
                        {"name":"Imported Draft","category":"Imported","httpMethod":"GET","proxyPath":"/v1/test/draft",
                         "backendUrlSandbox":"http://mock-sandbox:8080/x","rateLimitCount":10,"rateLimitWindow":"MINUTE",
                         "status":"DRAFT","documentation":{"source":"OPENAPI"}}
                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("DRAFT"))
                .andReturn().getResponse().getContentAsString();
        String id = JsonPath.read(created, "$.id");
        assertThat(gateway.calls).contains("syncApi:" + id + ":DRAFT");   // sync with DRAFT = no route

        mvc.perform(post("/api/admin/apis/{id}/enable", id).with(admin()))
                .andExpect(jsonPath("$.status").value("ACTIVE"));
    }
}
