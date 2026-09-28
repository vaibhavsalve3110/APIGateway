package com.apigw.platform.errors;

import java.time.Instant;
import java.util.List;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface ErrorEventRepository extends JpaRepository<ErrorEvent, Long> {

    List<ErrorEvent> findAllByOrderByOccurredAtDescIdDesc(Pageable page);

    List<ErrorEvent> findBySourceOrderByOccurredAtDescIdDesc(String source, Pageable page);

    @Modifying
    @Query("delete from ErrorEvent e where e.occurredAt < :before")
    int deleteOlderThan(Instant before);
}
