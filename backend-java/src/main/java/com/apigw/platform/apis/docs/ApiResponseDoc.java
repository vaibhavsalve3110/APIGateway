package com.apigw.platform.apis.docs;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/** The documented response for one HTTP status code. */
public record ApiResponseDoc(
        @NotNull @Min(100) @Max(599) Integer statusCode,
        @Size(max = 500) String description,
        @Size(max = 50_000) String bodyExample,
        @Valid @Size(max = 200) List<ApiField> bodyFields) {

    public ApiResponseDoc {
        bodyFields = bodyFields == null ? List.of() : List.copyOf(bodyFields);
    }
}
