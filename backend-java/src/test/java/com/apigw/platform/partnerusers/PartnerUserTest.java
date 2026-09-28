package com.apigw.platform.partnerusers;

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

/** CP-PTN-04: several portal logins per organization; the credentials belong to the organization. */
class PartnerUserTest extends IntegrationTest {

    private String createUser(String partnerId, String name, String email, String role) throws Exception {
        return mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"fullName":"%s","email":"%s","role":"%s"}
                                """.formatted(name, email, role)))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
    }

    @Test
    void oneOrganizationCanHaveSeveralUsersAndNoneCarryCredentials() throws Exception {
        String partnerId = JsonPath.read(createPartner("Multi User Fintech"), "$.id");

        String first = createUser(partnerId, "Priya Nair", "priya@multiuser.in", "PARTNER_ADMIN");
        createUser(partnerId, "Rahul Shetty", "rahul@multiuser.in", "PARTNER_DEVELOPER");

        // A user is a login only: no key material of its own.
        org.assertj.core.api.Assertions.assertThat(first)
                .doesNotContain("privateKeyPem", "ipvSalt", "signatureFingerprint");

        String partnerCode = JsonPath.read(mvc.perform(get("/api/admin/partners/{id}", partnerId).with(admin()))
                .andReturn().getResponse().getContentAsString(), "$.code");
        mvc.perform(get("/api/admin/partners/{id}/users", partnerId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].partnerCode").value(partnerCode));
    }

    @Test
    void theEmailCanBeCorrectedAndStaysUnique() throws Exception {
        String partnerId = JsonPath.read(createPartner("Email Fintech"), "$.id");
        String userId = JsonPath.read(createUser(partnerId, "Priya Nair", "old@email.in", "PARTNER_ADMIN"), "$.id");
        createUser(partnerId, "Rahul Shetty", "taken@email.in", "PARTNER_DEVELOPER");

        mvc.perform(put("/api/admin/partner-users/{id}", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Priya N\",\"email\":\"NEW@email.in\",\"role\":\"PARTNER_VIEWER\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value("new@email.in"))
                .andExpect(jsonPath("$.fullName").value("Priya N"))
                .andExpect(jsonPath("$.role").value("PARTNER_VIEWER"));

        mvc.perform(put("/api/admin/partner-users/{id}", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Priya N\",\"email\":\"taken@email.in\",\"role\":\"PARTNER_VIEWER\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("EMAIL_IN_USE"));
    }

    @Test
    void accessIsRevokedAndGrantedAgain() throws Exception {
        String partnerId = JsonPath.read(createPartner("Access Fintech"), "$.id");
        String userId = JsonPath.read(createUser(partnerId, "User One", "user@access.in", "PARTNER_ADMIN"), "$.id");

        mvc.perform(post("/api/admin/partner-users/{id}/access", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"DISABLED\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DISABLED"));
        mvc.perform(post("/api/admin/partner-users/{id}/access", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"ACTIVE\"}"))
                .andExpect(jsonPath("$.status").value("ACTIVE"));
    }

    @Test
    void aUserCanOnlyBeDeletedOnceAccessIsRevoked() throws Exception {
        String partnerId = JsonPath.read(createPartner("Delete Fintech"), "$.id");
        String userId = JsonPath.read(createUser(partnerId, "Leaver One", "leaver@delete.in", "PARTNER_DEVELOPER"), "$.id");

        // Still active: deletion is refused, and says what to do first.
        mvc.perform(delete("/api/admin/partner-users/{id}", userId).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ACCESS_NOT_REVOKED"));

        mvc.perform(post("/api/admin/partner-users/{id}/access", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"DISABLED\"}"))
                .andExpect(status().isOk());

        mvc.perform(delete("/api/admin/partner-users/{id}", userId).with(editor()))
                .andExpect(status().isForbidden());
        mvc.perform(delete("/api/admin/partner-users/{id}", userId).with(admin()))
                .andExpect(status().isNoContent());

        mvc.perform(get("/api/admin/partner-users/{id}", userId).with(admin()))
                .andExpect(status().isNotFound());
        // The address is free to use again.
        createUser(partnerId, "Newcomer", "leaver@delete.in", "PARTNER_VIEWER");
    }

    @Test
    void emailsAreUniqueAndOnlyAdminsManageUsers() throws Exception {
        String partnerId = JsonPath.read(createPartner("Unique Fintech"), "$.id");
        createUser(partnerId, "Priya Nair", "same@unique.in", "PARTNER_ADMIN");

        mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Other\",\"email\":\"SAME@unique.in\",\"role\":\"PARTNER_DEVELOPER\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("EMAIL_IN_USE"));

        mvc.perform(get("/api/admin/partner-users").with(editor())).andExpect(status().isForbidden());
        mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(editor())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Nope\",\"email\":\"nope@unique.in\",\"role\":\"PARTNER_VIEWER\"}"))
                .andExpect(status().isForbidden());
    }
}
