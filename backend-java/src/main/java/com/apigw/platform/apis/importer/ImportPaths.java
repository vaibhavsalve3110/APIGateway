package com.apigw.platform.apis.importer;

/** Normalises paths from imported files into the proxy-path form the gateway accepts. */
final class ImportPaths {

    private ImportPaths() {
    }

    /**
     * {@code /v1/payments/:txnId} and {@code /v1/{{version}}/x} become {@code /v1/payments/{txnId}} and
     * {@code /v1/{version}/x}; any character the proxy path does not allow is dropped.
     */
    static String sanitize(String path) {
        if (path == null || path.isBlank()) {
            return "/";
        }
        String p = path.trim();
        int query = p.indexOf('?');
        if (query >= 0) {
            p = p.substring(0, query);
        }
        p = p.replaceAll("\\{\\{\\s*([A-Za-z0-9_\\-.]+)\\s*}}", "{$1}")
                .replaceAll("(^|/):([A-Za-z0-9_]+)", "$1{$2}")
                .replaceAll("[^A-Za-z0-9/_\\-{}.]", "");
        if (!p.startsWith("/")) {
            p = "/" + p;
        }
        return p.replaceAll("/{2,}", "/");
    }
}
