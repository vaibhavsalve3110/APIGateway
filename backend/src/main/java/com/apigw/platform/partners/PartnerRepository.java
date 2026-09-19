package com.apigw.platform.partners;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PartnerRepository extends JpaRepository<Partner, UUID> {

    List<Partner> findAllByOrderByNameAsc();

    Optional<Partner> findByCode(String code);

    boolean existsByCode(String code);

    boolean existsByClientIdSandboxOrClientIdProduction(String sandbox, String production);

    long countByGroupId(UUID groupId);
}
