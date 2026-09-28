package com.apigw.platform.partnerusers;

import java.time.Instant;
import java.util.UUID;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import com.apigw.platform.partners.RecordStatus;

/** Request and response shapes for partner user accounts (CP-PTN-04). */
public final class PartnerUserDtos {

    private PartnerUserDtos() {
    }

    public record CreateRequest(
            @NotBlank @Size(max = 160) String fullName,
            @NotBlank @Email @Size(max = 200) String email,
            @NotNull PartnerUserRole role) {
    }

    /** The email is the portal sign-in and can be corrected; it stays unique across all organizations. */
    public record UpdateRequest(
            @NotBlank @Size(max = 160) String fullName,
            @NotBlank @Email @Size(max = 200) String email,
            @NotNull PartnerUserRole role) {
    }

    public record AccessRequest(@NotNull RecordStatus status) {
    }

    /** A login; the organization holds the credentials, so nothing secret appears here. */
    public record PartnerUserView(UUID id, UUID partnerId, String partnerCode, String partnerName,
                                  String fullName, String email, PartnerUserRole role, RecordStatus status,
                                  String createdBy, Instant createdAt, Instant updatedAt) {

        static PartnerUserView of(PartnerUser u, String partnerCode, String partnerName) {
            return new PartnerUserView(u.getId(), u.getPartnerId(), partnerCode, partnerName,
                    u.getFullName(), u.getEmail(), u.getRole(), u.getStatus(),
                    u.getCreatedBy(), u.getCreatedAt(), u.getUpdatedAt());
        }
    }
}
