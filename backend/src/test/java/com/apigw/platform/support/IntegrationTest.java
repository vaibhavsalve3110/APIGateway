package com.apigw.platform.support;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.RequestPostProcessor;

import com.jayway.jsonpath.JsonPath;

/** Full application on H2 with a controllable clock and a recording gateway. */
// spring.mail.host is cleared here on purpose: backend/config/application.yml is read by every run,
// including this one, and a test suite must never reach a real mail server.
@SpringBootTest(properties = {"apigw.scheduling.enabled=false", "spring.mail.host="})
@AutoConfigureMockMvc
@ActiveProfiles("h2")
@Import(TestSupport.class)
public abstract class IntegrationTest {

    @Autowired
    protected MockMvc mvc;

    @Autowired
    protected TestSupport.MutableClock clock;

    @Autowired
    protected TestSupport.RecordingGateway gateway;

    protected static RequestPostProcessor admin() {
        return jwt().jwt(j -> j.claim("preferred_username", "vaibhav.admin"))
                .authorities(new SimpleGrantedAuthority("ROLE_ADMIN"));
    }

    protected static RequestPostProcessor editor() {
        return jwt().jwt(j -> j.claim("preferred_username", "ravi.editor"))
                .authorities(new SimpleGrantedAuthority("ROLE_EDITOR"));
    }

    protected static RequestPostProcessor partnerUser(String partnerCode) {
        return jwt().jwt(j -> j.claim("preferred_username", "dev@" + partnerCode)
                        .claim("groups", List.of("/partners/" + partnerCode)))
                .authorities(new SimpleGrantedAuthority("ROLE_PARTNER"));
    }

    protected String createGroup(String name) throws Exception {
        String body = mvc.perform(post("/api/admin/partner-groups").with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"%s\"}".formatted(name)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(body, "$.id");
    }

    /**
     * Registers a UAT-only organization in a fresh group and returns its PartnerView JSON.
     * Registration itself returns {@code IssuedCredentials}; {@link #registerPartner} exposes that.
     */
    protected String createPartner(String name) throws Exception {
        String id = JsonPath.read(registerPartner(name), "$.partner.id");
        return mvc.perform(get("/api/admin/partners/{id}", id).with(admin()))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
    }

    /** The registration response, including the organization credentials issued once. */
    protected String registerPartner(String name) throws Exception {
        String groupId = createGroup(name + " group " + UUID.randomUUID());
        return mvc.perform(post("/api/admin/partners").with(admin())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"%s\",\"groupId\":\"%s\",\"contactEmail\":\"it@example.in\"}"
                                .formatted(name, groupId)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
    }
}
