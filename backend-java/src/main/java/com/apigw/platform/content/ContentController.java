package com.apigw.platform.content;

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

import com.apigw.platform.content.ContentDtos.PageRequest;
import com.apigw.platform.content.ContentDtos.PageView;
import com.apigw.platform.security.CurrentActor;

/** Developer Portal content (CP-API-10), edited by Admins in the Management Portal. */
@RestController
@RequestMapping("/api/admin/pages")
class ContentController {

    private final ContentService content;

    ContentController(ContentService content) {
        this.content = content;
    }

    @GetMapping
    List<PageView> list() {
        return content.list();
    }

    @GetMapping("/{id}")
    PageView get(@PathVariable UUID id) {
        return content.view(id);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    PageView create(@Valid @RequestBody PageRequest request) {
        return content.create(request, CurrentActor.get());
    }

    /** Saves a new version; what partners see does not change until {@link #publish}. */
    @PutMapping("/{id}")
    PageView update(@PathVariable UUID id, @Valid @RequestBody PageRequest request) {
        return content.update(id, request, CurrentActor.get());
    }

    @PostMapping("/{id}/publish")
    PageView publish(@PathVariable UUID id) {
        return content.publish(id, CurrentActor.get());
    }

    @PostMapping("/{id}/unpublish")
    PageView unpublish(@PathVariable UUID id) {
        return content.unpublish(id, CurrentActor.get());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable UUID id) {
        content.delete(id, CurrentActor.get());
    }
}
