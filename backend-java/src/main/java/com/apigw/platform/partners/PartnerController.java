package com.apigw.platform.partners;

import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.partners.PartnerDtos.GroupRequest;
import com.apigw.platform.partners.PartnerDtos.GroupView;
import com.apigw.platform.partners.PartnerDtos.PartnerRequest;
import com.apigw.platform.partners.PartnerDtos.IssuedCredentials;
import com.apigw.platform.partners.PartnerDtos.PartnerView;
import com.apigw.platform.partners.PartnerDtos.RevealedSalt;
import com.apigw.platform.partners.PartnerDtos.UpdateRequest;
import com.apigw.platform.partners.PartnerDtos.StatusRequest;
import com.apigw.platform.partners.PartnerDtos.TierRequest;
import com.apigw.platform.security.CurrentActor;

@RestController
@RequestMapping("/api/admin")
class PartnerController {

    private final PartnerService partners;
    private final PartnerCredentialService credentials;

    PartnerController(PartnerService partners, PartnerCredentialService credentials) {
        this.partners = partners;
        this.credentials = credentials;
    }

    @GetMapping("/partner-groups")
    List<GroupView> groups() {
        return partners.listGroups();
    }

    @PostMapping("/partner-groups")
    @ResponseStatus(HttpStatus.CREATED)
    GroupView createGroup(@Valid @RequestBody GroupRequest request) {
        return partners.createGroup(request, CurrentActor.get());
    }

    @GetMapping("/partners")
    List<PartnerView> list() {
        return partners.listPartners();
    }

    @GetMapping("/partners/{id}")
    PartnerView get(@PathVariable UUID id) {
        return partners.view(id);
    }

    /** Registering an organization also issues its signature key pair and IPV salt, returned once here. */
    @PostMapping("/partners")
    @ResponseStatus(HttpStatus.CREATED)
    IssuedCredentials create(@Valid @RequestBody PartnerRequest request) {
        return partners.create(request, CurrentActor.get());
    }

    @PutMapping("/partners/{id}")
    PartnerView update(@PathVariable UUID id, @Valid @RequestBody UpdateRequest request) {
        return partners.update(id, request, CurrentActor.get());
    }

    /** Recreates the organization's signature key pair; the new private key is shown once. */
    @PostMapping("/partners/{id}/signature")
    IssuedCredentials regenerateSignature(@PathVariable UUID id) {
        return credentials.regenerateSignature(id, CurrentActor.get());
    }

    @PostMapping("/partners/{id}/ipv-salt")
    IssuedCredentials rotateIpvSalt(@PathVariable UUID id) {
        return credentials.rotateIpvSalt(id, CurrentActor.get());
    }

    @PostMapping("/partners/{id}/ipv-salt/reveal")
    RevealedSalt revealIpvSalt(@PathVariable UUID id) {
        return credentials.revealIpvSalt(id, CurrentActor.get());
    }

    @PutMapping("/partners/{id}/access-tier")
    PartnerView changeTier(@PathVariable UUID id, @Valid @RequestBody TierRequest request) {
        return partners.changeTier(id, request.accessTier(), CurrentActor.get());
    }

    @PutMapping("/partners/{id}/status")
    PartnerView setStatus(@PathVariable UUID id, @Valid @RequestBody StatusRequest request) {
        return partners.setStatus(id, request.status(), CurrentActor.get());
    }
}
