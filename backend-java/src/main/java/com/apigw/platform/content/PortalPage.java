package com.apigw.platform.content;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.apigw.platform.common.ApiException;

/**
 * An informational page shown in the Developer Portal — onboarding guides, FAQs, terms of use
 * (BRD CP-API-10).
 *
 * <p>The text is not stored here but in {@link PortalPageVersion}. A page points at the version partners
 * currently see, so editing a published page is safe: the draft accumulates as new versions and nothing
 * changes on the live portal until it is published again.
 */
@Entity
@Table(name = "portal_page")
public class PortalPage {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String slug;

    @Column(nullable = false)
    private String title;

    @Column(nullable = false)
    private String category;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private PageStatus status;

    @Column(nullable = false)
    private int position;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "published_at")
    private Instant publishedAt;

    @Column(name = "published_version")
    private UUID publishedVersion;

    protected PortalPage() {
    }

    public PortalPage(UUID id, String slug, String title, String category, int position, String createdBy,
                      Instant now) {
        this.id = id;
        this.slug = slug;
        this.title = title;
        this.category = category;
        this.position = position;
        this.status = PageStatus.DRAFT;
        this.createdBy = createdBy;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void updateDetails(String slug, String title, String category, int position, Instant now) {
        this.slug = slug;
        this.title = title;
        this.category = category;
        this.position = position;
        this.updatedAt = now;
    }

    /** Points the live portal at a version of this page's own text. */
    public void publish(PortalPageVersion version, Instant now) {
        if (!version.getPageId().equals(id)) {
            throw ApiException.conflict("WRONG_PAGE", "That version belongs to another page");
        }
        this.publishedVersion = version.getId();
        this.status = PageStatus.PUBLISHED;
        this.publishedAt = now;
        this.updatedAt = now;
    }

    /** Takes the page off the portal; the text and its history are kept. */
    public void unpublish(Instant now) {
        this.status = PageStatus.DRAFT;
        this.publishedVersion = null;
        this.updatedAt = now;
    }

    public UUID getId() {
        return id;
    }

    public String getSlug() {
        return slug;
    }

    public String getTitle() {
        return title;
    }

    public String getCategory() {
        return category;
    }

    public PageStatus getStatus() {
        return status;
    }

    public int getPosition() {
        return position;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public String getCreatedBy() {
        return createdBy;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public Instant getPublishedAt() {
        return publishedAt;
    }

    public UUID getPublishedVersion() {
        return publishedVersion;
    }
}
