package com.apigw.platform.partners;

import java.time.Instant;
import java.util.UUID;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/** Request and response shapes for partner groups and partners. */
public final class PartnerDtos {

    private PartnerDtos() {
    }

    public record GroupRequest(@NotBlank @Size(max = 120) String name, @Size(max = 500) String description) {
    }

    public record GroupView(UUID id, String name, String description, RecordStatus status, long partnerCount) {
    }

    public record PartnerRequest(
            @NotBlank @Size(max = 160) String name,
            @NotNull UUID groupId,
            @Email @Size(max = 200) String contactEmail) {
    }

    public record TierRequest(@NotNull AccessTier accessTier) {
    }

    public record StatusRequest(@NotNull RecordStatus status) {
    }

    public record PartnerView(UUID id, String code, String name, UUID groupId, String groupName,
                              AccessTier accessTier, RecordStatus status, String contactEmail,
                              String clientIdSandbox, String clientIdProduction, Instant createdAt) {

        static PartnerView of(Partner p, String groupName) {
            return new PartnerView(p.getId(), p.getCode(), p.getName(), p.getGroupId(), groupName,
                    p.getAccessTier(), p.getStatus(), p.getContactEmail(), p.getClientIdSandbox(),
                    p.getClientIdProduction(), p.getCreatedAt());
        }
    }
}
