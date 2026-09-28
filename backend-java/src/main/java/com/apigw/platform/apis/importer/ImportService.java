package com.apigw.platform.apis.importer;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import com.apigw.platform.apis.importer.ImportModels.ImportResult;
import com.apigw.platform.common.ApiException;
import com.fasterxml.jackson.databind.JsonNode;

/** Reads a Swagger / OpenAPI file or a Postman collection into operations the Add API editor can use. */
@Service
public class ImportService {

    public ImportResult read(String content) {
        String text = content == null ? "" : content.strip();
        if (text.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "EMPTY_FILE", "The file is empty");
        }
        JsonNode json = JsonExamples.parseOrNull(text);
        ImportResult result = json != null && PostmanImporter.looksLikePostman(json)
                ? PostmanImporter.parse(json)
                : OpenApiImporter.parse(text);
        if (result.operations().isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "NO_OPERATIONS",
                    "The file was read, but it contains no GET, POST, PUT, PATCH or DELETE operations");
        }
        return result;
    }
}
