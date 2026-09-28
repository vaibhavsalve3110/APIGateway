package com.apigw.platform.products;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/**
 * CP-API-09: a Product is a journey of dependent APIs, assigned to an organization or to named users, and
 * visible in the Developer Portal once published.
 */
class ProductJourneyTest extends IntegrationTest {

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

    private String createProduct(String name, String initiate, String confirm) throws Exception {
        return mvc.perform(post("/api/admin/products").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"%s","summary":"Collect a payment end to end",
                                 "journeyMarkdown":"## Flow\\n1. Initiate\\n2. Confirm with the txnId",
                                 "steps":[
                                   {"apiId":"%s","note":"Start the payment; returns txnId"},
                                   {"apiId":"%s","note":"Confirm using the txnId","dependsOnApiId":"%s"}
                                 ]}
                                """.formatted(name, initiate, confirm, initiate)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
    }

    @Test
    void aProductIsAnOrderedJourneyWithDependenciesAndAFlowDocument() throws Exception {
        String initiate = anApi("Journey Initiate", "/v1/journey/initiate");
        String confirm = anApi("Journey Confirm", "/v1/journey/confirm");

        String created = createProduct("Payment Journey", initiate, confirm);
        String id = JsonPath.read(created, "$.id");

        mvc.perform(get("/api/admin/products/{id}", id).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.slug").value("payment-journey"))
                .andExpect(jsonPath("$.status").value("DRAFT"))
                .andExpect(jsonPath("$.journeyMarkdown").value(org.hamcrest.Matchers.containsString("Confirm with the txnId")))
                .andExpect(jsonPath("$.steps.length()").value(2))
                .andExpect(jsonPath("$.steps[0].step").value(1))
                .andExpect(jsonPath("$.steps[0].apiName").value("Journey Initiate"))
                .andExpect(jsonPath("$.steps[1].step").value(2))
                .andExpect(jsonPath("$.steps[1].dependsOnApiName").value("Journey Initiate"))
                .andExpect(jsonPath("$.steps[1].note").value("Confirm using the txnId"));
    }

    @Test
    void dependenciesMustMakeSense() throws Exception {
        String initiate = anApi("Sense Initiate", "/v1/sense/initiate");
        String other = anApi("Sense Other", "/v1/sense/other");

        // Depending on itself.
        mvc.perform(post("/api/admin/products").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"Self Dependent","steps":[{"apiId":"%s","dependsOnApiId":"%s"}]}
                                """.formatted(initiate, initiate)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SELF_DEPENDENCY"));

        // Depending on an API that is not part of this journey.
        mvc.perform(post("/api/admin/products").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"Outside Dependency","steps":[{"apiId":"%s","dependsOnApiId":"%s"}]}
                                """.formatted(initiate, other)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("DEPENDENCY_NOT_IN_PRODUCT"));

        // A journey with no steps cannot be published.
        String empty = JsonPath.read(mvc.perform(post("/api/admin/products").with(admin())
                                .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"Empty Journey\"}"))
                        .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString(), "$.id");
        mvc.perform(post("/api/admin/products/{id}/publish", empty).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PRODUCT_EMPTY"));
    }

    @Test
    void assignedPartnersSeeAPublishedJourneyAndOthersDoNot() throws Exception {
        String initiate = anApi("Assign Initiate", "/v1/assign/initiate");
        String confirm = anApi("Assign Confirm", "/v1/assign/confirm");
        String productId = JsonPath.read(createProduct("Assigned Journey", initiate, confirm), "$.id");

        String partner = createPartner("Journey Fintech");
        String partnerId = JsonPath.read(partner, "$.id");
        String partnerCode = JsonPath.read(partner, "$.code");

        // Published but not yet assigned: nobody sees it.
        mvc.perform(post("/api/admin/products/{id}/publish", productId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PUBLISHED"));
        mvc.perform(get("/api/partner/products").with(partnerUser(partnerCode)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));

        // Assigned to the organization: every user of it sees the journey, its steps and the flow document.
        mvc.perform(post("/api/admin/products/{id}/assignments", productId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"partnerId\":\"%s\"}".formatted(partnerId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.assignments.length()").value(1))
                .andExpect(jsonPath("$.assignments[0].partnerUserId").doesNotExist());

        mvc.perform(get("/api/partner/products").with(partnerUser(partnerCode)))
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].name").value("Assigned Journey"))
                .andExpect(jsonPath("$[0].steps.length()").value(2))
                .andExpect(jsonPath("$[0].journeyMarkdown").value(org.hamcrest.Matchers.containsString("Flow")));

        mvc.perform(get("/api/partner/products/{slug}", "assigned-journey").with(partnerUser(partnerCode)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.steps[1].dependsOnApiName").value("Assign Initiate"));

        // A different organization sees nothing.
        String otherCode = JsonPath.read(createPartner("Other Fintech"), "$.code");
        mvc.perform(get("/api/partner/products").with(partnerUser(otherCode)))
                .andExpect(jsonPath("$.length()").value(0));
        mvc.perform(get("/api/partner/products/{slug}", "assigned-journey").with(partnerUser(otherCode)))
                .andExpect(status().isNotFound());

        // Withdrawing the assignment hides it again.
        String assignmentId = JsonPath.read(mvc.perform(get("/api/admin/products/{id}", productId).with(admin()))
                .andReturn().getResponse().getContentAsString(), "$.assignments[0].id");
        mvc.perform(delete("/api/admin/products/{id}/assignments/{a}", productId, assignmentId).with(admin()))
                .andExpect(status().isOk());
        mvc.perform(get("/api/partner/products").with(partnerUser(partnerCode)))
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void aJourneyCanBeAssignedToOneUserInsideAnOrganization() throws Exception {
        String initiate = anApi("User Assign Initiate", "/v1/userassign/initiate");
        String confirm = anApi("User Assign Confirm", "/v1/userassign/confirm");
        String productId = JsonPath.read(createProduct("User Journey", initiate, confirm), "$.id");
        mvc.perform(post("/api/admin/products/{id}/publish", productId).with(admin())).andExpect(status().isOk());

        String partner = createPartner("User Scope Fintech");
        String partnerId = JsonPath.read(partner, "$.id");
        String userId = JsonPath.read(mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Journey User\",\"email\":\"journey.user@scope.in\",\"role\":\"PARTNER_ADMIN\"}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString(), "$.id");

        mvc.perform(post("/api/admin/products/{id}/assignments", productId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"partnerId\":\"%s\",\"partnerUserId\":\"%s\"}".formatted(partnerId, userId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.assignments[0].partnerUserEmail").value("journey.user@scope.in"));

        // Assigning the same user twice is refused.
        mvc.perform(post("/api/admin/products/{id}/assignments", productId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"partnerId\":\"%s\",\"partnerUserId\":\"%s\"}".formatted(partnerId, userId)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ALREADY_ASSIGNED"));

        // A user of another organization cannot be assigned this partner's product.
        String otherPartnerId = JsonPath.read(createPartner("Wrong Org Fintech"), "$.id");
        String otherUserId = JsonPath.read(mvc.perform(post("/api/admin/partners/{id}/users", otherPartnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Wrong Org\",\"email\":\"wrong.org@scope.in\",\"role\":\"PARTNER_VIEWER\"}"))
                .andReturn().getResponse().getContentAsString(), "$.id");
        mvc.perform(post("/api/admin/products/{id}/assignments", productId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"partnerId\":\"%s\",\"partnerUserId\":\"%s\"}".formatted(partnerId, otherUserId)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("USER_NOT_IN_ORGANIZATION"));
    }

    @Test
    void publishedProductsCannotBeDeletedAndOnlyAdminsManageThem() throws Exception {
        String api = anApi("Delete Guard", "/v1/delete/guard");
        String id = JsonPath.read(mvc.perform(post("/api/admin/products").with(admin())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"name\":\"Guarded Journey\",\"steps\":[{\"apiId\":\"%s\"}]}".formatted(api)))
                        .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString(), "$.id");

        mvc.perform(post("/api/admin/products/{id}/publish", id).with(admin())).andExpect(status().isOk());
        mvc.perform(delete("/api/admin/products/{id}", id).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PRODUCT_PUBLISHED"));

        mvc.perform(post("/api/admin/products/{id}/unpublish", id).with(admin()))
                .andExpect(jsonPath("$.status").value("DRAFT"));
        mvc.perform(put("/api/admin/products/{id}", id).with(editor()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Nope\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(delete("/api/admin/products/{id}", id).with(admin())).andExpect(status().isNoContent());
        mvc.perform(get("/api/admin/products/{id}", id).with(admin())).andExpect(status().isNotFound());
    }
}
