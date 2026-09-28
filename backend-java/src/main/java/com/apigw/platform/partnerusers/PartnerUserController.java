package com.apigw.platform.partnerusers;

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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.partnerusers.PartnerUserDtos.AccessRequest;
import com.apigw.platform.partnerusers.PartnerUserDtos.CreateRequest;
import com.apigw.platform.partnerusers.PartnerUserDtos.PartnerUserView;
import com.apigw.platform.partnerusers.PartnerUserDtos.UpdateRequest;
import com.apigw.platform.security.Actor;
import com.apigw.platform.security.CurrentActor;

/**
 * Portal logins for an organization (CP-PTN-04). Admin only, like the rest of {@code /api/admin/**}.
 * The organization's signature key pair and IPV salt are managed on {@code /api/admin/partners/{id}}.
 */
@RestController
@RequestMapping("/api/admin")
public class PartnerUserController {

    private final PartnerUserService service;

    public PartnerUserController(PartnerUserService service) {
        this.service = service;
    }

    /** All partner users, or those of one partner with {@code ?partnerId=}. */
    @GetMapping("/partner-users")
    public List<PartnerUserView> list(@RequestParam(required = false) UUID partnerId) {
        return service.list(partnerId);
    }

    @GetMapping("/partner-users/{id}")
    public PartnerUserView get(@PathVariable UUID id) {
        return service.view(id);
    }

    @GetMapping("/partners/{partnerId}/users")
    public List<PartnerUserView> listForPartner(@PathVariable UUID partnerId) {
        return service.list(partnerId);
    }

    @PostMapping("/partners/{partnerId}/users")
    public PartnerUserView create(@PathVariable UUID partnerId, @Valid @RequestBody CreateRequest request) {
        return service.create(partnerId, request, actor());
    }

    @PutMapping("/partner-users/{id}")
    public PartnerUserView update(@PathVariable UUID id, @Valid @RequestBody UpdateRequest request) {
        return service.update(id, request, actor());
    }

    @PostMapping("/partner-users/{id}/access")
    public PartnerUserView setAccess(@PathVariable UUID id, @Valid @RequestBody AccessRequest request) {
        return service.setAccess(id, request.status(), actor());
    }

    /** Permanent, and refused until the user's access has been revoked. */
    @DeleteMapping("/partner-users/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID id) {
        service.delete(id, actor());
    }

    private Actor actor() {
        return CurrentActor.get();
    }
}
