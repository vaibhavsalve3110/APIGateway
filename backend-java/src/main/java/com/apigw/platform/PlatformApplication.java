package com.apigw.platform;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class PlatformApplication {

    public static void main(String[] args) {
        // "Try it live" must send the Sandbox gateway's virtual-host name in the Host header, which the JDK HTTP
        // client blocks by default. Set before any HttpClient is created.
        System.setProperty("jdk.httpclient.allowRestrictedHeaders", "host");
        SpringApplication.run(PlatformApplication.class, args);
    }
}
