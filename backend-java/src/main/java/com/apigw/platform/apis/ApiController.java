package com.apigw.platform.apis;

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

import com.apigw.platform.apis.importer.ImportModels.ImportRequest;
import com.apigw.platform.apis.importer.ImportModels.ImportResult;
import com.apigw.platform.apis.importer.ImportService;
import com.apigw.platform.security.CurrentActor;

@RestController
@RequestMapping("/api/admin/apis")
class ApiController {

    private final ApiService apis;
    private final ImportService importer;

    ApiController(ApiService apis, ImportService importer) {
        this.apis = apis;
        this.importer = importer;
    }

    @GetMapping
    List<ApiView> list() {
        return apis.list();
    }

    @GetMapping("/{id}")
    ApiView get(@PathVariable UUID id) {
        return apis.get(id);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    ApiView create(@Valid @RequestBody ApiRequest request) {
        return apis.create(request, CurrentActor.get());
    }

    /** CP-API-06: read a Swagger / OpenAPI file or Postman collection; nothing is saved until the editor saves. */
    @PostMapping("/import")
    ImportResult importFile(@Valid @RequestBody ImportRequest request) {
        return importer.read(request.content());
    }

    @PutMapping("/{id}")
    ApiView update(@PathVariable UUID id, @Valid @RequestBody ApiRequest request) {
        return apis.update(id, request, CurrentActor.get());
    }

    @PutMapping("/{id}/guest-visibility")
    ApiView guestVisibility(@PathVariable UUID id, @RequestBody GuestVisibility body) {
        return apis.setGuestVisible(id, body.visible(), CurrentActor.get());
    }

    @PostMapping("/{id}/disable")
    ApiView disable(@PathVariable UUID id) {
        return apis.disable(id, CurrentActor.get());
    }

    @PostMapping("/{id}/enable")
    ApiView enable(@PathVariable UUID id) {
        return apis.enable(id, CurrentActor.get());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable UUID id) {
        apis.delete(id, CurrentActor.get());
    }

    record GuestVisibility(boolean visible) {
    }
}
