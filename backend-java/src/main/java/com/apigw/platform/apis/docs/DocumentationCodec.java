package com.apigw.platform.apis.docs;

import org.springframework.stereotype.Component;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

/** Converts documentation to and from the JSON stored on {@code api_definition.documentation}. */
@Component
public class DocumentationCodec {

    private final JsonMapper json;

    public DocumentationCodec(JsonMapper json) {
        this.json = json;
    }

    public String write(ApiDocumentation documentation) {
        return documentation == null ? null : json.writeValueAsString(documentation);
    }

    public ApiDocumentation read(String stored) {
        if (stored == null || stored.isBlank()) {
            return ApiDocumentation.empty();
        }
        try {
            return json.readValue(stored, ApiDocumentation.class);
        } catch (JacksonException e) {
            throw new IllegalStateException("Stored API documentation is not valid JSON", e);
        }
    }
}
