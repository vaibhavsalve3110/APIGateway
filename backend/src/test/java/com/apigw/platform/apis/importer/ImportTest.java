package com.apigw.platform.apis.importer;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Map;

import org.hamcrest.Matchers;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.fasterxml.jackson.databind.ObjectMapper;

/** CP-API-06: Swagger 2.0, OpenAPI 3 and Postman v2.1 all become operations with documentation. */
class ImportTest extends IntegrationTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    private String body(String content) throws Exception {
        return JSON.writeValueAsString(Map.of("fileName", "spec", "content", content));
    }

    @Test
    void openApi3YamlImportsParametersBodyAndResponsesPerStatusCode() throws Exception {
        String yaml = """
                openapi: 3.0.3
                info: { title: Payments API, version: "2.1" }
                servers: [ { url: "https://core.example.in/payments" } ]
                paths:
                  /v1/payments/imps/{txnId}:
                    get:
                      tags: [Payments]
                      summary: Get IMPS transfer status
                      parameters:
                        - { name: txnId, in: path, required: true, schema: { type: string } }
                        - { name: X-Request-Id, in: header, required: true, schema: { type: string, format: uuid } }
                        - { name: verbose, in: query, schema: { type: boolean }, example: true }
                      responses:
                        "200":
                          description: Transfer found
                          headers:
                            X-RateLimit-Remaining: { schema: { type: integer }, example: 287 }
                          content:
                            application/json:
                              schema: { $ref: "#/components/schemas/Transfer" }
                        "404": { description: Unknown transfer }
                        default: { description: Unexpected error }
                  /v1/payments/imps:
                    post:
                      summary: Initiate IMPS transfer
                      requestBody:
                        content:
                          application/json:
                            schema:
                              type: object
                              required: [amount]
                              properties:
                                amount: { type: string, example: "250.00" }
                                payee:
                                  type: object
                                  properties:
                                    ifsc: { type: string, example: HDFC0000123 }
                      responses:
                        "201": { description: Created }
                components:
                  schemas:
                    Transfer:
                      type: object
                      required: [txnId, status]
                      properties:
                        txnId: { type: string, example: IMPS123 }
                        status: { type: string, enum: [ACCEPTED, PENDING] }
                """;
        mvc.perform(post("/api/admin/apis/import").with(admin()).contentType(MediaType.APPLICATION_JSON).content(body(yaml)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.format").value("OPENAPI"))
                .andExpect(jsonPath("$.title").value("Payments API"))
                .andExpect(jsonPath("$.suggestedBackendBaseUrl").value("https://core.example.in/payments"))
                .andExpect(jsonPath("$.operations.length()").value(2))
                .andExpect(jsonPath("$.operations[0].name").value("Get IMPS transfer status"))
                .andExpect(jsonPath("$.operations[0].category").value("Payments"))
                .andExpect(jsonPath("$.operations[0].proxyPath").value("/v1/payments/imps/{txnId}"))
                .andExpect(jsonPath("$.operations[0].documentation.requestHeaders[0].name").value("X-Request-Id"))
                .andExpect(jsonPath("$.operations[0].documentation.requestHeaders[0].type").value("string(uuid)"))
                .andExpect(jsonPath("$.operations[0].documentation.queryParameters[0].example").value("true"))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].statusCode").value(200))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyFields[0].name").value("txnId"))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyFields[0].required").value(true))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyExample")
                        .value(Matchers.containsString("\"status\" : \"ACCEPTED\"")))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyExample")
                        .value(Matchers.not(Matchers.containsString("\r"))))
                .andExpect(jsonPath("$.operations[0].documentation.responses[1].statusCode").value(404))
                .andExpect(jsonPath("$.operations[0].documentation.responseHeaders[0].name").value("X-RateLimit-Remaining"))
                .andExpect(jsonPath("$.operations[1].documentation.requestBodyFields[*].name",
                        Matchers.contains("amount", "payee", "payee.ifsc")))
                .andExpect(jsonPath("$.operations[1].documentation.requestBodyExample")
                        .value(Matchers.containsString("\"ifsc\" : \"HDFC0000123\"")))
                .andExpect(jsonPath("$.warnings[*]", Matchers.hasItem(Matchers.containsString("'default'"))));
    }

    @Test
    void swagger2JsonIsConverted() throws Exception {
        String swagger = """
                {"swagger":"2.0","info":{"title":"Legacy","version":"1"},"host":"legacy.example.in","basePath":"/api",
                 "paths":{"/balance":{"get":{"summary":"Balance","produces":["application/json"],
                   "parameters":[{"name":"account","in":"query","required":true,"type":"string"}],
                   "responses":{"200":{"description":"OK","schema":{"type":"object","properties":{"balance":{"type":"number"}}}}}}}}}
                """;
        mvc.perform(post("/api/admin/apis/import").with(admin()).contentType(MediaType.APPLICATION_JSON).content(body(swagger)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.format").value("OPENAPI"))
                .andExpect(jsonPath("$.operations[0].httpMethod").value("GET"))
                .andExpect(jsonPath("$.operations[0].proxyPath").value("/balance"))
                .andExpect(jsonPath("$.operations[0].documentation.queryParameters[0].required").value(true))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyFields[0].type").value("number"));
    }

    @Test
    void postmanCollectionImportsFoldersHeadersBodyAndSavedResponses() throws Exception {
        String collection = """
                {"info":{"_postman_id":"x1","name":"Partner APIs","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
                 "variable":[{"key":"baseUrl","value":"https://core.example.in"}],
                 "item":[{"name":"Accounts","item":[
                   {"name":"Get statement",
                    "request":{"method":"GET",
                      "header":[{"key":"X-Request-Id","value":"abc","description":"Correlation id"},{"key":"X-Off","value":"1","disabled":true}],
                      "url":{"raw":"{{baseUrl}}/v1/accounts/:accountId/statement?from=2026-08-01",
                             "path":["v1","accounts",":accountId","statement"],
                             "query":[{"key":"from","value":"2026-08-01"}]}},
                    "response":[
                      {"name":"OK","code":200,"header":[{"key":"X-RateLimit-Remaining","value":"119"}],
                       "body":"{\\"count\\":42,\\"account\\":{\\"masked\\":\\"5010••4412\\"}}"},
                      {"name":"Not linked","code":404,"body":"{\\"code\\":\\"ACCOUNT_NOT_FOUND\\"}"}]},
                   {"name":"Create note","request":{"method":"POST","url":"{{baseUrl}}/v1/notes",
                    "body":{"mode":"raw","raw":"{\\"text\\":\\"hello\\",\\"pinned\\":true}"}}}
                 ]}]}
                """;
        mvc.perform(post("/api/admin/apis/import").with(admin()).contentType(MediaType.APPLICATION_JSON).content(body(collection)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.format").value("POSTMAN"))
                .andExpect(jsonPath("$.title").value("Partner APIs"))
                .andExpect(jsonPath("$.suggestedBackendBaseUrl").value("https://core.example.in"))
                .andExpect(jsonPath("$.operations.length()").value(2))
                .andExpect(jsonPath("$.operations[0].category").value("Accounts"))
                .andExpect(jsonPath("$.operations[0].proxyPath").value("/v1/accounts/{accountId}/statement"))
                .andExpect(jsonPath("$.operations[0].documentation.requestHeaders.length()").value(1))
                .andExpect(jsonPath("$.operations[0].documentation.queryParameters[0].name").value("from"))
                .andExpect(jsonPath("$.operations[0].documentation.responses[*].statusCode", Matchers.contains(200, 404)))
                .andExpect(jsonPath("$.operations[0].documentation.responses[0].bodyFields[*].name",
                        Matchers.contains("count", "account", "account.masked")))
                .andExpect(jsonPath("$.operations[0].documentation.responseHeaders[0].name").value("X-RateLimit-Remaining"))
                .andExpect(jsonPath("$.operations[1].httpMethod").value("POST"))
                .andExpect(jsonPath("$.operations[1].proxyPath").value("/v1/notes"))
                .andExpect(jsonPath("$.operations[1].documentation.requestBodyFields[1].type").value("boolean"));
    }

    @Test
    void unreadableFilesAreRejectedClearly() throws Exception {
        mvc.perform(post("/api/admin/apis/import").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content(body("this is not a specification")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(Matchers.oneOf("UNREADABLE_SPECIFICATION", "NO_OPERATIONS")));
        mvc.perform(post("/api/admin/apis/import").with(editor()).contentType(MediaType.APPLICATION_JSON)
                        .content(body("openapi: 3.0.0")))
                .andExpect(status().isForbidden());
    }
}
