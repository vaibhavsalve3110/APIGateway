package com.apigw.platform.products;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OrderColumn;
import jakarta.persistence.Table;

import com.apigw.platform.common.ApiException;

/**
 * A Product is a journey: the ordered set of APIs a partner calls to complete one business outcome, such as
 * onboarding a customer or making a payment (BRD CP-API-09). Later steps typically depend on earlier ones,
 * and {@link #getJourneyMarkdown()} is where that flow is explained to the partner.
 *
 * <p>A Product is packaging, not permission. Assigning it to an organization decides who can see it in the
 * Developer Portal; what a partner may actually call is enforced at the gateway by their security key.
 */
@Entity
@Table(name = "product")
public class Product {

    @Id
    private UUID id;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private String slug;

    private String summary;

    @Column(length = 4000)
    private String description;

    /** The flow and dependency document partners read on the product page. */
    @Column(name = "journey_markdown", length = 100_000)
    private String journeyMarkdown;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ProductStatus status;

    /** Ordered: step 1, step 2, ... as the journey is actually performed. */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "product_step", joinColumns = @JoinColumn(name = "product_id"))
    @OrderColumn(name = "position")
    private List<ProductStep> steps = new ArrayList<>();

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "published_at")
    private Instant publishedAt;

    protected Product() {
    }

    public Product(UUID id, String name, String slug, String summary, String description, String journeyMarkdown,
                   List<ProductStep> steps, String createdBy, Instant now) {
        this.id = id;
        this.name = name;
        this.slug = slug;
        this.summary = summary;
        this.description = description;
        this.journeyMarkdown = journeyMarkdown;
        this.steps = new ArrayList<>(steps);
        this.status = ProductStatus.DRAFT;
        this.createdBy = createdBy;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void update(String name, String slug, String summary, String description, String journeyMarkdown,
                       List<ProductStep> steps, Instant now) {
        this.name = name;
        this.slug = slug;
        this.summary = summary;
        this.description = description;
        this.journeyMarkdown = journeyMarkdown;
        this.steps = new ArrayList<>(steps);
        this.updatedAt = now;
    }

    /** A journey with no steps is nothing to publish. */
    public void publish(Instant now) {
        if (steps.isEmpty()) {
            throw ApiException.conflict("PRODUCT_EMPTY", "Add at least one API before publishing " + name);
        }
        this.status = ProductStatus.PUBLISHED;
        this.publishedAt = now;
        this.updatedAt = now;
    }

    public void unpublish(Instant now) {
        this.status = ProductStatus.DRAFT;
        this.updatedAt = now;
    }

    public UUID getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public String getSlug() {
        return slug;
    }

    public String getSummary() {
        return summary;
    }

    public String getDescription() {
        return description;
    }

    public String getJourneyMarkdown() {
        return journeyMarkdown;
    }

    public ProductStatus getStatus() {
        return status;
    }

    public List<ProductStep> getSteps() {
        return List.copyOf(steps);
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
}
