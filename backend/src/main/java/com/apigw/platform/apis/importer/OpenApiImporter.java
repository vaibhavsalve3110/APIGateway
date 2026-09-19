package com.apigw.platform.apis.importer;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import org.springframework.http.HttpStatus;

import com.apigw.platform.apis.docs.ApiDocumentation;
import com.apigw.platform.apis.docs.ApiField;
import com.apigw.platform.apis.docs.ApiResponseDoc;
import com.apigw.platform.apis.importer.ImportModels.ImportResult;
import com.apigw.platform.apis.importer.ImportModels.ImportedOperation;
import com.apigw.platform.common.ApiException;

import io.swagger.parser.OpenAPIParser;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.Operation;
import io.swagger.v3.oas.models.PathItem;
import io.swagger.v3.oas.models.examples.Example;
import io.swagger.v3.oas.models.headers.Header;
import io.swagger.v3.oas.models.media.Content;
import io.swagger.v3.oas.models.media.MediaType;
import io.swagger.v3.oas.models.media.Schema;
import io.swagger.v3.oas.models.parameters.Parameter;
import io.swagger.v3.oas.models.responses.ApiResponse;
import io.swagger.v3.parser.core.models.ParseOptions;
import io.swagger.v3.parser.core.models.SwaggerParseResult;

/** Swagger 2.0 and OpenAPI 3.x (JSON or YAML). Swagger 2.0 is converted to OpenAPI 3 by the parser. */
final class OpenApiImporter {

    private static final Set<PathItem.HttpMethod> SUPPORTED = Set.of(PathItem.HttpMethod.GET, PathItem.HttpMethod.POST,
            PathItem.HttpMethod.PUT, PathItem.HttpMethod.PATCH, PathItem.HttpMethod.DELETE);
    private static final int MAX_DEPTH = 5;

    private OpenApiImporter() {
    }

    static ImportResult parse(String content) {
        ParseOptions options = new ParseOptions();
        options.setResolve(true);
        options.setResolveFully(true);
        SwaggerParseResult parsed = new OpenAPIParser().readContents(content, null, options);
        OpenAPI spec = parsed.getOpenAPI();
        List<String> warnings = new ArrayList<>(parsed.getMessages() == null ? List.of() : parsed.getMessages());
        if (spec == null || spec.getPaths() == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "UNREADABLE_SPECIFICATION",
                    "The file could not be read as Swagger / OpenAPI"
                            + (warnings.isEmpty() ? "" : ": " + String.join("; ", warnings.subList(0, Math.min(3, warnings.size())))));
        }

        List<ImportedOperation> operations = new ArrayList<>();
        spec.getPaths().forEach((path, item) -> item.readOperationsMap().forEach((method, op) -> {
            if (!SUPPORTED.contains(method)) {
                warnings.add(method + " " + path + " skipped — only GET, POST, PUT, PATCH and DELETE are supported");
                return;
            }
            operations.add(operation(path, method.name(), item, op, warnings));
        }));

