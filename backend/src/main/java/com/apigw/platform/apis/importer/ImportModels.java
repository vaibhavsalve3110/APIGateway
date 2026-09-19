package com.apigw.platform.apis.importer;

import java.util.List;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import com.apigw.platform.apis.docs.ApiDocumentation;

/** Request and result shapes for documentation import (BRD CP-API-06). */
public final class ImportModels {

    private ImportModels() {
    }

    /** The file's text; the Management Portal reads the uploaded file in the browser and sends its contents. */
    public record ImportRequest(@Size(max = 255) String fileName, @NotBlank @Size(max = 5_000_000) String content) {
    }

    /** One operation found in the file, ready to pre-fill the Add API editor. */
    public record ImportedOperation(String name, String category, String httpMethod, String proxyPath,
                                    String description, ApiDocumentation documentation) {
    }

    /**
     * @param format                  OPENAPI or POSTMAN
     * @param suggestedBackendBaseUrl the server / base URL declared in the file, if any
     */
    public record ImportResult(String format, String title, String suggestedBackendBaseUrl,
                               List<ImportedOperation> operations, List<String> warnings) {
    }
}
