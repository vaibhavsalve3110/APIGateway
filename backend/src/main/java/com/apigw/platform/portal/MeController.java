package com.apigw.platform.portal;

import java.util.Set;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.security.Actor;
import com.apigw.platform.security.CurrentActor;

/** Lets either portal discover who is signed in and which screens to show. */
@RestController
class MeController {

    record MeView(String username, Set<String> roles, String partnerCode) {
    }

    @GetMapping("/api/me")
    MeView me() {
        Actor actor = CurrentActor.get();
        return new MeView(actor.username(), actor.roles(), actor.partnerCode());
    }
}
