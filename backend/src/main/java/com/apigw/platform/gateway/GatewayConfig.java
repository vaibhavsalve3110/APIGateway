package com.apigw.platform.gateway;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

import com.apigw.platform.config.ApigwProperties;

@Configuration
class GatewayConfig {

    @Bean
    GatewayClient gatewayClient(ApigwProperties props, RestClient.Builder builder) {
        return props.gateway().enabled() ? new ApisixGatewayClient(props, builder) : new NoopGatewayClient();
    }
}
