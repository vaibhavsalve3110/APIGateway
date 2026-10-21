package com.apigw.platform.crypto;

import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;

/**
 * Puts {@link PayloadEncryptionFilter} outside everything else.
 *
 * <p>Registering it at highest precedence matters in both directions: a request body is decrypted before
 * anything parses it, and Spring Security's own 401 and 403 responses are encrypted on the way out
 * instead of escaping in the clear — which is exactly the kind of response a tester looks at first.
 *
 * <p>The filter is built here rather than annotated {@code @Component}, because Boot auto-registers an
 * annotated filter at a default order <em>as well</em> as through this bean, leaving two registrations
 * of the same filter at different places in the chain.
 */
@Configuration
public class PayloadEncryptionFilterConfig {

    @Bean
    FilterRegistrationBean<PayloadEncryptionFilter> payloadEncryption(PayloadCrypto crypto, Environment env) {
        FilterRegistrationBean<PayloadEncryptionFilter> registration =
                new FilterRegistrationBean<>(new PayloadEncryptionFilter(crypto, env));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        registration.addUrlPatterns("/*");
        return registration;
    }
}
