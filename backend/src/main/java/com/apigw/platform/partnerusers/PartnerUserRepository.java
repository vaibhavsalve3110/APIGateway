package com.apigw.platform.partnerusers;

import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PartnerUserRepository extends JpaRepository<PartnerUser, UUID> {

    List<PartnerUser> findByPartnerIdOrderByFullNameAsc(UUID partnerId);

    List<PartnerUser> findAllByOrderByFullNameAsc();

    boolean existsByEmail(String email);

    java.util.Optional<PartnerUser> findByEmail(String email);

    long countByPartnerId(UUID partnerId);
}
