package com.apigw.platform.partners;

import java.time.Clock;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.crypto.SecretCipher;
import com.apigw.platform.partners.PartnerDtos.IssuedCredentials;
import com.apigw.platform.partners.PartnerDtos.PartnerView;
import com.apigw.platform.partners.PartnerDtos.RevealedSalt;
import com.apigw.platform.partnerusers.IpvSaltMaterial;
import com.apigw.platform.partnerusers.SignatureKeyMaterial;
import com.apigw.platform.security.Actor;

/**
 * The signature key pair and IPV salt of an organization (partner). Issued once at registration and shared
 * by every user of that organization, alongside its security keys and Client IDs.
 *
 * <p>Only the public half of the pair is stored — the private key is returned to the caller once, as for
 * security keys (CP-SEC-08). The salt is needed by both sides, so it is stored encrypted and can be revealed
 * again by an Admin; every issue, reveal and rotation is audited.
 */
@Service
public class PartnerCredentialService {

    static final String SHOWN_ONCE =
            "The private key is shown once and is not stored. Hand it to the organization securely; "
                    + "if it is lost, recreate the pair.";

    private final PartnerRepository partners;
    private final SecretCipher cipher;
    private final AuditService audit;
    private final Clock clock;

    public PartnerCredentialService(PartnerRepository partners, SecretCipher cipher, AuditService audit, Clock clock) {
        this.partners = partners;
        this.cipher = cipher;
        this.audit = audit;
        this.clock = clock;
    }

    /** Called when an organization is registered, and by the backfill for rows created before V4. */
    @Transactional
    public IssuedCredentials issueInitial(Partner partner, Actor actor) {
        SignatureKeyMaterial signature = SignatureKeyMaterial.generate();
        IpvSaltMaterial salt = IpvSaltMaterial.generate();
        partner.applySignature(signature, clock.instant());
        partner.applyIpvSalt(cipher.encrypt(salt.plaintext()), salt.masked(), clock.instant());
        audit.record(actor, "ISSUE_CREDENTIALS", PartnerService.AUDIT_PARTNER, partner.getId(),
                "Signature key " + signature.fingerprint() + " and IPV salt " + salt.masked()
                        + " issued to " + partner.getName());
        return new IssuedCredentials(null, signature.privateKeyPem(), signature.publicKeyPem(),
                salt.plaintext(), SHOWN_ONCE);
    }

    @Transactional
    public IssuedCredentials regenerateSignature(UUID partnerId, Actor actor) {
        Partner partner = require(partnerId);
        String previous = partner.getSignatureFingerprint();
        SignatureKeyMaterial signature = SignatureKeyMaterial.generate();
        partner.applySignature(signature, clock.instant());
        audit.record(actor, "REGENERATE_SIGNATURE", PartnerService.AUDIT_PARTNER, partnerId,
                "Signature key pair recreated for " + partner.getName() + "; " + previous + " replaced by "
                        + signature.fingerprint());
        return new IssuedCredentials(null, signature.privateKeyPem(), signature.publicKeyPem(), null, SHOWN_ONCE);
    }

    @Transactional
    public IssuedCredentials rotateIpvSalt(UUID partnerId, Actor actor) {
        Partner partner = require(partnerId);
        String previous = partner.getIpvSaltMasked();
        IpvSaltMaterial salt = IpvSaltMaterial.generate();
        partner.applyIpvSalt(cipher.encrypt(salt.plaintext()), salt.masked(), clock.instant());
        audit.record(actor, "ROTATE_IPV_SALT", PartnerService.AUDIT_PARTNER, partnerId,
                "IPV salt rotated for " + partner.getName() + "; " + previous + " replaced by " + salt.masked());
        return new IssuedCredentials(null, null, null, salt.plaintext(),
                "Update the salt in the organization's configuration — the previous salt stops working immediately.");
    }

    @Transactional
    public RevealedSalt revealIpvSalt(UUID partnerId, Actor actor) {
        Partner partner = require(partnerId);
        audit.record(actor, "VIEW_IPV_SALT", PartnerService.AUDIT_PARTNER, partnerId,
                "IPV salt of " + partner.getName() + " revealed");
        return new RevealedSalt(partnerId, cipher.decrypt(partner.getIpvSaltCipher()), partner.getIpvSaltCreatedAt());
    }

    /** The view carries the fingerprint and the masked salt only. */
    IssuedCredentials withView(IssuedCredentials issued, PartnerView view) {
        return new IssuedCredentials(view, issued.privateKeyPem(), issued.publicKeyPem(), issued.ipvSalt(),
                issued.notice());
    }

    private Partner require(UUID id) {
        return partners.findById(id)
                .orElseThrow(() -> com.apigw.platform.common.ApiException.notFound("Partner", id));
    }
}
