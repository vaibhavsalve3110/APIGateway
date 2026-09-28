package com.apigw.platform.portal;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import com.apigw.platform.common.Env;
import com.apigw.platform.support.IntegrationTest;
import com.apigw.platform.usage.UsageEvent;
import com.apigw.platform.usage.UsageRepository;
import com.jayway.jsonpath.JsonPath;

/** A partner's own dashboard: their traffic only, and zeroes rather than blanks when there is none. */
class PartnerDashboardTest extends IntegrationTest {

    @Autowired
    private UsageRepository usage;

    @Test
    void aQuietAccountShowsZeroesEverywhereRatherThanFailing() throws Exception {
        String code = JsonPath.read(createPartner("Quiet Fintech"), "$.code");

        mvc.perform(get("/api/partner/dashboard").with(partnerUser(code)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.partnerCode").value(code))
                .andExpect(jsonPath("$.window.success").value(0))
                .andExpect(jsonPath("$.window.failed").value(0))
                .andExpect(jsonPath("$.window.successRate").value(0))
                .andExpect(jsonPath("$.window.avgLatencyMs").doesNotExist())
                .andExpect(jsonPath("$.counts.activeKeys").value(0))
                .andExpect(jsonPath("$.counts.products").value(0))
                .andExpect(jsonPath("$.apis.length()").value(0))
                .andExpect(jsonPath("$.recentCalls.length()").value(0));
    }

    @Test
    void aPartnerSeesOnlyTheirOwnCalls() throws Exception {
        String mine = createPartner("Busy Fintech");
        String myCode = JsonPath.read(mine, "$.code");
        String myClientId = JsonPath.read(mine, "$.clientIdSandbox");
        String theirClientId = JsonPath.read(createPartner("Someone Else Fintech"), "$.clientIdSandbox");

        Instant now = clock.instant();
        usage.save(new UsageEvent(now.minusSeconds(60), UUID.randomUUID(), Env.SANDBOX, myClientId, 200, 120));
        usage.save(new UsageEvent(now.minusSeconds(30), UUID.randomUUID(), Env.SANDBOX, myClientId, 500, 900));
        usage.save(new UsageEvent(now.minusSeconds(10), UUID.randomUUID(), Env.SANDBOX, theirClientId, 200, 100));

        mvc.perform(get("/api/partner/dashboard").with(partnerUser(myCode)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.window.success").value(1))
                .andExpect(jsonPath("$.window.failed").value(1))
                .andExpect(jsonPath("$.window.successRate").value(50.0))
                .andExpect(jsonPath("$.recentCalls.length()").value(2))
                .andExpect(jsonPath("$.recentCalls[*].clientId").value(org.hamcrest.Matchers.everyItem(
                        org.hamcrest.Matchers.is(myClientId))));

        // The history endpoint is scoped the same way, and filters like the Management Portal's.
        mvc.perform(get("/api/partner/usage/logs").param("status", "SERVER_ERROR").with(partnerUser(myCode)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].statusCode").value(500))
                .andExpect(jsonPath("$[0].clientId").value(myClientId));
    }
}
