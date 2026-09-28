package com.apigw.platform.products;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import com.apigw.platform.apis.ApiStatus;

/** Request and response shapes for Products (CP-API-09). */
public final class ProductDtos {

    private ProductDtos() {
    }

    /** One step of the journey as the portal sends it. */
    public record StepRequest(@NotNull UUID apiId, @Size(max = 500) String note, UUID dependsOnApiId) {
    }

    public record ProductRequest(
            @NotBlank @Size(max = 120) String name,
            @Size(max = 300) String summary,
            @Size(max = 4000) String description,
            @Size(max = 100_000) String journeyMarkdown,
            List<StepRequest> steps) {

        public ProductRequest {
            steps = steps == null ? List.of() : List.copyOf(steps);
        }
    }

    /** An API inside a journey, with its place in the flow. */
    public record StepView(int step, UUID apiId, String apiName, String category, String httpMethod,
                           String proxyPath, ApiStatus status, String apiDescription, String note,
                           UUID dependsOnApiId, String dependsOnApiName) {
    }

    public record AssignmentView(UUID id, UUID partnerId, String partnerCode, String partnerName,
                                 UUID partnerUserId, String partnerUserEmail, String assignedBy, Instant assignedAt) {
    }

    public record ProductView(UUID id, String name, String slug, String summary, String description,
                              String journeyMarkdown, ProductStatus status, List<StepView> steps,
                              List<AssignmentView> assignments, Instant createdAt, String createdBy,
                              Instant updatedAt, Instant publishedAt) {
    }

    /** Assigning a Product: to a whole organization, or to one user inside it. */
    public record AssignRequest(@NotNull UUID partnerId, UUID partnerUserId) {
    }

    /** What a partner sees: published Products assigned to them, with only the APIs that are live. */
    public record PartnerProductView(UUID id, String name, String slug, String summary, String description,
                                     String journeyMarkdown, List<StepView> steps, boolean assignedToYouDirectly) {
    }
}
