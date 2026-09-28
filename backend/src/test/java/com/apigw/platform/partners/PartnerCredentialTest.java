package com.apigw.platform.partners;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/**
 * Registration is per organization: the signature key pair and IPV salt are issued to the organization,
 * shared by its users, and re-issuable by an Admin.
 */
class PartnerCredentialTest extends IntegrationTest {

    @Autowired
    private PartnerRepository partners;

    @Test
    void registeringAnOrganizationIssuesItsCredentialsOnce() throws Exception {
        String registered = registerPartner("Credential Fintech");

        String privateKey = JsonPath.read(registered, "$.privateKeyPem");
        String salt = JsonPath.read(registered, "$.ipvSalt");
        String partnerId = JsonPath.read(registered, "$.partner.id");
        assertThat(privateKey).startsWith("-----BEGIN PRIVATE KEY-----");
        assertThat(salt).startsWith("ipv_");
        assertThat(JsonPath.<String>read(registered, "$.partner.signatureFingerprint")).startsWith("SHA256:");

        Partner stored = partners.findById(UUID.fromString(partnerId)).orElseThrow();
        assertThat(stored.getSignaturePublicKey()).isEqualTo(JsonPath.<String>read(registered, "$.publicKeyPem"));
        assertThat(stored.getIpvSaltCipher()).startsWith("v1:").doesNotContain(salt);

        // Reading the organization back exposes the public key and a masked salt only.
        mvc.perform(get("/api/admin/partners/{id}", partnerId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.signatureAlgorithm").value("RSA-2048/SHA-256"))
                .andExpect(jsonPath("$.ipvSaltMasked").value(org.hamcrest.Matchers.containsString("••••")))
                .andExpect(jsonPath("$.privateKeyPem").doesNotExist())
                .andExpect(jsonPath("$.ipvSalt").doesNotExist());
    }

    @Test
    void anAdminCanRecreateTheKeyPairAndRotateOrRevealTheSalt() throws Exception {
        String registered = registerPartner("Rotate Organization");
        String partnerId = JsonPath.read(registered, "$.partner.id");
        String firstFingerprint = JsonPath.read(registered, "$.partner.signatureFingerprint");
        String firstSalt = JsonPath.read(registered, "$.ipvSalt");

        String recreated = mvc.perform(post("/api/admin/partners/{id}/signature", partnerId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ipvSalt").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        assertThat(JsonPath.<String>read(recreated, "$.privateKeyPem")).isNotEqualTo(JsonPath.read(registered, "$.privateKeyPem"));
        mvc.perform(get("/api/admin/partners/{id}", partnerId).with(admin()))
                .andExpect(jsonPath("$.signatureFingerprint").value(org.hamcrest.Matchers.not(firstFingerprint)));

        mvc.perform(post("/api/admin/partners/{id}/ipv-salt/reveal", partnerId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ipvSalt").value(firstSalt));

        String rotated = mvc.perform(post("/api/admin/partners/{id}/ipv-salt", partnerId).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.privateKeyPem").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        String rotatedSalt = JsonPath.read(rotated, "$.ipvSalt");
        assertThat(rotatedSalt).isNotEqualTo(firstSalt);
        mvc.perform(post("/api/admin/partners/{id}/ipv-salt/reveal", partnerId).with(admin()))
                .andExpect(jsonPath("$.ipvSalt").value(rotatedSalt));
    }

    @Test
    void organizationDetailsCanBeCorrectedAndOnlyAdminsMayDoIt() throws Exception {
        String partnerId = JsonPath.read(createPartner("Typo Fintech"), "$.id");

        mvc.perform(put("/api/admin/partners/{id}", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Typo Fintech Pvt Ltd\",\"contactEmail\":\"ops@typo.in\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Typo Fintech Pvt Ltd"))
                .andExpect(jsonPath("$.contactEmail").value("ops@typo.in"))
                // Correcting details never touches the credentials.
                .andExpect(jsonPath("$.signatureFingerprint").value(org.hamcrest.Matchers.startsWith("SHA256:")));

        mvc.perform(put("/api/admin/partners/{id}", partnerId).with(editor())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Nope\",\"contactEmail\":\"nope@typo.in\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/api/admin/partners/{id}/signature", partnerId).with(editor()))
                .andExpect(status().isForbidden());
    }
}
