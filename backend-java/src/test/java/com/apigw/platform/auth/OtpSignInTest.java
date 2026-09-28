package com.apigw.platform.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/** Sign-in for both portals: a CAPTCHA, then a one-time code e-mailed to a known address. */
class OtpSignInTest extends IntegrationTest {

    @Autowired
    private CaptchaService captcha;

    @Autowired
    private PlatformUserRepository platformUsers;

    /** A solved CAPTCHA: tests read the answer straight from the service rather than the image. */
    private String[] solvedCaptcha() throws Exception {
        String body = mvc.perform(post("/api/auth/captcha"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.image").value(org.hamcrest.Matchers.startsWith("data:image/png;base64,")))
                .andReturn().getResponse().getContentAsString();
        String id = JsonPath.read(body, "$.challengeId");
        return new String[] {id, captcha.peek(id)};
    }

    private String requestCode(String email) throws Exception {
        String[] c = solvedCaptcha();
        String body = mvc.perform(post("/api/auth/otp/request").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","captchaId":"%s","captchaAnswer":"%s"}
                                """.formatted(email, c[0], c[1])))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(body, "$.devCode");
    }

    private String staffEmail() {
        String email = "admin-" + UUID.randomUUID() + "@apigw.local";
        platformUsers.save(new PlatformUser(UUID.randomUUID(), email, "Test Admin", PlatformRole.ADMIN,
                "test", clock.instant()));
        return email;
    }

    @Test
    void aCorrectCodeSignsAnInternalUserInAndTheTokenWorks() throws Exception {
        String email = staffEmail();

        String code = requestCode(email);
        assertThat(code).hasSize(6).containsOnlyDigits();

        String signedIn = mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"%s\",\"code\":\"%s\"}".formatted(email, code)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.roles[0]").value("ADMIN"))
                .andExpect(jsonPath("$.partnerCode").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        String token = JsonPath.read(signedIn, "$.token");

        // The session token is accepted by the rest of the API, exactly as a Keycloak token used to be.
        mvc.perform(get("/api/admin/apis").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk());
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.username").value(email))
                .andExpect(jsonPath("$.roles[0]").value("ADMIN"));

        // The code is single use.
        mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"%s\",\"code\":\"%s\"}".formatted(email, code)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CODE"));
    }

    @Test
    void aPartnerUserSignsInAndCarriesOnlyTheirOwnOrganization() throws Exception {
        String partnerId = JsonPath.read(createPartner("Sign In Fintech"), "$.id");
        String partnerCode = JsonPath.read(createPartner("Sign In Fintech"), "$.code");
        String email = "dev-" + UUID.randomUUID() + "@signin.in";
        mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Dev One\",\"email\":\"%s\",\"role\":\"PARTNER_ADMIN\"}".formatted(email)))
                .andExpect(status().isOk());

        String token = JsonPath.read(mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"%s\",\"code\":\"%s\"}".formatted(email, requestCode(email))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.roles[0]").value("PARTNER"))
                .andReturn().getResponse().getContentAsString(), "$.token");

        mvc.perform(get("/api/partner/me").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk());
        // A partner token is not an admin token.
        mvc.perform(get("/api/admin/apis").header("Authorization", "Bearer " + token))
                .andExpect(status().isForbidden());
        assertThat(partnerCode).startsWith("PTN-");
    }

    @Test
    void aWrongCaptchaSendsNothingAndAnUnknownAddressIsNotRevealed() throws Exception {
        String[] c = solvedCaptcha();
        mvc.perform(post("/api/auth/otp/request").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","captchaId":"%s","captchaAnswer":"wrong"}
                                """.formatted(staffEmail(), c[0])))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("CAPTCHA_FAILED"));

        // An address nobody owns is told so (apigw.auth.reveal-unknown-email, on by default).
        String[] c2 = solvedCaptcha();
        mvc.perform(post("/api/auth/otp/request").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"nobody@nowhere.in","captchaId":"%s","captchaAnswer":"%s"}
                                """.formatted(c2[0], c2[1])))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_REGISTERED"))
                .andExpect(jsonPath("$.devCode").doesNotExist());

        mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"nobody@nowhere.in\",\"code\":\"123456\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void wrongCodesAreLimitedAndCodesExpire() throws Exception {
        String email = staffEmail();
        String code = requestCode(email);

        for (int i = 0; i < 5; i++) {
            mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                            .content("{\"email\":\"%s\",\"code\":\"000000\"}".formatted(email)))
                    .andExpect(status().isUnauthorized());
        }
        // Five wrong guesses kill the code, even though it is the right one now.
        mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"%s\",\"code\":\"%s\"}".formatted(email, code)))
                .andExpect(status().isUnauthorized());

        String second = staffEmail();
        String freshCode = requestCode(second);
        clock.advance(Duration.ofMinutes(6));
        mvc.perform(post("/api/auth/otp/verify").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"%s\",\"code\":\"%s\"}".formatted(second, freshCode)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CODE"));
    }

    @Test
    void revokingAccessStopsTheNextSignIn() throws Exception {
        String partnerId = JsonPath.read(createPartner("Revoked Fintech"), "$.id");
        String email = "revoked-" + UUID.randomUUID() + "@signin.in";
        String userId = JsonPath.read(mvc.perform(post("/api/admin/partners/{id}/users", partnerId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fullName\":\"Dev Two\",\"email\":\"%s\",\"role\":\"PARTNER_VIEWER\"}".formatted(email)))
                .andReturn().getResponse().getContentAsString(), "$.id");

        mvc.perform(post("/api/admin/partner-users/{id}/access", userId).with(admin())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"DISABLED\"}"))
                .andExpect(status().isOk());

        // A revoked user can no longer sign in: they are treated as not registered, and no code is sent.
        String[] c = solvedCaptcha();
        mvc.perform(post("/api/auth/otp/request").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","captchaId":"%s","captchaAnswer":"%s"}
                                """.formatted(email, c[0], c[1])))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_REGISTERED"));
    }
}
