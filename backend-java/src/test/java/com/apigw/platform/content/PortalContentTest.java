package com.apigw.platform.content;

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

/** CP-API-10: pages are written and edited here, and only appear on the Developer Portal once published. */
class PortalContentTest extends IntegrationTest {

    private String createPage(String title, String body) throws Exception {
        return mvc.perform(post("/api/admin/pages").with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"title":"%s","category":"Guides","bodyMarkdown":"%s","position":1}
                                """.formatted(title, body)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
    }

    @Test
    void editingDoesNotChangeWhatPartnersSeeUntilItIsPublished() throws Exception {
        String created = createPage("Onboarding Guide", "# Welcome\\n\\nFirst steps.");
        String id = JsonPath.read(created, "$.id");

        // Draft: not on the portal at all.
        mvc.perform(get("/api/partner/pages").with(partnerUser("PTN-00001")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.slug == 'onboarding-guide')]").isEmpty());
        mvc.perform(get("/api/partner/pages/{slug}", "onboarding-guide").with(partnerUser("PTN-00001")))
                .andExpect(status().isNotFound());

        mvc.perform(post("/api/admin/pages/{id}/publish", id).with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PUBLISHED"))
                .andExpect(jsonPath("$.unpublishedChanges").value(false));

        mvc.perform(get("/api/partner/pages/{slug}", "onboarding-guide").with(partnerUser("PTN-00001")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("Onboarding Guide"))
                .andExpect(jsonPath("$.bodyMarkdown").value(org.hamcrest.Matchers.containsString("First steps.")));

        // Editing a published page saves a new version but leaves the live text alone.
        mvc.perform(put("/api/admin/pages/{id}", id).with(admin()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"title":"Onboarding Guide","category":"Guides","bodyMarkdown":"# Welcome\\n\\nRewritten.","position":1}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.unpublishedChanges").value(true))
                .andExpect(jsonPath("$.versions.length()").value(2));

        mvc.perform(get("/api/partner/pages/{slug}", "onboarding-guide").with(partnerUser("PTN-00001")))
                .andExpect(jsonPath("$.bodyMarkdown").value(org.hamcrest.Matchers.containsString("First steps.")));

        // Publishing again moves partners to the new text.
        mvc.perform(post("/api/admin/pages/{id}/publish", id).with(admin()))
                .andExpect(jsonPath("$.unpublishedChanges").value(false));
        mvc.perform(get("/api/partner/pages/{slug}", "onboarding-guide").with(partnerUser("PTN-00001")))
                .andExpect(jsonPath("$.bodyMarkdown").value(org.hamcrest.Matchers.containsString("Rewritten.")));
    }

    @Test
    void anEmptyPageCannotBePublishedAndWithdrawingHidesIt() throws Exception {
        String id = JsonPath.read(createPage("Empty Page", ""), "$.id");
        mvc.perform(post("/api/admin/pages/{id}/publish", id).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PAGE_EMPTY"));

        String faq = JsonPath.read(createPage("Partner FAQ", "## Questions"), "$.id");
        mvc.perform(post("/api/admin/pages/{id}/publish", faq).with(admin())).andExpect(status().isOk());
        mvc.perform(get("/api/partner/pages/{slug}", "partner-faq").with(partnerUser("PTN-00001")))
                .andExpect(status().isOk());

        mvc.perform(post("/api/admin/pages/{id}/unpublish", faq).with(admin()))
                .andExpect(jsonPath("$.status").value("DRAFT"));
        mvc.perform(get("/api/partner/pages/{slug}", "partner-faq").with(partnerUser("PTN-00001")))
                .andExpect(status().isNotFound());

        // History survives being withdrawn, and the page can then be deleted.
        mvc.perform(get("/api/admin/pages/{id}", faq).with(admin()))
                .andExpect(jsonPath("$.versions.length()").value(1));
        mvc.perform(delete("/api/admin/pages/{id}", faq).with(admin())).andExpect(status().isNoContent());
    }

    @Test
    void aPublishedPageCannotBeDeletedAndOnlyAdminsEdit() throws Exception {
        String id = JsonPath.read(createPage("Terms Of Use", "Terms text"), "$.id");
        mvc.perform(post("/api/admin/pages/{id}/publish", id).with(admin())).andExpect(status().isOk());

        mvc.perform(delete("/api/admin/pages/{id}", id).with(admin()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PAGE_PUBLISHED"));

        mvc.perform(get("/api/admin/pages").with(editor())).andExpect(status().isForbidden());
        mvc.perform(post("/api/admin/pages").with(editor()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"Nope\",\"category\":\"Guides\"}"))
                .andExpect(status().isForbidden());
    }
}
