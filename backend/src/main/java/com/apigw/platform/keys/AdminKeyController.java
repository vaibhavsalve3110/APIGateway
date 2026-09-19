package com.apigw.platform.keys;

import java.util.List;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.common.Env;
import com.apigw.platform.keys.KeyViews.GeneratedKey;
import com.apigw.platform.keys.KeyViews.KeyView;
import com.apigw.platform.security.CurrentActor;

@RestController
@RequestMapping("/api/admin")
class AdminKeyController {

    private final SecurityKeyService keys;

    AdminKeyController(SecurityKeyService keys) {
        this.keys = keys;
    }

    @GetMapping("/partners/{partnerId}/keys")
    List<KeyView> list(@PathVariable UUID partnerId) {
        return keys.list(partnerId);
    }

    @PostMapping("/partners/{partnerId}/keys/{environment}")
    @ResponseStatus(HttpStatus.CREATED)
    GeneratedKey generate(@PathVariable UUID partnerId, @PathVariable Env environment) {
        return keys.generate(partnerId, environment, CurrentActor.get());
    }

    @PostMapping("/keys/{keyId}/revoke")
    KeyView revoke(@PathVariable UUID keyId) {
        return keys.revokeNewKey(keyId, CurrentActor.get());
    }
}
