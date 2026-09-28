package com.apigw.platform.demo;

import java.util.List;

import com.apigw.platform.apis.docs.ApiDocumentation;
import com.apigw.platform.apis.docs.ApiField;
import com.apigw.platform.apis.docs.ApiResponseDoc;

/** Documentation for the demo APIs, matching the WireMock stubs in infra/mocks. */
final class DemoDocumentation {

    private DemoDocumentation() {
    }

    private static final List<ApiField> STANDARD_HEADERS = List.of(
            new ApiField("X-Security-Key", "string", true, "agw_sbx_…", "Your Sandbox or Production security key."),
            new ApiField("X-Request-Id", "string(uuid)", false, "8f14e45f-ceea-4b71-a9d2-0d3c9d1f2e4a",
                    "Idempotency / correlation id you generate per call. Replays within 24 hours return the original response."));

    private static final List<ApiField> STANDARD_RESPONSE_HEADERS = List.of(
            new ApiField("X-RateLimit-Limit", "integer", true, "300", "Calls allowed per window for your Client ID."),
            new ApiField("X-RateLimit-Remaining", "integer", true, "287", "Calls left in the current window."),
            new ApiField("X-Correlation-Id", "string", true, "b3d1c0a2-77ef-4a11-9c02", "Quote this in support queries."));

    private static final ApiResponseDoc UNAUTHORISED = new ApiResponseDoc(401, "Security key missing, invalid or expired",
            "{\n  \"message\": \"Missing API key found in request\"\n}", List.of(new ApiField("message", "string", true, null, "Gateway error text.")));
    private static final ApiResponseDoc RATE_LIMITED = new ApiResponseDoc(429, "Rate limit for your Client ID exceeded — honour Retry-After",
            "{\n  \"error_msg\": \"Requests are too frequent, please try again later.\"\n}", List.of());

    static ApiDocumentation forPath(String path) {
        return switch (path) {
            case "/v1/payments/imps" -> imps();
            case "/v1/payments/neft" -> neft();
            case "/v1/accounts/balance" -> balance();
            case "/v1/accounts/statement" -> statement();
            case "/v1/reference/ifsc" -> ifsc();
            default -> mandate();
        };
    }

    private static ApiDocumentation imps() {
        String request = """
                {
                  "beneficiaryIfsc": "HDFC0000123",
                  "beneficiaryAccount": "501000000004412",
                  "beneficiaryName": "Rohan Sharma",
                  "amount": "25000.00",
                  "remarks": "Settlement 14 Sep"
                }""";
        return new ApiDocumentation("MANUAL", List.of(), STANDARD_HEADERS,
                List.of(
                        new ApiField("beneficiaryIfsc", "string", true, "HDFC0000123", "Beneficiary branch IFSC (11 characters)."),
                        new ApiField("beneficiaryAccount", "string", true, "501000000004412", "Beneficiary account, registered under your account."),
                        new ApiField("beneficiaryName", "string", true, "Rohan Sharma", "Name as registered with the bank."),
                        new ApiField("amount", "string(decimal)", true, "25000.00", "INR amount; ceiling ₹5,00,000 per transfer."),
                        new ApiField("remarks", "string", false, "Settlement 14 Sep", "Narration shown on the beneficiary statement (max 40).")),
                request, STANDARD_RESPONSE_HEADERS,
                List.of(
                        new ApiResponseDoc(200, "Transfer accepted by the switch", """
                                {
                                  "txnId": "IMPS26091412345",
                                  "status": "ACCEPTED",
                                  "rrn": "627312445901",
                                  "initiatedAt": "2026-09-14T14:22:07+05:30",
                                  "environment": "SANDBOX"
                                }""", List.of(
                                new ApiField("txnId", "string", true, "IMPS26091412345", "Gateway transaction reference."),
                                new ApiField("status", "string", true, "ACCEPTED", "ACCEPTED, PENDING or REJECTED."),
                                new ApiField("rrn", "string", false, "627312445901", "NPCI retrieval reference number."),
                                new ApiField("initiatedAt", "string(date-time)", true, "2026-09-14T14:22:07+05:30", null))),
                        new ApiResponseDoc(400, "Validation failed — a field is missing or the amount is above the ceiling", """
                                {
                                  "code": "VALIDATION_FAILED",
                                  "detail": "amount must not exceed 500000.00",
                                  "fields": { "amount": "must not exceed 500000.00" }
                                }""", List.of(
                                new ApiField("code", "string", true, "VALIDATION_FAILED", null),
                                new ApiField("fields", "object", false, null, "Field name → problem."))),
                        UNAUTHORISED,
                        new ApiResponseDoc(409, "Duplicate X-Request-Id with a different payload", """
                                {
                                  "code": "DUPLICATE_REQUEST",
                                  "detail": "X-Request-Id was already used with a different body"
                                }""", List.of()),
                        RATE_LIMITED));
    }

