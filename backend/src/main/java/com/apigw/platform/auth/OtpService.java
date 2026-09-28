package com.apigw.platform.auth;

import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.keys.KeyMaterial;
import com.apigw.platform.security.Actor;

/**
 * E-mail one-time codes for both portals (sign-in replaces Keycloak passwords).
 *
 * <p>Rules, in one place so they can be audited: a CAPTCHA must be solved before a code is sent; a code is
 * six digits, valid for {@code apigw.auth.otp-ttl}, usable once, and wrong guesses are counted so it cannot be
 * brute-forced; requests per address are capped in a rolling window and a resend must wait out a cooldown.
 *
 * <p>Whether an address exists is never revealed — an unknown address gets the same "code sent" answer, and no
 * mail. Successful and failed sign-ins are written to the audit log.
 */
@Service
public class OtpService {

    private static final Logger log = LoggerFactory.getLogger(OtpService.class);
    static final String AUDIT_TYPE = "SIGN_IN";
    private static final SecureRandom RANDOM = new SecureRandom();

    private final OtpChallengeRepository challenges;
    private final CaptchaService captcha;
    private final LoginIdentityService identities;
    private final OtpMailer mailer;
    private final TokenService tokens;
    private final AuditService audit;
    private final ApigwProperties props;
    private final Clock clock;

    public OtpService(OtpChallengeRepository challenges, CaptchaService captcha, LoginIdentityService identities,
                      OtpMailer mailer, TokenService tokens, AuditService audit, ApigwProperties props, Clock clock) {
        this.challenges = challenges;
        this.captcha = captcha;
        this.identities = identities;
        this.mailer = mailer;
        this.tokens = tokens;
        this.audit = audit;
        this.props = props;
        this.clock = clock;
    }

    /** What the portal shows after asking for a code. {@code devCode} is set only without a mail server. */
    public record CodeRequested(long expiresInSeconds, long resendInSeconds, String devCode) {
    }

    public record SignedIn(String token, Instant expiresAt, String email, String displayName,
                           List<String> roles, String partnerCode) {
    }

    @Transactional
    public CodeRequested requestCode(String rawEmail, String captchaId, String captchaAnswer, String clientIp) {
        if (!captcha.solve(captchaId, captchaAnswer)) {
            throw new ApiException(org.springframework.http.HttpStatus.BAD_REQUEST, "CAPTCHA_FAILED",
                    "That does not match the image. Try the new one.");
        }
        String email = normalise(rawEmail);
        ApigwProperties.Auth auth = props.auth();
        Instant now = clock.instant();

        List<OtpChallenge> recent = challenges.findByEmailAndCreatedAtAfter(email, now.minus(auth.requestWindow()));
        if (recent.size() >= auth.maxRequestsPerWindow()) {
            audit.record(anonymous(email), "SIGN_IN_THROTTLED", AUDIT_TYPE, null,
                    "Too many sign-in codes requested for " + email + " from " + clientIp);
            throw new ApiException(org.springframework.http.HttpStatus.TOO_MANY_REQUESTS, "TOO_MANY_REQUESTS",
                    "Too many codes requested. Wait " + auth.requestWindow().toMinutes() + " minutes and try again.");
        }
        Optional<OtpChallenge> last = recent.stream().max((a, b) -> a.getCreatedAt().compareTo(b.getCreatedAt()));
        if (last.isPresent()) {
            long waited = Duration.between(last.get().getCreatedAt(), now).toSeconds();
            if (waited < auth.resendCooldown().toSeconds()) {
                throw new ApiException(org.springframework.http.HttpStatus.TOO_MANY_REQUESTS, "RESEND_TOO_SOON",
                        "A code was just sent. You can ask for another in "
                                + (auth.resendCooldown().toSeconds() - waited) + " seconds.");
            }
        }

        Optional<LoginIdentity> identity = identities.find(email);
        if (identity.isEmpty()) {
            log.info("Sign-in code requested for unknown address {} from {}", email, clientIp);
            audit.record(anonymous(email), "SIGN_IN_UNKNOWN_EMAIL", AUDIT_TYPE, null,
                    "Sign-in attempted with an address that is not registered: " + email + " from " + clientIp);
            if (auth.revealUnknownEmail()) {
                throw new ApiException(org.springframework.http.HttpStatus.NOT_FOUND, "USER_NOT_REGISTERED",
                        "This e-mail address is not registered. Ask your administrator to create an account for you.");
            }
            // Otherwise: the same answer as for a known address, so nobody can discover who holds an account.
            return new CodeRequested(auth.otpTtl().toSeconds(), auth.resendCooldown().toSeconds(), null);
        }

        String code = randomCode(auth.otpLength());
        challenges.save(new OtpChallenge(UUID.randomUUID(), email, KeyMaterial.sha256Hex(code), now,
                now.plus(auth.otpTtl()), clientIp));
        boolean delivered = mailer.send(email, code, auth.otpTtl());
        audit.record(anonymous(email), "SIGN_IN_CODE_SENT", AUDIT_TYPE, null,
                "One-time code " + (delivered ? "e-mailed to " : "issued for (not e-mailed) ") + email
                        + " from " + clientIp);
        // Shown in the portal only when it could not be e-mailed, and never under prod (OtpMailer rethrows).
        return new CodeRequested(auth.otpTtl().toSeconds(), auth.resendCooldown().toSeconds(),
                delivered ? null : code);
    }

