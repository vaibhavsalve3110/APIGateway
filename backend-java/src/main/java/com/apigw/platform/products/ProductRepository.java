package com.apigw.platform.products;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductRepository extends JpaRepository<Product, UUID> {

    List<Product> findAllByOrderByNameAsc();

    List<Product> findByStatusOrderByNameAsc(ProductStatus status);

    Optional<Product> findBySlug(String slug);

    boolean existsBySlug(String slug);
}
