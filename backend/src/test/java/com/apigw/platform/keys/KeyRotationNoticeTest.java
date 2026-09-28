package com.apigw.platform.keys;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

import com.apigw.platform.notifications.Mailer;
import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/**
 * Rotating a key is never silent: the Partner Admins get the key, every user of that organisation is told it
 * changed, and the APIM Admin team is told which partner did it. Only Partner Admins may rotate.
 */
class KeyRotationNoticeTest extends IntegrationTest {

    @MockitoSpyBean
    private Mailer mailer;

    private String addUser(String partnerId, String name, String email, String role) throws Exception {
        return JsonPath.read(mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"%s\",\"email\":\"%s\",\"role\":\"%s\"}".formatted(name, email, role)))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString(), "$.id");
    }

    @Test
    void onlyAPartnerAdminMayGenerateAKey() throws Exception {
        String partner = createPartner("Rotation Fintech");
        String partnerId = JsonPath.read(partner, "$.id");
        String code = JsonPath.read(partner, "$.code");
        addUser(partnerId, "Dev Person", "dev@rotation.in", "PARTNER_DEVELOPER");
        addUser(partnerId, "Admin Person", "admin@rotation.in", "PARTNER_ADMIN");

        // A developer is refused, and told who can do it.
        mvc.perform(post("/api/partner/keys/{env}", "SANDBOX").with(partnerUserNamed(code, "dev@rotation.in")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("NOT_PARTNER_ADMIN"));

        // The portal is told which role the user has, so it can hide the button rather than fail the click.
        mvc.perform(get("/api/partner/me").with(partnerUserNamed(code, "dev@rotation.in")))
                .andExpect(jsonPath("$.role").value("PARTNER_DEVELOPER"))
                .andExpect(jsonPath("$.canGenerateKeys").value(false));
        mvc.perform(get("/api/partner/me").with(partnerUserNamed(code, "admin@rotation.in")))
                .andExpect(jsonPath("$.role").value("PARTNER_ADMIN"))
                .andExpect(jsonPath("$.canGenerateKeys").value(true));

        mvc.perform(post("/api/partner/keys/{env}", "SANDBOX").with(partnerUserNamed(code, "admin@rotation.in")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.plaintext").value(org.hamcrest.Matchers.startsWith("agw_sbx_")));
    }

    @Test
    void everyoneWhoShouldKnowIsToldWhoeverRotatedTheKey() throws Exception {
        String partner = createPartner("Notice Fintech");
        String partnerId = JsonPath.read(partner, "$.id");
        addUser(partnerId, "Partner Admin", "owner@notice.in", "PARTNER_ADMIN");
        addUser(partnerId, "Partner Dev", "builder@notice.in", "PARTNER_DEVELOPER");

        // An APIM Admin rotates on the partner's behalf.
        mvc.perform(post("/api/admin/partners/{id}/keys/{env}", partnerId, "SANDBOX").with(admin()))
                .andExpect(status().isCreated());

        ArgumentCaptor<List<String>> recipients = ArgumentCaptor.captor();
        ArgumentCaptor<String> subjects = ArgumentCaptor.captor();
        ArgumentCaptor<String> bodies = ArgumentCaptor.captor();
        verify(mailer, atLeastOnce()).send(recipients.capture(), subjects.capture(), bodies.capture());

        List<String> allSubjects = subjects.getAllValues();
        List<List<String>> allRecipients = recipients.getAllValues();

        // The key goes to the Partner Admin only.
        int keyMail = allSubjects.indexOf(allSubjects.stream()
                .filter(s -> s.startsWith("Your new sandbox security key")).findFirst().orElseThrow());
        assertThat(allRecipients.get(keyMail)).containsExactly("owner@notice.in");
        assertThat(bodies.getAllValues().get(keyMail)).contains("agw_sbx_", "Client ID");

        // Everyone in the organisation is told it changed, and what to do if it was not them.
        int notice = allSubjects.indexOf(allSubjects.stream()
                .filter(s -> s.startsWith("Security key changed")).findFirst().orElseThrow());
        assertThat(allRecipients.get(notice)).containsExactlyInAnyOrder("owner@notice.in", "builder@notice.in");
        assertThat(bodies.getAllValues().get(notice))
                .contains("contact the APIM Admin team immediately")
                .doesNotContain("agw_sbx_");   // the key itself is not in the broadcast

        // The APIM Admin team hears about it too.
        assertThat(allSubjects).anyMatch(s -> s.startsWith("Key rotation: Notice Fintech"));
    }

    @Test
    void aPartnerRotatingTheirOwnKeyTriggersTheSameNotices() throws Exception {
        String partner = createPartner("Self Rotate Fintech");
        String partnerId = JsonPath.read(partner, "$.id");
        String code = JsonPath.read(partner, "$.code");
        addUser(partnerId, "Self Admin", "self@rotate.in", "PARTNER_ADMIN");

        mvc.perform(post("/api/partner/keys/{env}", "SANDBOX").with(partnerUserNamed(code, "self@rotate.in")))
                .andExpect(status().isCreated());

        ArgumentCaptor<String> bodies = ArgumentCaptor.captor();
        verify(mailer, atLeastOnce()).send(anyList(), anyString(), bodies.capture());
        assertThat(bodies.getAllValues())
                .anyMatch(b -> b.contains("by self@rotate.in in the Developer Portal"));
    }
}
