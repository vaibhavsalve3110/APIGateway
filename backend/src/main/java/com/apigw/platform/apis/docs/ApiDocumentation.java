package com.apigw.platform.apis.docs;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Size;

import com.fasterxml.jackson.annotation.JsonIgnore;

/**
 * Everything a partner needs to call one API (BRD CP-API-06 / CP-API-07, DP-02): parameters, request headers and
 * body, response headers, and one response per HTTP status code.
 *
 * @param source where the documentation came from: MANUAL, OPENAPI or POSTMAN
 */
public record ApiDocumentation(
        @Size(max = 12) String source,
        @Valid @Size(max = 50) List<ApiField> queryParameters,
        @Valid @Size(max = 50) List<ApiField> requestHeaders,
        @Valid @Size(max = 200) List<ApiField> requestBodyFields,
        @Size(max = 50_000) String requestBodyExample,
        @Valid @Size(max = 50) List<ApiField> responseHeaders,
        @Valid @Size(max = 30) List<ApiResponseDoc> responses) {

    public ApiDocumentation {
        queryParameters = queryParameters == null ? List.of() : List.copyOf(queryParameters);
        requestHeaders = requestHeaders == null ? List.of() : List.copyOf(requestHeaders);
        requestBodyFields = requestBodyFields == null ? List.of() : List.copyOf(requestBodyFields);
        responseHeaders = responseHeaders == null ? List.of() : List.copyOf(responseHeaders);
        responses = responses == null ? List.of() : List.copyOf(responses);
        source = source == null || source.isBlank() ? "MANUAL" : source;
    }

    public static ApiDocumentation empty() {
        return new ApiDocumentation("MANUAL", null, null, null, null, null, null);
    }

    /** Each status code may be documented once. */
    @JsonIgnore
    @AssertTrue(message = "each HTTP status code can only be documented once")
    public boolean isStatusCodesUnique() {
        Set<Integer> seen = new HashSet<>();
        return responses.stream().allMatch(r -> seen.add(r.statusCode()));
    }

    /** The example partners see first, and the one the simulated Sandbox returns: the lowest 2xx response. */
    @JsonIgnore
    public ApiResponseDoc primarySuccess() {
        return responses.stream()
                .filter(r -> r.statusCode() >= 200 && r.statusCode() < 300)
                .min((a, b) -> Integer.compare(a.statusCode(), b.statusCode()))
                .orElse(null);
    }
}
