package com.apigw.platform.common;

import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import com.apigw.platform.errors.ErrorLogService;

/** Every error leaves the API as an RFC 9457 problem document with a {@code code} property. */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    private final ErrorLogService errors;

    public GlobalExceptionHandler(ErrorLogService errors) {
        this.errors = errors;
    }

    @ExceptionHandler(ApiException.class)
    ProblemDetail handle(ApiException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(ex.status(), ex.getMessage());
        problem.setProperty("code", ex.code());
        // A 4xx is the API working as designed (a duplicate name, a revoked key); only a 5xx is our fault.
        if (ex.status().is5xxServerError()) {
            String reference = errors.record(ErrorLogService.API, ex.code(), ex.getMessage(), ex);
            if (reference != null) {
                problem.setProperty("reference", reference);
            }
        }
        return problem;
    }

    /**
     * No handler for that path: a 404, not a defect. Usually a stale portal calling an endpoint this build
     * does not have yet, so the message says as much instead of "something went wrong". Deliberately not
     * recorded — anything scanning for paths would otherwise fill the error log.
     */
    @ExceptionHandler(NoResourceFoundException.class)
    ProblemDetail handle(NoResourceFoundException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND,
                "No endpoint at " + ex.getResourcePath()
                        + ". If the portal was just updated, the backend may still be running an older build.");
        problem.setProperty("code", "ENDPOINT_NOT_FOUND");
        return problem;
    }

    /**
     * The path exists but not for that verb — again a stale portal against an older backend rather than a
     * defect, so it answers 405 and is not recorded.
     */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    ProblemDetail handle(HttpRequestMethodNotSupportedException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.METHOD_NOT_ALLOWED,
                ex.getMethod() + " is not supported here"
                        + (ex.getSupportedHttpMethods() == null || ex.getSupportedHttpMethods().isEmpty()
                        ? "" : " (allowed: " + ex.getSupportedHttpMethods() + ")")
                        + ". If the portal was just updated, the backend may still be running an older build.");
        problem.setProperty("code", "METHOD_NOT_ALLOWED");
        return problem;
    }

    /**
     * Anything not handled above is a defect: record it with its stack trace, and give the caller a reference
     * instead of the exception text, which can leak internals.
     */
    @ExceptionHandler(Exception.class)
    ProblemDetail handleUnexpected(Exception ex) {
        log.error("Unhandled exception", ex);
        String reference = errors.record(ErrorLogService.API, "INTERNAL_ERROR",
                ex.getClass().getSimpleName() + ": " + ex.getMessage(), ex);
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.INTERNAL_SERVER_ERROR,
                reference == null
                        ? "Something went wrong. Please try again, and tell your administrator if it continues."
                        : "Something went wrong. Quote reference " + reference + " to your administrator.");
        problem.setProperty("code", "INTERNAL_ERROR");
        if (reference != null) {
            problem.setProperty("reference", reference);
        }
        return problem;
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail handle(MethodArgumentNotValidException ex) {
        Map<String, String> fields = new LinkedHashMap<>();
        ex.getBindingResult().getFieldErrors()
                .forEach(error -> fields.putIfAbsent(error.getField(), error.getDefaultMessage()));
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, "Some fields are invalid");
        problem.setProperty("code", "VALIDATION_FAILED");
        problem.setProperty("fields", fields);
        return problem;
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    ProblemDetail handle(DataIntegrityViolationException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT,
                "The change conflicts with an existing record (a name, path or Client ID is already in use)");
        problem.setProperty("code", "DUPLICATE");
        return problem;
    }
}
