package com.apigw.platform.errors;

import java.time.Instant;

/** Response shapes for the system error log. */
public final class ErrorDtos {

    private ErrorDtos() {
    }

    public record ErrorView(Long id, Instant occurredAt, String source, String code, String message, String detail,
                            String actor, String request, String clientIp, String reference) {

        static ErrorView of(ErrorEvent e) {
            return new ErrorView(e.getId(), e.getOccurredAt(), e.getSource(), e.getCode(), e.getMessage(),
                    e.getDetail(), e.getActor(), e.getRequest(), e.getClientIp(), e.getReference());
        }
    }
}
