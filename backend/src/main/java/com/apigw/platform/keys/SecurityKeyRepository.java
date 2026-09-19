package com.apigw.platform.keys;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

import com.apigw.platform.common.Env;

public interface SecurityKeyRepository extends JpaRepository<SecurityKey, UUID> {

    List<SecurityKey> findByPartnerIdAndEnvironmentAndStatusIn(UUID partnerId, Env environment, Collection<KeyStatus> statuses);

    List<SecurityKey> findByPartnerIdAndStatusIn(UUID partnerId, Collection<KeyStatus> statuses);

    List<SecurityKey> findByPartnerIdOrderByCreatedAtDesc(UUID partnerId);

    List<SecurityKey> findByStatusAndExpiresAtLessThanEqual(KeyStatus status, Instant cutoff);

    Optional<SecurityKey> findByKeyHash(String keyHash);
}
