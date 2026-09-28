package com.apigw.platform.products;

import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.products.ProductDtos.AssignRequest;
import com.apigw.platform.products.ProductDtos.ProductRequest;
import com.apigw.platform.products.ProductDtos.ProductView;
import com.apigw.platform.security.CurrentActor;

/** Products — journeys of dependent APIs (CP-API-09). Admin only, like the rest of {@code /api/admin/**}. */
@RestController
@RequestMapping("/api/admin/products")
class ProductController {

    private final ProductService products;

    ProductController(ProductService products) {
        this.products = products;
    }

    @GetMapping
    List<ProductView> list() {
        return products.list();
    }

    @GetMapping("/{id}")
    ProductView get(@PathVariable UUID id) {
        return products.view(id);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    ProductView create(@Valid @RequestBody ProductRequest request) {
        return products.create(request, CurrentActor.get());
    }

    @PutMapping("/{id}")
    ProductView update(@PathVariable UUID id, @Valid @RequestBody ProductRequest request) {
        return products.update(id, request, CurrentActor.get());
    }

    /** Publishing shows the journey to the partners it is assigned to; withdrawing takes it back to draft. */
    @PostMapping("/{id}/publish")
    ProductView publish(@PathVariable UUID id) {
        return products.setPublished(id, true, CurrentActor.get());
    }

    @PostMapping("/{id}/unpublish")
    ProductView unpublish(@PathVariable UUID id) {
        return products.setPublished(id, false, CurrentActor.get());
    }

    /** Assign to a whole organization, or to one named user inside it. */
    @PostMapping("/{id}/assignments")
    ProductView assign(@PathVariable UUID id, @Valid @RequestBody AssignRequest request) {
        return products.assign(id, request, CurrentActor.get());
    }

    @DeleteMapping("/{id}/assignments/{assignmentId}")
    ProductView unassign(@PathVariable UUID id, @PathVariable UUID assignmentId) {
        return products.unassign(id, assignmentId, CurrentActor.get());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable UUID id) {
        products.delete(id, CurrentActor.get());
    }
}
