package com.apigw.platform.keys;

import java.time.Duration;
import java.util.List;

import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import com.apigw.platform.auth.PlatformRole;
import com.apigw.platform.auth.PlatformUser;
import com.apigw.platform.auth.PlatformUserRepository;
import com.apigw.platform.config.ApigwProperties;
import com.apigw.platform.notifications.Mailer;
import com.apigw.platform.partners.RecordStatus;
import com.apigw.platform.partnerusers.PartnerUser;
import com.apigw.platform.partnerusers.PartnerUserRepository;
import com.apigw.platform.partnerusers.PartnerUserRole;

/**
 * Who hears about a key rotation (BRD CP-SEC-04/05, and the operator's rule that a key change must never be
 * silent):
 *
 * <ul>
 *   <li>the organization's <b>Partner Admins</b> get the new key, since they are the ones who install it;</li>
 *   <li><b>every user</b> of that organization, admins included, is told the key changed and what to do if it
 *       was not them;</li>
 *   <li>the <b>APIM Admin team</b> is told which partner rotated, so an unexpected rotation is noticed by
 *       someone other than the partner.</li>
 * </ul>
 *
 * <p>The same notices go out whether the partner rotated their own key or an APIM Admin did it for them;
 * only the wording says who.
 *
 * <p>Runs after the transaction commits, so nobody is told about a rotation that was rolled back.
 */
@Component
class KeyNotificationListener {

    private final PartnerUserRepository partnerUsers;
    private final PlatformUserRepository platformUsers;
    private final Mailer mailer;
    private final ApigwProperties props;

    KeyNotificationListener(PartnerUserRepository partnerUsers, PlatformUserRepository platformUsers, Mailer mailer,
                            ApigwProperties props) {
        this.partnerUsers = partnerUsers;
        this.platformUsers = platformUsers;
        this.mailer = mailer;
        this.props = props;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    void onKeyGenerated(KeyGeneratedEvent event) {
        List<PartnerUser> active = partnerUsers.findByPartnerIdOrderByFullNameAsc(event.partnerId()).stream()
                .filter(u -> u.getStatus() == RecordStatus.ACTIVE)
                .toList();
        List<String> admins = active.stream()
                .filter(u -> u.getRole() == PartnerUserRole.PARTNER_ADMIN)
                .map(PartnerUser::getEmail)
                .toList();
        List<String> everyone = active.stream().map(PartnerUser::getEmail).toList();
        String who = event.byPartner()
                ? "by " + event.actorUsername() + " in the Developer Portal"
                : "by the APIM Admin team (" + event.actorUsername() + ")";
        String environment = event.environment().name().toLowerCase(java.util.Locale.ROOT);

        if (!admins.isEmpty() && props.keys().emailKeyToAdmin()) {
            mailer.send(admins, "Your new " + environment + " security key — " + event.partnerName(),
                    keyEmail(event, who, environment));
        }
        if (!everyone.isEmpty()) {
            mailer.send(everyone, "Security key changed for " + event.partnerName(),
                    changeNotice(event, who, environment));
        }
        List<String> apimAdmins = platformUsers.findAllByOrderByFullNameAsc().stream()
                .filter(u -> u.getStatus() == RecordStatus.ACTIVE && u.getRole() == PlatformRole.ADMIN)
                .map(PlatformUser::getEmail)
                .toList();
        if (!apimAdmins.isEmpty()) {
            mailer.send(apimAdmins,
                    "Key rotation: " + event.partnerName() + " (" + event.partnerCode() + ") — " + environment,
                    adminAlert(event, who, environment));
        }
    }

    private String keyEmail(KeyGeneratedEvent event, String who, String environment) {
        return """
                A new %s security key has been generated for %s (%s) %s.

                Client ID : %s
                New key   : %s

                Install it now. %s

                This key is shown in this message and in the portal at the moment it was created, and nowhere
                else — the platform keeps only a one-way hash of it and cannot tell you the value again.

                If you did not expect this change, contact the APIM Admin team immediately.
                """.formatted(environment, event.partnerName(), event.partnerCode(), who,
                event.clientId(), event.plaintext(), overlapSentence(event));
    }

    private String changeNotice(KeyGeneratedEvent event, String who, String environment) {
        return """
                The %s security key for %s (%s) was changed %s.

                %s

                You are receiving this because you have a Developer Portal account with %s. The key itself is
                sent only to your Partner Admins; ask them for it if you need it.

                If this change was not made by your organisation, contact the APIM Admin team immediately —
                someone may have access to your portal account.
                """.formatted(environment, event.partnerName(), event.partnerCode(), who,
                overlapSentence(event), event.partnerName());
    }

    private String adminAlert(KeyGeneratedEvent event, String who, String environment) {
        return """
                %s (%s) now has a new %s security key, generated %s.

                Client ID    : %s
                Key          : %s
                Previous key : %s

                Every active user of that organisation has been told. If this rotation was not expected,
                check the audit log and contact the partner.
                """.formatted(event.partnerName(), event.partnerCode(), environment, who, event.clientId(),
                event.maskedKey(),
                event.previousExpiresAt() == null ? "none — this is their first key for this environment"
                        : "stops working at " + event.previousExpiresAt());
    }

    /** Spells out the overlap, because "the old key still works for a while" is the part people get wrong. */
    private String overlapSentence(KeyGeneratedEvent event) {
        if (event.previousExpiresAt() == null) {
            return "There was no previous key for this environment, so nothing stops working.";
        }
        Duration overlap = props.keys().overlapWindow();
        return "The previous key keeps working for " + overlap.toMinutes() + " more minutes, until "
                + event.previousExpiresAt() + ", and then stops.";
    }
}
