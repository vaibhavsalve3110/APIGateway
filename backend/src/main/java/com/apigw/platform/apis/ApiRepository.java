package com.apigw.platform.apis;

import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ApiRepository extends JpaRepository<ApiDefinition, UUID> {

    List<ApiDefinition> findAllByOrderByNameAsc();

    List<ApiDefinition> findByStatusOrderByNameAsc(ApiStatus status);
}
