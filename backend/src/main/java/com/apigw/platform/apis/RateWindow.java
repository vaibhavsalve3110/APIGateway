package com.apigw.platform.apis;

/** Rate-limit window for CP-API-08 (requests per minute / hour / day). */
public enum RateWindow {
    MINUTE(60),
    HOUR(3_600),
    DAY(86_400);

    private final int seconds;

    RateWindow(int seconds) {
        this.seconds = seconds;
    }

    public int seconds() {
        return seconds;
    }
}
