package com.apigw.platform.audit;

import java.util.List;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AuditRepository extends JpaRepository<AuditEvent, Long> {

    List<AuditEvent> findAllByOrderByOccurredAtDescIdDesc(Pageable page);

    List<AuditEvent> findByObjectTypeAndObjectIdOrderByOccurredAtDescIdDesc(String objectType, String objectId);
}
