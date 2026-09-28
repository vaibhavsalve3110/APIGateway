package com.apigw.platform.auth;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.transaction.annotation.Transactional;

public interface OtpChallengeRepository extends JpaRepository<OtpChallenge, UUID> {

    Optional<OtpChallenge> findFirstByEmailOrderByCreatedAtDesc(String email);

    List<OtpChallenge> findByEmailAndCreatedAtAfter(String email, Instant after);

    /** Transactional here, not on the caller: the cleanup job calls it directly, so a proxy on the job would not apply. */
    @Modifying
    @Transactional
    @Query("delete from OtpChallenge c where c.expiresAt < :before")
    int deleteExpired(Instant before);
}
