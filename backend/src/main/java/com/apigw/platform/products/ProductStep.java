package com.apigw.platform.products;

import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;

/**
 * One step of a Product's journey: an API, why it is called at this point, and which earlier step it needs
 * first — for example "confirm payment" depends on the txnId that "initiate payment" returns.
 */
@Embeddable
public class ProductStep {

    @Column(name = "api_id", nullable = false)
    private UUID apiId;

    @Column(name = "step_note", length = 500)
    private String note;

    @Column(name = "depends_on_api_id")
    private UUID dependsOnApiId;

    protected ProductStep() {
    }

    public ProductStep(UUID apiId, String note, UUID dependsOnApiId) {
        this.apiId = apiId;
        this.note = note == null || note.isBlank() ? null : note.trim();
        this.dependsOnApiId = dependsOnApiId;
    }

    public UUID getApiId() {
        return apiId;
    }

    public String getNote() {
        return note;
    }

    public UUID getDependsOnApiId() {
        return dependsOnApiId;
    }
}
