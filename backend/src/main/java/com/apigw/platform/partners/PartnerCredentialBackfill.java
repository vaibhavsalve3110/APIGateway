package com.apigw.platform.partners;

import java.util.List;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.security.Actor;

/**
 * Issues a signature key pair and IPV salt to organizations registered before V4 moved the credentials from
 * the portal user to the organization. V4 carries over the material of an organization's first user, so this
 * only covers organizations that never had a user. Idempotent: it does nothing once every row has credentials.
 */
@Component
class PartnerCredentialBackfill implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(PartnerCredentialBackfill.class);
    private static final Actor SYSTEM = new Actor("System", Set.of("ADMIN"), null);

    private final PartnerRepository partners;
    private final PartnerCredentialService credentials;

    PartnerCredentialBackfill(PartnerRepository partners, PartnerCredentialService credentials) {
        this.partners = partners;
        this.credentials = credentials;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        List<Partner> missing = partners.findAll().stream().filter(p -> !p.hasCredentials()).toList();
        if (missing.isEmpty()) {
            return;
        }
        // The private key is discarded here on purpose: an Admin recreates the pair when the partner needs it,
        // which is the only way material ever reaches someone outside the platform.
        missing.forEach(p -> credentials.issueInitial(p, SYSTEM));
        log.info("Issued organization credentials to {} partner(s) that had none; recreate the key pair from the "
                + "portal when handing them to a partner", missing.size());
    }
}
