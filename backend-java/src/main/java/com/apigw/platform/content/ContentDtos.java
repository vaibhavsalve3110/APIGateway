package com.apigw.platform.content;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** Request and response shapes for Developer Portal pages (CP-API-10). */
public final class ContentDtos {

    private ContentDtos() {
    }

    public record PageRequest(
            @NotBlank @Size(max = 160) String title,
            @NotBlank @Size(max = 60) String category,
            @Size(max = 100_000) String bodyMarkdown,
            Integer position) {
    }

    public record VersionView(UUID id, int version, String editedBy, Instant editedAt, boolean live) {
    }

    /**
     * A page as the Management Portal sees it: the draft text being edited, plus whether that differs from
     * what partners are currently shown.
     */
    public record PageView(UUID id, String slug, String title, String category, PageStatus status, int position,
                           String bodyMarkdown, boolean unpublishedChanges, Instant createdAt, String createdBy,
                           Instant updatedAt, Instant publishedAt, List<VersionView> versions) {
    }

    /** What a partner sees: the published text only. */
    public record PublishedPageView(String slug, String title, String category, String bodyMarkdown,
                                    Instant publishedAt) {
    }

    /** Menu entry for the Developer Portal. */
    public record PageLink(String slug, String title, String category) {
    }
}
