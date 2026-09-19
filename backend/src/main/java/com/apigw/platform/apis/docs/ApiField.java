package com.apigw.platform.apis.docs;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * One documented parameter, header or body field. {@code name} may use dots for nesting, e.g. {@code payer.ifsc}.
 * {@code required} is a wrapper type because Jackson 3 rejects a missing JSON value for a primitive; it defaults to false.
 */
public record ApiField(
        @NotBlank @Size(max = 120) String name,
        @Size(max = 40) String type,
        Boolean required,
        @Size(max = 500) String example,
        @Size(max = 1000) String description) {

    public ApiField {
        type = type == null || type.isBlank() ? "string" : type;
        required = Boolean.TRUE.equals(required);
    }
}
