package com.apigw.platform.apis.importer;

import java.net.URI;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.apigw.platform.apis.docs.ApiDocumentation;
import com.apigw.platform.apis.docs.ApiField;
import com.apigw.platform.apis.docs.ApiResponseDoc;
import com.apigw.platform.apis.importer.ImportModels.ImportResult;
import com.apigw.platform.apis.importer.ImportModels.ImportedOperation;
import com.fasterxml.jackson.databind.JsonNode;

/** Postman Collection v2.0 / v2.1. Saved example responses become the per-status-code responses. */
final class PostmanImporter {

    private static final Set<String> SUPPORTED = Set.of("GET", "POST", "PUT", "PATCH", "DELETE");
    /** Leading {{baseUrl}} variable or scheme://host[:port]. */
    private static final Pattern BASE = Pattern.compile("^(\\{\\{[^}]+}}|https?://[^/?#]+)");

    private PostmanImporter() {
    }

    static boolean looksLikePostman(JsonNode root) {
        if (root == null || !root.isObject()) {
            return false;
        }
        JsonNode info = root.path("info");
        return info.has("_postman_id") || info.path("schema").asText("").contains("getpostman.com")
                || (root.has("item") && !root.has("openapi") && !root.has("swagger"));
    }

    static ImportResult parse(JsonNode root) {
        Map<String, String> variables = new LinkedHashMap<>();
        for (JsonNode v : root.path("variable")) {
            variables.put(v.path("key").asText(), v.path("value").asText());
        }
        List<ImportedOperation> operations = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        String[] base = {null};
        walk(root.path("item"), "Imported", operations, warnings, variables, base);
        return new ImportResult("POSTMAN", root.path("info").path("name").asText(null), base[0], operations, warnings);
    }

    private static void walk(JsonNode items, String folder, List<ImportedOperation> out, List<String> warnings,
                             Map<String, String> variables, String[] base) {
        for (JsonNode item : items) {
            if (item.has("item")) {
                walk(item.path("item"), item.path("name").asText(folder), out, warnings, variables, base);
            } else if (item.has("request")) {
                ImportedOperation op = operation(item, folder, warnings, variables, base);
                if (op != null) {
                    out.add(op);
                }
            }
        }
    }

    private static ImportedOperation operation(JsonNode item, String folder, List<String> warnings,
                                               Map<String, String> variables, String[] base) {
        JsonNode request = item.path("request");
        String name = item.path("name").asText("Untitled request");
        String method = (request.isTextual() ? "GET" : request.path("method").asText("GET")).toUpperCase(Locale.ROOT);
        if (!SUPPORTED.contains(method)) {
            warnings.add(name + " skipped — " + method + " is not supported");
            return null;
        }

        JsonNode url = request.isTextual() ? request : request.path("url");
        String raw = url.isTextual() ? url.asText() : url.path("raw").asText("");
        String path;
        if (url.isObject() && url.path("path").isArray() && !url.path("path").isEmpty()) {
            List<String> segments = new ArrayList<>();
            url.path("path").forEach(s -> segments.add(s.isTextual() ? s.asText() : s.path("value").asText()));
            path = "/" + String.join("/", segments);
        } else {
            path = BASE.matcher(raw).replaceFirst("");
        }
        if (base[0] == null) {
            base[0] = baseUrl(raw, variables);
        }

        List<ApiField> query = new ArrayList<>();
        for (JsonNode q : url.path("query")) {
            if (!q.path("disabled").asBoolean(false)) {
                query.add(new ApiField(q.path("key").asText(), "string", false, text(q.path("value")), text(q.path("description"))));
            }
        }
        List<ApiField> headers = headers(request.path("header"));

        String bodyExample = null;
        JsonNode body = request.path("body");
        if ("raw".equals(body.path("mode").asText())) {
            bodyExample = JsonExamples.pretty(body.path("raw").asText(null));
        } else if (body.has("mode") && !body.path("mode").asText().isBlank()) {
            warnings.add(name + ": '" + body.path("mode").asText() + "' body mode is not imported — document it manually");
        }

        List<ApiResponseDoc> responses = new ArrayList<>();
        Map<String, ApiField> responseHeaders = new LinkedHashMap<>();
        for (JsonNode r : item.path("response")) {
            int code = r.path("code").asInt(0);
            if (code < 100 || code > 599 || responses.stream().anyMatch(x -> x.statusCode() == code)) {
                continue;
            }
            String example = JsonExamples.pretty(r.path("body").asText(null));
            responses.add(new ApiResponseDoc(code, firstNonBlank(r.path("name").asText(null), r.path("status").asText(null)),
                    example, JsonExamples.fieldsFrom(example)));
            if (code >= 200 && code < 300) {
                headers(r.path("header")).forEach(h -> responseHeaders.putIfAbsent(h.name(), h));
            }
        }

        String description = request.path("description").isTextual() ? request.path("description").asText()
                : request.path("description").path("content").asText(null);
        return new ImportedOperation(name.length() > 160 ? name.substring(0, 157) + "..." : name,
                folder.length() > 60 ? folder.substring(0, 60) : folder, method, ImportPaths.sanitize(path), description,
                new ApiDocumentation("POSTMAN", query, headers, JsonExamples.fieldsFrom(bodyExample), bodyExample,
                        new ArrayList<>(responseHeaders.values()), responses));
    }

    private static List<ApiField> headers(JsonNode headerArray) {
        List<ApiField> headers = new ArrayList<>();
        for (JsonNode h : headerArray) {
            if (!h.path("disabled").asBoolean(false) && !h.path("key").asText("").isBlank()) {
                headers.add(new ApiField(h.path("key").asText(), "string", false, text(h.path("value")), text(h.path("description"))));
            }
        }
        return headers;
    }

    private static String baseUrl(String raw, Map<String, String> variables) {
        Matcher m = BASE.matcher(raw);
        if (!m.find()) {
            return null;
        }
        String base = m.group(1);
        if (base.startsWith("{{")) {
            base = variables.get(base.substring(2, base.length() - 2).trim());
        }
        if (base == null || base.isBlank()) {
            return null;
        }
        try {
            URI uri = URI.create(base);
            return uri.getScheme() == null ? null : base;
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static String text(JsonNode node) {
        return node == null || node.isMissingNode() || node.isNull() ? null : JsonExamples.truncate(node.asText());
    }

    private static String firstNonBlank(String a, String b) {
        return a != null && !a.isBlank() ? a : b;
    }
}
