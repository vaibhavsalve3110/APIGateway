package com.apigw.platform.errors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import com.apigw.platform.errors.ErrorDtos.ErrorView;
import com.apigw.platform.support.IntegrationTest;

/** Operational failures are stored in error_event and readable by an Admin. */
class ErrorLogTest extends IntegrationTest {

    @Autowired
    private ErrorLogService errors;

    @Autowired
    private ErrorEventRepository repository;

    @Test
    void aFailureIsStoredWithItsStackTraceAndReference() {
        String reference = errors.record(ErrorLogService.SMTP, "SMTP_REJECTED",
                "Could not e-mail the sign-in code to ops@example.in: 535 Username and Password not accepted",
                new IllegalStateException("Authentication failed"));

        assertThat(reference).startsWith("ERR-");
        List<ErrorView> latest = errors.latest(ErrorLogService.SMTP, 10);
        assertThat(latest).isNotEmpty();
        ErrorView stored = latest.getFirst();
        assertThat(stored.code()).isEqualTo("SMTP_REJECTED");
        assertThat(stored.message()).contains("535 Username and Password not accepted");
        assertThat(stored.detail()).contains("IllegalStateException", "Authentication failed");
        assertThat(stored.reference()).isEqualTo(reference);
    }

    @Test
    void recordingSurvivesARolledBackTransactionAndNeverThrows() {
        long before = repository.count();
        // The caller's own transaction failing must not take the record of it away.
        errors.record(ErrorLogService.SCHEDULER, "KEY_EXPIRY_FAILED", "The key expiry sweep failed", null);
        assertThat(repository.count()).isEqualTo(before + 1);

        // A null cause and an over-long message are tolerated rather than throwing inside a failure path.
        String reference = errors.record(ErrorLogService.API, "INTERNAL_ERROR", "x".repeat(5_000), null);
        assertThat(reference).isNotNull();
        assertThat(errors.latest(ErrorLogService.API, 1).getFirst().message()).hasSize(1_000).endsWith("...");
    }

    @Test
    void onlyAdminsCanReadTheLogAndFilteringWorks() throws Exception {
        errors.record(ErrorLogService.GATEWAY, "GATEWAY_UNAVAILABLE", "The sandbox gateway did not answer", null);

        mvc.perform(get("/api/admin/errors").param("source", "GATEWAY").with(admin()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].source").value("GATEWAY"))
                .andExpect(jsonPath("$[0].code").value("GATEWAY_UNAVAILABLE"))
                .andExpect(jsonPath("$[0].reference").value(org.hamcrest.Matchers.startsWith("ERR-")));

        mvc.perform(get("/api/admin/errors").with(editor())).andExpect(status().isForbidden());
        mvc.perform(get("/api/admin/errors")).andExpect(status().isUnauthorized());
    }

    @Test
    void anUnknownEndpointIsA404AndIsNotRecordedAsADefect() throws Exception {
        long before = repository.count();

        mvc.perform(get("/api/admin/no-such-endpoint").with(admin()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ENDPOINT_NOT_FOUND"))
                .andExpect(jsonPath("$.reference").doesNotExist());

        // Same for a verb the endpoint does not offer: a stale portal, not a defect.
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                        .delete("/api/admin/partners").with(admin()))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(jsonPath("$.code").value("METHOD_NOT_ALLOWED"))
                .andExpect(jsonPath("$.reference").doesNotExist());

        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void oldRecordsArePurged() {
        errors.record(ErrorLogService.API, "INTERNAL_ERROR", "old failure", null);
        long before = repository.count();

        clock.advance(Duration.ofDays(31));
        int purged = errors.purgeBefore(clock.instant().minus(Duration.ofDays(30)));

        assertThat(purged).isEqualTo((int) before);
        assertThat(repository.count()).isZero();
    }
}
