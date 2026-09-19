package com.apigw.platform.apis.importer;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.apigw.platform.apis.docs.ApiField;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.util.DefaultIndenter;
import com.fasterxml.jackson.core.util.DefaultPrettyPrinter;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;

/** JSON helpers shared by the importers: pretty-printing examples and deriving field tables from them. */
final class JsonExamples {

    static final ObjectMapper MAPPER = new ObjectMapper();
    /** Always LF line breaks, whatever the host OS, so stored examples look the same everywhere. */
    private static final ObjectWriter PRETTY = MAPPER.writer(
            new DefaultPrettyPrinter().withObjectIndenter(new DefaultIndenter("  ", "\n")));
    private static final int MAX_DEPTH = 5;

    private JsonExamples() {
    }

    static JsonNode parseOrNull(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return MAPPER.readTree(text);
        } catch (JsonProcessingException e) {
            return null;
        }
    }

    /** Pretty JSON if the text is JSON, otherwise the text unchanged. */
    static String pretty(String text) {
        JsonNode node = parseOrNull(text);
        return node == null ? text : pretty(node);
    }

    static String pretty(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return PRETTY.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            return String.valueOf(value);
        }
    }

    /** Field table inferred from an example payload: types come from the values, nothing is marked required. */
    static List<ApiField> fieldsFrom(String exampleJson) {
        JsonNode root = parseOrNull(exampleJson);
        List<ApiField> out = new ArrayList<>();
        if (root != null) {
            collect(root.isArray() && !root.isEmpty() ? root.get(0) : root, "", out, 0);
        }
        return out;
    }

    private static void collect(JsonNode node, String prefix, List<ApiField> out, int depth) {
        if (!node.isObject() || depth > MAX_DEPTH) {
            return;
        }
        for (Map.Entry<String, JsonNode> entry : node.properties()) {
            String name = prefix.isEmpty() ? entry.getKey() : prefix + "." + entry.getKey();
            JsonNode value = entry.getValue();
            out.add(new ApiField(name, typeOf(value), false,
                    value.isValueNode() && !value.isNull() ? truncate(value.asText()) : null, null));
            if (value.isObject()) {
                collect(value, name, out, depth + 1);
            } else if (value.isArray() && !value.isEmpty() && value.get(0).isObject()) {
                collect(value.get(0), name + "[]", out, depth + 1);
            }
        }
    }

    static String typeOf(JsonNode value) {
        if (value.isTextual()) {
            return "string";
        }
        if (value.isIntegralNumber()) {
            return "integer";
        }
        if (value.isNumber()) {
            return "number";
        }
        if (value.isBoolean()) {
            return "boolean";
        }
        if (value.isArray()) {
            return "array";
        }
        if (value.isObject()) {
            return "object";
        }
        return "string";
    }

    static String truncate(String s) {
        return s == null || s.length() <= 500 ? s : s.substring(0, 497) + "...";
    }
}
