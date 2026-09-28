package com.apigw.platform.errors;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.errors.ErrorDtos.ErrorView;

/**
 * The system error log. Admin only, like the rest of {@code /api/admin/**}: rows carry stack traces and the
 * addresses of people who were signed in.
 */
@RestController
@RequestMapping("/api/admin")
class ErrorController {

    private final ErrorLogService errors;

    ErrorController(ErrorLogService errors) {
        this.errors = errors;
    }

    @GetMapping("/errors")
    List<ErrorView> latest(@RequestParam(required = false) String source,
                           @RequestParam(defaultValue = "100") int limit) {
        return errors.latest(source, limit);
    }
}