    private static ApiDocumentation neft() {
        String request = """
                {
                  "beneficiaryIfsc": "ICIC0000456",
                  "beneficiaryAccount": "501000000004438",
                  "beneficiaryName": "Meera Iyer",
                  "amount": "112500.00"
                }""";
        return new ApiDocumentation("MANUAL", List.of(), STANDARD_HEADERS,
                List.of(
                        new ApiField("beneficiaryIfsc", "string", true, "ICIC0000456", null),
                        new ApiField("beneficiaryAccount", "string", true, "501000000004438", null),
                        new ApiField("beneficiaryName", "string", true, "Meera Iyer", null),
                        new ApiField("amount", "string(decimal)", true, "112500.00", "INR amount.")),
                request, STANDARD_RESPONSE_HEADERS,
                List.of(
                        new ApiResponseDoc(200, "Accepted into the next NEFT batch", """
                                {
                                  "txnId": "NEFT26091498210",
                                  "status": "PENDING",
                                  "environment": "SANDBOX"
                                }""", List.of(
                                new ApiField("txnId", "string", true, "NEFT26091498210", null),
                                new ApiField("status", "string", true, "PENDING", "PENDING until the batch settles."))),
                        UNAUTHORISED, RATE_LIMITED));
    }

    private static ApiDocumentation balance() {
        return new ApiDocumentation("MANUAL",
                List.of(new ApiField("accountNumber", "string", true, "501000000004412", "Account linked to your partner account.")),
                STANDARD_HEADERS, List.of(), null, STANDARD_RESPONSE_HEADERS,
                List.of(
                        new ApiResponseDoc(200, "Current balance", """
                                {
                                  "accountNumber": "5010••••••4412",
                                  "currency": "INR",
                                  "balance": "184320.55",
                                  "availableBalance": "184320.55",
                                  "asOf": "2026-09-14T14:22:09+05:30",
                                  "environment": "SANDBOX"
                                }""", List.of(
                                new ApiField("accountNumber", "string", true, "5010••••••4412", "Always masked."),
                                new ApiField("balance", "string(decimal)", true, "184320.55", "Ledger balance."),
                                new ApiField("availableBalance", "string(decimal)", true, "184320.55", "Balance available to spend."),
                                new ApiField("asOf", "string(date-time)", true, null, null))),
                        new ApiResponseDoc(404, "Account not linked to your partner account", """
                                {
                                  "code": "ACCOUNT_NOT_FOUND",
                                  "detail": "No linked account 501000000009999"
                                }""", List.of()),
                        UNAUTHORISED, RATE_LIMITED));
    }

    private static ApiDocumentation statement() {
        return new ApiDocumentation("MANUAL",
                List.of(
                        new ApiField("accountNumber", "string", true, "501000000004412", null),
                        new ApiField("from", "string(date)", true, "2026-08-15", "Start date, at most 90 days before 'to'."),
                        new ApiField("to", "string(date)", true, "2026-09-14", "End date (inclusive).")),
                STANDARD_HEADERS, List.of(), null, STANDARD_RESPONSE_HEADERS,
                List.of(
                        new ApiResponseDoc(200, "Statement summary and download link", """
                                {
                                  "accountNumber": "5010••••••4412",
                                  "transactionCount": 42,
                                  "downloadUrl": "https://sandbox-api.apigw.localhost/dl/st_9f2c",
                                  "expiresIn": 900,
                                  "environment": "SANDBOX"
                                }""", List.of(
                                new ApiField("transactionCount", "integer", true, "42", null),
                                new ApiField("downloadUrl", "string(uri)", true, null, "Signed link, valid for expiresIn seconds."))),
                        UNAUTHORISED, RATE_LIMITED));
    }

    private static ApiDocumentation ifsc() {
        return new ApiDocumentation("MANUAL",
                List.of(new ApiField("code", "string", true, "HDFC0000123", "The 11-character IFSC to look up.")),
                List.of(new ApiField("X-Security-Key", "string", true, "agw_sbx_…", "Your key; the Guest key also works for this API.")),
                List.of(), null, STANDARD_RESPONSE_HEADERS,
                List.of(
                        new ApiResponseDoc(200, "Branch details", """
                                {
                                  "ifsc": "HDFC0000123",
                                  "bank": "Example Bank",
                                  "branch": "Fort, Mumbai",
                                  "environment": "SANDBOX"
                                }""", List.of(
                                new ApiField("ifsc", "string", true, "HDFC0000123", null),
                                new ApiField("bank", "string", true, "Example Bank", null),
                                new ApiField("branch", "string", true, "Fort, Mumbai", null))),
                        new ApiResponseDoc(400, "The code query parameter is missing or malformed", """
                                {
                                  "code": "MISSING_PARAMETER",
                                  "detail": "Query parameter 'code' is required"
                                }""", List.of()),
                        UNAUTHORISED));
    }

    private static ApiDocumentation mandate() {
        return new ApiDocumentation("MANUAL", List.of(), STANDARD_HEADERS, List.of(), null, STANDARD_RESPONSE_HEADERS,
                List.of(new ApiResponseDoc(200, "Mandate registered", """
                        {
                          "mandateId": "MND2609141234",
                          "status": "REGISTERED"
                        }""", List.of()), UNAUTHORISED));
    }
}
