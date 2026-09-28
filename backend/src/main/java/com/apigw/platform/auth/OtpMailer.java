package com.apigw.platform.auth;

import java.time.Duration;
import java.util.Arrays;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.stereotype.Component;

import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.errors.ErrorLogService;

/**
 * Sends the one-time code by e-mail.
 *
 * <p>When no SMTP host is configured the code is written to the log instead and returned to the portal, so the
 * platform can be demonstrated without a mail server. That fallback refuses to start under the {@code prod}
 * profile — see {@link #OtpMailer}.
 */
@Component
public class OtpMailer {

    private static final Logger log = LoggerFactory.getLogger(OtpMailer.class);

    private final ObjectProvider<JavaMailSender> mailSender;
    private final ApigwProperties props;
    private final ErrorLogService errors;
    private final boolean smtpConfigured;
    private final boolean prod;

    public OtpMailer(ObjectProvider<JavaMailSender> mailSender, ApigwProperties props, ErrorLogService errors,
                     Environment env) {
        this.mailSender = mailSender;
        this.props = props;
        this.errors = errors;
        this.prod = Arrays.asList(env.getActiveProfiles()).contains("prod");
        this.smtpConfigured = env.getProperty("spring.mail.host") != null
                && !env.getProperty("spring.mail.host", "").isBlank();
        if (!smtpConfigured) {
            if (prod) {
                throw new IllegalStateException(
                        "spring.mail.host must be set in production: sign-in codes are sent by e-mail");
            }
            log.warn("No SMTP host configured — sign-in codes will be logged and shown in the portal. "
                    + "Development only; set spring.mail.* before any real deployment.");
        }
    }

    /**
     * Sends the code, and says whether it actually went out.
     *
     * <p>{@code false} means the portal may show the code instead: either no mail server is configured, or
     * one is configured but refused the message. Outside production that keeps a misconfigured relay from
     * locking everyone out; under {@code prod} a failure is rethrown, because showing a sign-in code on
     * screen there would defeat the point of sending it.
     */
    public boolean send(String email, String code, Duration validFor) {
        if (!smtpConfigured) {
            log.warn("DEV sign-in code for {}: {} (valid {} minutes)", email, code, validFor.toMinutes());
            return false;
        }
        try {
            normaliseAppPassword();
            deliver(email, code, validFor);
            return true;
        } catch (org.springframework.mail.MailException e) {
            // Recorded either way: in production the caller sees a failure, and the operator needs the reason.
            errors.record(ErrorLogService.SMTP, "SMTP_REJECTED",
                    "Could not e-mail the sign-in code to " + email + ": " + rootCause(e), e);
            if (prod) {
                throw e;
            }
            log.error("SMTP rejected the sign-in code for {} ({}). Falling back to showing it in the portal — "
                    + "check spring.mail.* in backend/config/application-local.yml", email, rootCause(e));
            log.warn("DEV sign-in code for {}: {} (valid {} minutes)", email, code, validFor.toMinutes());
            return false;
        }
    }

    /** The server's own words ("535-5.7.8 Username and Password not accepted"), not just "Authentication failed". */
    private static String rootCause(Throwable e) {
        Throwable cause = e;
        while (cause.getCause() != null && cause.getCause() != cause) {
            cause = cause.getCause();
        }
        String detail = cause.getMessage();
        return detail == null || detail.isBlank() ? e.getMessage() : detail.strip().replaceAll("\\s+", " ");
    }

    /**
     * Google shows an App Password as four groups of four ("abcd efgh ijkl mnop"), and pasting it that way is
     * the usual reason Gmail answers "Username and Password not accepted" — SMTP sends the spaces literally.
     * Only that exact shape is normalised, so a passphrase that genuinely contains spaces is left alone.
     */
    private void normaliseAppPassword() {
        if (!(mailSender.getIfAvailable() instanceof JavaMailSenderImpl sender)) {
            return;
        }
        String password = sender.getPassword();
        if (password != null && password.matches("(?i)[a-z]{4}( [a-z]{4}){3}")) {
            sender.setPassword(password.replace(" ", ""));
            log.info("Gmail App Password was given with spaces, as Google displays it; using it without them");
        }
    }

    private void deliver(String email, String code, Duration validFor) {
        SimpleMailMessage message = new SimpleMailMessage();
        message.setTo(email);
        message.setFrom(props.auth().mailFrom());
        message.setSubject("Your API Gateway sign-in code");
        message.setText("""
                Your one-time sign-in code is %s.

                It is valid for %d minutes and can be used once. If you did not ask to sign in, ignore this
                message and tell your administrator — someone has your e-mail address.
                """.formatted(code, validFor.toMinutes()));
        mailSender.getObject().send(message);
        log.info("Sign-in code sent to {}", email);
    }
}
