package com.apigw.platform.auth;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.security.Actor;
import com.apigw.platform.security.CurrentActor;

/** Sign-in for both portals: CAPTCHA, then a one-time code by e-mail. Open endpoints — see SecurityConfig. */
@RestController
@RequestMapping("/api/auth")
class AuthController {

    private final CaptchaService captcha;
    private final OtpService otp;

    AuthController(CaptchaService captcha, OtpService otp) {
        this.captcha = captcha;
        this.otp = otp;
    }

    record CodeRequest(@NotBlank @Email String email, @NotBlank String captchaId, @NotBlank String captchaAnswer) {
    }

    record VerifyRequest(@NotBlank @Email String email, @NotBlank String code) {
    }

    record Me(String username, java.util.Set<String> roles, String partnerCode) {
    }

    /** A fresh CAPTCHA image; solving it is required before any code is sent. */
    @PostMapping("/captcha")
    CaptchaService.Challenge captcha() {
        return captcha.issue();
    }

    @PostMapping("/otp/request")
    OtpService.CodeRequested requestCode(@Valid @RequestBody CodeRequest request, HttpServletRequest http) {
        return otp.requestCode(request.email(), request.captchaId(), request.captchaAnswer(), clientIp(http));
    }

    @PostMapping("/otp/verify")
    OtpService.SignedIn verify(@Valid @RequestBody VerifyRequest request, HttpServletRequest http) {
        return otp.verify(request.email(), request.code(), clientIp(http));
    }

    /** Who the presented token belongs to; the portals call this on load to restore a session. */
    @GetMapping("/me")
    Me me() {
        Actor actor = CurrentActor.get();
        return new Me(actor.username(), actor.roles(), actor.partnerCode());
    }

    private static String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