        String server = spec.getServers() == null || spec.getServers().isEmpty() ? null : spec.getServers().get(0).getUrl();
        String title = spec.getInfo() == null ? null : spec.getInfo().getTitle();
        return new ImportResult("OPENAPI", title, server == null || "/".equals(server) ? null : server, operations, warnings);
    }

    private static ImportedOperation operation(String path, String method, PathItem item, Operation op, List<String> warnings) {
        List<Parameter> params = new ArrayList<>();
        if (item.getParameters() != null) {
            params.addAll(item.getParameters());
        }
        if (op.getParameters() != null) {
            params.addAll(op.getParameters());
        }
        List<ApiField> query = new ArrayList<>();
        List<ApiField> headers = new ArrayList<>();
        for (Parameter p : params) {
            ApiField field = new ApiField(p.getName(), typeOf(p.getSchema()), Boolean.TRUE.equals(p.getRequired()),
                    str(p.getExample() != null ? p.getExample() : p.getSchema() == null ? null : p.getSchema().getExample()),
                    p.getDescription());
            if ("query".equals(p.getIn())) {
                query.add(field);
            } else if ("header".equals(p.getIn())) {
                headers.add(field);
            }
        }

        List<ApiField> bodyFields = new ArrayList<>();
        String bodyExample = null;
        if (op.getRequestBody() != null) {
            MediaType media = pickMedia(op.getRequestBody().getContent());
            if (media != null) {
                bodyExample = example(media);
                if (media.getSchema() != null) {
                    flatten(media.getSchema(), "", bodyFields, 0);
                }
            }
        }

        Map<String, ApiField> responseHeaders = new LinkedHashMap<>();
        List<ApiResponseDoc> responses = new ArrayList<>();
        if (op.getResponses() != null) {
            op.getResponses().forEach((code, response) -> {
                Integer status = statusCode(code);
                if (status == null) {
                    warnings.add(method + " " + path + ": response '" + code + "' skipped — only numeric status codes are kept");
                    return;
                }
                responses.add(response(status, response));
                if (status >= 200 && status < 300 && response.getHeaders() != null) {
                    for (Map.Entry<String, Header> h : response.getHeaders().entrySet()) {
                        responseHeaders.putIfAbsent(h.getKey(), new ApiField(h.getKey(), typeOf(h.getValue().getSchema()),
                                Boolean.TRUE.equals(h.getValue().getRequired()), str(h.getValue().getExample()),
                                h.getValue().getDescription()));
                    }
                }
            });
        }

        String name = firstNonBlank(op.getSummary(), op.getOperationId(), method + " " + path);
        String category = op.getTags() == null || op.getTags().isEmpty() ? "Imported" : op.getTags().get(0);
        return new ImportedOperation(truncate(name, 160), truncate(category, 60), method, ImportPaths.sanitize(path),
                truncate(firstNonBlank(op.getDescription(), op.getSummary(), null), 2000),
                new ApiDocumentation("OPENAPI", query, headers, bodyFields, bodyExample,
                        new ArrayList<>(responseHeaders.values()), responses));
    }

    private static ApiResponseDoc response(int status, ApiResponse response) {
        MediaType media = pickMedia(response.getContent());
        List<ApiField> fields = new ArrayList<>();
        String example = null;
        if (media != null) {
            example = example(media);
            if (media.getSchema() != null) {
                flatten(media.getSchema(), "", fields, 0);
            }
        }
        String description = response.getDescription() != null && !response.getDescription().isBlank()
                ? response.getDescription() : HttpStatus.resolve(status) == null ? null : HttpStatus.resolve(status).getReasonPhrase();
        return new ApiResponseDoc(status, truncate(description, 500), example, fields);
    }

    private static MediaType pickMedia(Content content) {
        if (content == null || content.isEmpty()) {
            return null;
        }
        for (Map.Entry<String, MediaType> e : content.entrySet()) {
            if (e.getKey().toLowerCase(Locale.ROOT).contains("json")) {
                return e.getValue();
            }
        }
        return content.values().iterator().next();
    }

    private static String example(MediaType media) {
        if (media.getExample() != null) {
            return JsonExamples.pretty(media.getExample());
        }
        if (media.getExamples() != null && !media.getExamples().isEmpty()) {
            Example first = media.getExamples().values().iterator().next();
            if (first != null && first.getValue() != null) {
                return JsonExamples.pretty(first.getValue());
            }
        }
        return media.getSchema() == null ? null : JsonExamples.pretty(sample(media.getSchema(), 0));
    }

    /** Builds an example value from a schema when the file provides none. */
    private static Object sample(Schema<?> schema, int depth) {
        if (schema == null || depth > MAX_DEPTH) {
            return null;
        }
        if (schema.getExample() != null) {
            return schema.getExample();
        }
        if (schema.getEnum() != null && !schema.getEnum().isEmpty()) {
            return schema.getEnum().get(0);
        }
        String type = rawType(schema);
        if (schema.getProperties() != null && !schema.getProperties().isEmpty()) {
            Map<String, Object> object = new LinkedHashMap<>();
            schema.getProperties().forEach((name, child) -> object.put(name, sample(child, depth + 1)));
            return object;
        }
        if ("array".equals(type)) {
            Object item = sample(schema.getItems(), depth + 1);
            return item == null ? List.of() : List.of(item);
        }
        if ("integer".equals(type)) {
            return 0;
        }
        if ("number".equals(type)) {
            return 0.0;
        }
        if ("boolean".equals(type)) {
            return true;
        }
        if ("object".equals(type)) {
            return Map.of();
        }
        String format = schema.getFormat();
        if ("date-time".equals(format)) {
            return "2026-09-14T08:00:00Z";
        }
        if ("date".equals(format)) {
            return "2026-09-14";
        }
        if ("uuid".equals(format)) {
            return "3fa85f64-5717-4562-b3fc-2c963f66afa6";
        }
        return "string";
    }

    private static void flatten(Schema<?> schema, String prefix, List<ApiField> out, int depth) {
        if (depth > MAX_DEPTH) {
            return;
        }
        Schema<?> target = "array".equals(rawType(schema)) && schema.getItems() != null ? schema.getItems() : schema;
        String base = target == schema ? prefix : (prefix.isEmpty() ? "[]" : prefix + "[]");
        if (target.getProperties() == null) {
            return;
        }
        for (Map.Entry<String, Schema> e : target.getProperties().entrySet()) {
            Schema<?> child = e.getValue();
            String name = base.isEmpty() ? e.getKey() : base + "." + e.getKey();
            boolean required = target.getRequired() != null && target.getRequired().contains(e.getKey());
            Object ex = child.getExample() != null ? child.getExample()
                    : child.getEnum() != null && !child.getEnum().isEmpty() ? child.getEnum().get(0) : null;
            out.add(new ApiField(truncate(name, 120), typeOf(child), required, str(ex), truncate(child.getDescription(), 1000)));
            if (child.getProperties() != null || "array".equals(rawType(child))) {
                flatten(child, name, out, depth + 1);
            }
        }
    }

    private static String rawType(Schema<?> schema) {
        if (schema == null) {
            return null;
        }
        if (schema.getType() != null) {
            return schema.getType();
        }
        if (schema.getTypes() != null && !schema.getTypes().isEmpty()) {       // OpenAPI 3.1
            return schema.getTypes().stream().filter(t -> !"null".equals(t)).findFirst().orElse(null);
        }
        return schema.getProperties() != null ? "object" : null;
    }

    private static String typeOf(Schema<?> schema) {
        String type = rawType(schema);
        if (type == null) {
            return "string";
        }
        return schema.getFormat() == null ? type : type + "(" + schema.getFormat() + ")";
    }

    private static Integer statusCode(String code) {
        try {
            int status = Integer.parseInt(code.trim());
            return status >= 100 && status <= 599 ? status : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String str(Object o) {
        if (o == null) {
            return null;
        }
        String s = o instanceof String text ? text : JsonExamples.pretty(o);
        return JsonExamples.truncate(s);
    }

    private static String firstNonBlank(String... values) {
        for (String v : values) {
            if (v != null && !v.isBlank()) {
                return v.trim();
            }
        }
        return null;
    }

    private static String truncate(String s, int max) {
        return s == null || s.length() <= max ? s : s.substring(0, max - 3) + "...";
    }
}
