package com.apigw.platform.content;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One saved revision of a page's text. Kept for ever: what partners were shown, and when, is the sort of
 * thing a regulator asks about.
 */
@Entity
@Table(name = "portal_page_version")
public class PortalPageVersion {

    @Id
    private UUID id;

    @Column(name = "page_id", nullable = false)
    private UUID pageId;

    @Column(nullable = false)
    private int version;

    @Column(name = "body_markdown", nullable = false, length = 100_000)
    private String bodyMarkdown;

    @Column(name = "edited_by", nullable = false)
    private String editedBy;

    @Column(name = "edited_at", nullable = false)
    private Instant editedAt;

    protected PortalPageVersion() {
    }

    public PortalPageVersion(UUID id, UUID pageId, int version, String bodyMarkdown, String editedBy, Instant now) {
        this.id = id;
        this.pageId = pageId;
        this.version = version;
        this.bodyMarkdown = bodyMarkdown;
        this.editedBy = editedBy;
        this.editedAt = now;
    }

    public UUID getId() {
        return id;
    }

    public UUID getPageId() {
        return pageId;
    }

    public int getVersion() {
        return version;
    }

    public String getBodyMarkdown() {
        return bodyMarkdown;
    }

    public String getEditedBy() {
        return editedBy;
    }

    public Instant getEditedAt() {
        return editedAt;
    }
}
