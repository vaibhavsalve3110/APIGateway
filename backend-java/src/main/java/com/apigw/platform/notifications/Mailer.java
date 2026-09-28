package com.apigw.platform.notifications;

import java.util.Arrays;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Component;

import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.errors.ErrorLogService;

/**
 * Sends operational notices — key rotations and the like. Sign-in codes have their own sender
 * ({@code OtpMailer}) because they must never be queued, retried or logged like ordinary mail.
 *
 * <p>Without SMTP the message is written to the log instead, so the platform can be demonstrated without a
 * mail server. A failed send is recorded in the error log and swallowed: a notice that cannot be delivered
 * must not undo the key rotation it describes.
 */
@Component
public class Mailer {

    private static final Logger log = LoggerFactory.getLogger(Mailer.class);

    private final ObjectProvider<JavaMailSender> mailSender;
    private final ApigwProperties props;
    private final ErrorLogService errors;
    private final boolean smtpConfigured;

    public Mailer(ObjectProvider<JavaMailSender> mailSender, ApigwProperties props, ErrorLogService errors,
                  Environment env) {
        this.mailSender = mailSender;
        this.props = props;
        this.errors = errors;
        this.smtpConfigured = env.getProperty("spring.mail.host") != null
                && !env.getProperty("spring.mail.host", "").isBlank();
        if (!smtpConfigured && !Arrays.asList(env.getActiveProfiles()).contains("prod")) {
            log.warn("No SMTP host configured — notifications will be logged instead of sent.");
        }
    }

    /** Sends to each address separately, so one bad address cannot stop the rest. */
    public void send(List<String> recipients, String subject, String body) {
        recipients.stream().filter(r -> r != null && !r.isBlank()).distinct().forEach(to -> send(to, subject, body));
    }

    public void send(String to, String subject, String body) {
        if (!smtpConfigured) {
            log.info("NOTICE (no SMTP) to {}: {}\n{}", to, subject, body);
            return;
        }
        try {
            SimpleMailMessage message = new SimpleMailMessage();
            message.setTo(to);
            message.setFrom(props.auth().mailFrom());
            message.setSubject(subject);
            message.setText(body);
            mailSender.getObject().send(message);
            log.info("Notification '{}' sent to {}", subject, to);
        } catch (RuntimeException e) {
            errors.record(ErrorLogService.SMTP, "NOTIFICATION_NOT_SENT",
                    "Could not send '" + subject + "' to " + to + ": " + e.getMessage(), e);
        }
    }
}
