package com.apigw.platform.auth;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.util.Locale;

/**
 * Creates the first Management Portal account when there is none, so a fresh (or upgraded) database is not
 * locked out: sign-in needs a record to send a code to, and records are created from inside the portal.
 *
 * <p>Set {@code apigw.auth.bootstrap-admin} to the address that should receive it. Does nothing once any
 * internal user exists, so it never resurrects an account that was deliberately removed.
 */
@Component
class PlatformUserBootstrap implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(PlatformUserBootstrap.class);

    private final PlatformUserRepository users;
    private final Clock clock;
    private final String bootstrapAdmin;

    PlatformUserBootstrap(PlatformUserRepository users, Clock clock,
                          @Value("${apigw.auth.bootstrap-admin:admin@apigw.local}") String bootstrapAdmin) {
        this.users = users;
        this.clock = clock;
        this.bootstrapAdmin = bootstrapAdmin;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (users.count() > 0 || bootstrapAdmin == null || bootstrapAdmin.isBlank()) {
            return;
        }
        String email = bootstrapAdmin.trim().toLowerCase(Locale.ROOT);
        users.save(new PlatformUser(UUID.randomUUID(), email, "Platform Administrator", PlatformRole.ADMIN,
                "System", clock.instant()));
        log.info("Created the first Management Portal account for {} — sign in with a one-time code and add "
                + "the rest of your team", email);
    }
}
