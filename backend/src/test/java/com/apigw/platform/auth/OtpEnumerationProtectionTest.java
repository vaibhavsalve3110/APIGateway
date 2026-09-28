package com.apigw.platform.auth;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;

import com.apigw.platform.support.IntegrationTest;
import com.jayway.jsonpath.JsonPath;

/**
 * With {@code apigw.auth.reveal-unknown-email=false} an unregistered address is answered exactly like a
 * registered one, so an attacker cannot use the sign-in screen to find out who holds an account.
 */
@SpringBootTest(properties = {"apigw.scheduling.enabled=false", "spring.mail.host=",
        "apigw.auth.reveal-unknown-email=false"})
class OtpEnumerationProtectionTest extends IntegrationTest {

    @Autowired
    private CaptchaService captcha;

    @Test
    void anUnknownAddressIsIndistinguishableFromAKnownOne() throws Exception {
        String body = mvc.perform(post("/api/auth/captcha")).andReturn().getResponse().getContentAsString();
        String id = JsonPath.read(body, "$.challengeId");

        mvc.perform(post("/api/auth/otp/request").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"nobody@nowhere.in","captchaId":"%s","captchaAnswer":"%s"}
                                """.formatted(id, captcha.peek(id))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.expiresInSeconds").value(300))
                .andExpect(jsonPath("$.code").doesNotExist())
                .andExpect(jsonPath("$.devCode").doesNotExist());
    }
}
