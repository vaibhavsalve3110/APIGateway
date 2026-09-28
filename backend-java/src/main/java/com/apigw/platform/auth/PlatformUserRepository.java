package com.apigw.platform.auth;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PlatformUserRepository extends JpaRepository<PlatformUser, UUID> {

    Optional<PlatformUser> findByEmail(String email);

    boolean existsByEmail(String email);

    List<PlatformUser> findAllByOrderByFullNameAsc();
}
