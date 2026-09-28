package com.apigw.platform.errors;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import com.apigw.platform.errors.ErrorDtos.ErrorView;
import com.apigw.platform.security.Actor;
import com.apigw.platform.security.CurrentActor;

/**
 * Writes operational failures to {@code error_event} so they can be read from the portal rather than from a
 * log file on the server.
 *
 * <p>Recording runs in its own transaction: the failure it describes has usually just rolled one back, and a
 * row that disappears with it would be worthless. Recording never throws — if the database itself is the
 * problem, the log file is all that is left, and the original error must still reach the caller.
 */
@Service
public class ErrorLogService {

    private static final Logger log = LoggerFactory.getLogger(ErrorLogService.class);
    private static final int MAX_MESSAGE = 1000;
    private static final int MAX_DETAIL = 8000;

    private final ErrorEventRepository events;
    private final Clock clock;

    public ErrorLogService(ErrorEventRepository events, Clock clock) {
        this.events = events;
        this.clock = clock;
    }

    /** Sources are coarse on purpose, so the portal can filter by the part of the system that failed. */
    public static final String SMTP = "SMTP";
    public static final String GATEWAY = "GATEWAY";
    public static final String SCHEDULER = "SCHEDULER";
    public static final String API = "API";

    /**
     * Records a failure and returns the reference shown to the caller, or {@code null} if it could not be
     * stored.
     */
    public String record(String source, String code, String message, Throwable cause) {
        String reference = "ERR-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase(java.util.Locale.ROOT);
        try {
            store(source, code, message, cause, reference);
            return reference;
        } catch (RuntimeException e) {
            // The database is unreachable or the row was rejected: keep the original failure flowing.
            log.error("Could not store {} error {} ({}) — original problem: {}", source, code, e.getMessage(), message);
            return null;
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    void store(String source, String code, String message, Throwable cause, String reference) {
        events.save(new ErrorEvent(clock.instant(), source, code, trim(message, MAX_MESSAGE),
                stackTrace(cause), actorName(), requestLine(), clientIp(), reference));
    }

    @Transactional(readOnly = true)
    public List<ErrorView> latest(String source, int limit) {
        PageRequest page = PageRequest.of(0, Math.min(Math.max(limit, 1), 500));
        List<ErrorEvent> found = source == null || source.isBlank()
                ? events.findAllByOrderByOccurredAtDescIdDesc(page)
                : events.findBySourceOrderByOccurredAtDescIdDesc(source.trim().toUpperCase(java.util.Locale.ROOT), page);
        return found.stream().map(ErrorView::of).toList();
    }

    @Transactional
    public int purgeBefore(Instant before) {
        return events.deleteOlderThan(before);
    }

    private static String stackTrace(Throwable cause) {
        if (cause == null) {
            return null;
        }
        StringWriter out = new StringWriter();
        cause.printStackTrace(new PrintWriter(out));
        return trim(out.toString(), MAX_DETAIL);
    }

    private static String trim(String value, int max) {
        if (value == null) {
            return null;
        }
        return value.length() <= max ? value : value.substring(0, max - 3) + "...";
    }

    /** Best effort: a scheduled job or a startup failure has no signed-in user and no request. */
    private static String actorName() {
        try {
            Actor actor = CurrentActor.get();
            return actor.username();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static HttpServletRequest currentRequest() {
        return RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes
                ? attributes.getRequest() : null;
    }

    private static String requestLine() {
        HttpServletRequest request = currentRequest();
        return request == null ? null : trim(request.getMethod() + " " + request.getRequestURI(), 300);
    }

    private static String clientIp() {
        HttpServletRequest request = currentRequest();
        if (request == null) {
            return null;
        }
        String forwarded = request.getHeader("X-Forwarded-For");
        return forwarded == null || forwarded.isBlank() ? request.getRemoteAddr() : forwarded.split(",")[0].trim();
    }
}