    // A failed attempt must still be counted, so a rejection commits the counter instead of rolling it back.
    @Transactional(noRollbackFor = ApiException.class)
    public SignedIn verify(String rawEmail, String code, String clientIp) {
        String email = normalise(rawEmail);
        ApigwProperties.Auth auth = props.auth();
        Instant now = clock.instant();
        OtpChallenge challenge = challenges.findFirstByEmailOrderByCreatedAtDesc(email)
                .filter(c -> c.isUsable(now, auth.maxAttempts()))
                .orElseThrow(() -> invalidCode(email, clientIp, "no usable code"));

        challenge.countAttempt();
        if (!MessageDigest.isEqual(challenge.getCodeHash().getBytes(java.nio.charset.StandardCharsets.UTF_8),
                KeyMaterial.sha256Hex(code == null ? "" : code.trim()).getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
            throw invalidCode(email, clientIp, "wrong code, attempt " + challenge.getAttempts());
        }

        LoginIdentity identity = identities.find(email)
                .orElseThrow(() -> invalidCode(email, clientIp, "account no longer active"));
        challenge.consume(now);
        identities.recordSignIn(identity);
        TokenService.Session session = tokens.issue(identity);
        audit.record(new Actor(identity.email(), identity.roles(), identity.partnerCode()),
                "SIGN_IN", AUDIT_TYPE, null, "Signed in from " + clientIp);
        return new SignedIn(session.token(), session.expiresAt(), identity.email(), identity.displayName(),
                List.copyOf(identity.roles()), identity.partnerCode());
    }

    private ApiException invalidCode(String email, String clientIp, String reason) {
        audit.record(anonymous(email), "SIGN_IN_FAILED", AUDIT_TYPE, null,
                "Failed sign-in for " + email + " from " + clientIp + " (" + reason + ")");
        return new ApiException(org.springframework.http.HttpStatus.UNAUTHORIZED, "INVALID_CODE",
                "That code is not valid or has expired. Ask for a new one.");
    }

    /** Sign-in attempts are recorded before anyone is authenticated, so the actor is the address given. */
    private static Actor anonymous(String email) {
        return new Actor(email, java.util.Set.of("SYSTEM"), null);
    }

    private static String normalise(String email) {
        return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
    }

    private static String randomCode(int length) {
        StringBuilder code = new StringBuilder(length);
        for (int i = 0; i < length; i++) {
            code.append(RANDOM.nextInt(10));
        }
        return code.toString();
    }
}
