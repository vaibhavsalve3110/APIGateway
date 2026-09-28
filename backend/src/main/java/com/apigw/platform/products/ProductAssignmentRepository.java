package com.apigw.platform.products;

import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductAssignmentRepository extends JpaRepository<ProductAssignment, UUID> {

    List<ProductAssignment> findByProductId(UUID productId);

    List<ProductAssignment> findByPartnerId(UUID partnerId);

    List<ProductAssignment> findByPartnerIdAndPartnerUserIdIsNull(UUID partnerId);

    List<ProductAssignment> findByPartnerUserId(UUID partnerUserId);

    boolean existsByProductIdAndPartnerIdAndPartnerUserIdIsNull(UUID productId, UUID partnerId);

    boolean existsByProductIdAndPartnerUserId(UUID productId, UUID partnerUserId);
}
