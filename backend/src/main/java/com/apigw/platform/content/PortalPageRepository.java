package com.apigw.platform.content;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PortalPageRepository extends JpaRepository<PortalPage, UUID> {

    List<PortalPage> findAllByOrderByCategoryAscPositionAscTitleAsc();

    List<PortalPage> findByStatusOrderByCategoryAscPositionAscTitleAsc(PageStatus status);

    Optional<PortalPage> findBySlug(String slug);
}
