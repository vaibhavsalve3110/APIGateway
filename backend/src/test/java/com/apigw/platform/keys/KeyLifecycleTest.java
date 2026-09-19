package com.apigw.platform.keys;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/** BRD v1.3 key rules: shown once, stored hashed, 20-minute overlap, Admin revoke within the window. */
class KeyLifecycleTest extends IntegrationTest {

    @Autowired
    SecurityKeyRepository keys;

    @Autowired
    SecurityKeyService keyService;

    @Test
    void keyIsShownOnceAndOnlyItsHashIsStored() throws Exception {
        String partner = createPartner("Hash Check Fintech");
        String code = JsonPath.read(partner, "$.code");
        String clientId = JsonPath.read(partner, "$.clientIdSandbox");

        String generated = mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(code)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.clientId").value(clientId))
                .andReturn().getResponse().getContentAsString();
        String plaintext = JsonPath.read(generated, "$.plaintext");
        UUID keyId = UUID.fromString(JsonPath.read(generated, "$.key.id"));

        assertThat(plaintext).startsWith("agw_sbx_").hasSizeGreaterThanOrEqualTo(8 + 43);
        SecurityKey stored = keys.findById(keyId).orElseThrow();
        assertThat(stored.getKeyHash()).isEqualTo(KeyMaterial.sha256Hex(plaintext));
        assertThat(stored.getMaskedKey()).startsWith("agw_sbx_").endsWith(plaintext.substring(plaintext.length() - 4))
                .doesNotContain(plaintext.substring(8, 20));
        // The gateway receives the hash, never the key.
        assertThat(gateway.calls).contains("putCredential:SANDBOX:" + clientId + ":" + keyId + ":" + stored.getKeyHash());
        assertThat(String.join("\n", gateway.calls)).doesNotContain(plaintext);

        // Listing the keys afterwards never returns the key again.
        String listed = mvc.perform(get("/api/partner/keys").with(partnerUser(code)))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(listed).doesNotContain(plaintext).contains(stored.getMaskedKey());
    }

    @Test
    void newKeyStartsA20MinuteOverlapThenThePreviousKeyExpires() throws Exception {
        String partner = createPartner("Overlap Window Payments");
        String code = JsonPath.read(partner, "$.code");
        String clientId = JsonPath.read(partner, "$.clientIdSandbox");

        UUID first = generate(code);
        Instant secondAt = clock.instant();
        String second = mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(code)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.previousKeyExpiresAt").value(secondAt.plus(Duration.ofMinutes(20)).toString()))
                .andReturn().getResponse().getContentAsString();
        UUID secondId = UUID.fromString(JsonPath.read(second, "$.key.id"));

        SecurityKey previous = keys.findById(first).orElseThrow();
        assertThat(previous.getStatus()).isEqualTo(KeyStatus.EXPIRING);
        assertThat(previous.getExpiresAt()).isEqualTo(secondAt.plus(Duration.ofMinutes(20)));
        assertThat(keys.findById(secondId).orElseThrow().getStatus()).isEqualTo(KeyStatus.ACTIVE);

        // No third key while the window is open (keeps the two-key maximum).
        mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(code)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ROTATION_WINDOW_OPEN"));

        // Still inside the window: nothing expires.
        clock.advance(Duration.ofMinutes(19));
        keyService.expireDueKeys();
        assertThat(keys.findById(first).orElseThrow().getStatus()).isEqualTo(KeyStatus.EXPIRING);

        // Window over: the previous key expires and is removed from the gateway.
        clock.advance(Duration.ofMinutes(1));
        keyService.expireDueKeys();
        assertThat(keys.findById(first).orElseThrow().getStatus()).isEqualTo(KeyStatus.EXPIRED);
        assertThat(gateway.calls).contains("deleteCredential:SANDBOX:" + clientId + ":" + first);
        assertThat(keys.findById(secondId).orElseThrow().getStatus()).isEqualTo(KeyStatus.ACTIVE);

        // A new rotation may now start.
        generate(code);
    }

    @Test
    void adminCanRevokeTheNewKeyOnlyInsideTheWindow() throws Exception {
        String partner = createPartner("Revoke Window Securities");
        String code = JsonPath.read(partner, "$.code");

        UUID first = generate(code);
        UUID second = generate(code);

        mvc.perform(post("/api/admin/keys/{id}/revoke", second).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REVOKED"));
        SecurityKey reinstated = keys.findById(first).orElseThrow();
        assertThat(reinstated.getStatus()).isEqualTo(KeyStatus.ACTIVE);
        assertThat(reinstated.getExpiresAt()).isNull();

        // Rotate again, let the window close, and revoking is refused.
        UUID third = generate(code);
        clock.advance(Duration.ofMinutes(21));
        keyService.expireDueKeys();
        mvc.perform(post("/api/admin/keys/{id}/revoke", third).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("REVOKE_WINDOW_CLOSED"));
    }

    @Test
    void productionKeysNeedTheProductionTierAndDieWhenItIsWithdrawn() throws Exception {
        String partner = createPartner("Tier Rules Capital");
        String code = JsonPath.read(partner, "$.code");
        String partnerId = JsonPath.read(partner, "$.id");

        mvc.perform(post("/api/partner/keys/PRODUCTION").with(partnerUser(code)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("PRODUCTION_NOT_PROVISIONED"));

        String upgraded = mvc.perform(put("/api/admin/partners/{id}/access-tier", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"accessTier\":\"PRODUCTION\"}"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        String prodClientId = JsonPath.read(upgraded, "$.clientIdProduction");
        assertThat(prodClientId).endsWith("-prd");

        String generated = mvc.perform(post("/api/partner/keys/PRODUCTION").with(partnerUser(code)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.plaintext").value(org.hamcrest.Matchers.startsWith("agw_prd_")))
                .andReturn().getResponse().getContentAsString();
        UUID prodKey = UUID.fromString(JsonPath.read(generated, "$.key.id"));

        mvc.perform(put("/api/admin/partners/{id}/access-tier", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"accessTier\":\"UAT_ONLY\"}"))
                .andExpect(status().isOk());
        assertThat(keys.findById(prodKey).orElseThrow().getStatus()).isEqualTo(KeyStatus.REVOKED);
        assertThat(gateway.calls).contains("deleteCredential:PRODUCTION:" + prodClientId + ":" + prodKey);
    }

    @Test
    void partnerUsersOnlySeeTheirOwnAccount() throws Exception {
        String a = createPartner("Scope Alpha");
        String b = createPartner("Scope Beta");
        generate(JsonPath.read(a, "$.code"));

        mvc.perform(get("/api/partner/keys").with(partnerUser(JsonPath.read(b, "$.code"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
        mvc.perform(get("/api/partner/me").with(partnerUser(JsonPath.read(b, "$.code"))))
                .andExpect(jsonPath("$.name").value("Scope Beta"));
    }

    private UUID generate(String partnerCode) throws Exception {
        String body = mvc.perform(post("/api/partner/keys/SANDBOX").with(partnerUser(partnerCode)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return UUID.fromString(JsonPath.read(body, "$.key.id"));
    }
}
