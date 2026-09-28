package com.apigw.platform.auth;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import javax.imageio.ImageIO;

import org.springframework.stereotype.Service;

/**
 * A CAPTCHA drawn by the platform itself, so no sign-in detail reaches a third party.
 *
 * <p>Challenges live in memory for {@link #TTL} and are single-use: solving one, failing one, or letting it
 * expire removes it. That keeps the answer off the wire and out of the database; the trade-off is that a
 * restart (or a second instance without a shared cache) invalidates outstanding challenges, and the user
 * simply gets a new image.
 */
@Service
public class CaptchaService {

    static final Duration TTL = Duration.ofMinutes(5);
    private static final int WIDTH = 190;
    private static final int HEIGHT = 60;
    private static final int LENGTH = 5;
    /** No 0/O/1/I/5/S: they are unreadable once distorted. */
    private static final String ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ234679";
    private static final SecureRandom RANDOM = new SecureRandom();

    private final Map<String, Entry> challenges = new ConcurrentHashMap<>();
    private final Clock clock;

    public CaptchaService(Clock clock) {
        this.clock = clock;
    }

    private record Entry(String answer, Instant expiresAt) {
    }

    public record Challenge(String challengeId, String image, long expiresInSeconds) {
    }

    public Challenge issue() {
        purgeExpired();
        String answer = randomText();
        String id = UUID.randomUUID().toString();
        challenges.put(id, new Entry(answer, clock.instant().plus(TTL)));
        return new Challenge(id, "data:image/png;base64," + Base64.getEncoder().encodeToString(draw(answer)),
                TTL.toSeconds());
    }

    /** True once only: the challenge is removed whether the answer was right or wrong. */
    public boolean solve(String challengeId, String answer) {
        if (challengeId == null || answer == null) {
            return false;
        }
        Entry entry = challenges.remove(challengeId);
        return entry != null
                && clock.instant().isBefore(entry.expiresAt())
                && entry.answer().equalsIgnoreCase(answer.trim());
    }

    private void purgeExpired() {
        Instant now = clock.instant();
        challenges.entrySet().removeIf(e -> !now.isBefore(e.getValue().expiresAt()));
    }

    private static String randomText() {
        StringBuilder text = new StringBuilder(LENGTH);
        for (int i = 0; i < LENGTH; i++) {
            text.append(ALPHABET.charAt(RANDOM.nextInt(ALPHABET.length())));
        }
        return text.toString();
    }

    private static byte[] draw(String text) {
        BufferedImage image = new BufferedImage(WIDTH, HEIGHT, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = image.createGraphics();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(new Color(0xF4, 0xF6, 0xF9));
            g.fillRect(0, 0, WIDTH, HEIGHT);

            // Speckles and lines, so the glyphs do not sit on a clean background.
            for (int i = 0; i < 380; i++) {
                g.setColor(new Color(RANDOM.nextInt(160) + 80, RANDOM.nextInt(160) + 80, RANDOM.nextInt(160) + 80));
                g.fillRect(RANDOM.nextInt(WIDTH), RANDOM.nextInt(HEIGHT), 2, 2);
            }
            g.setStroke(new BasicStroke(1.4f));
            for (int i = 0; i < 4; i++) {
                g.setColor(new Color(RANDOM.nextInt(120) + 60, RANDOM.nextInt(120) + 60, RANDOM.nextInt(120) + 60, 150));
                g.drawLine(RANDOM.nextInt(WIDTH), RANDOM.nextInt(HEIGHT), RANDOM.nextInt(WIDTH), RANDOM.nextInt(HEIGHT));
            }

            int x = 20;
            for (char c : text.toCharArray()) {
                AffineTransform saved = g.getTransform();
                double angle = (RANDOM.nextDouble() - 0.5) * 0.7;
                g.rotate(angle, x, HEIGHT / 2.0);
                g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 34 + RANDOM.nextInt(8)));
                g.setColor(new Color(20 + RANDOM.nextInt(60), 30 + RANDOM.nextInt(60), 60 + RANDOM.nextInt(70)));
                g.drawString(String.valueOf(c), x, 44 - RANDOM.nextInt(8));
                g.setTransform(saved);
                x += 30 + RANDOM.nextInt(6);
            }
        } finally {
            g.dispose();
        }
        try (ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            ImageIO.write(image, "png", out);
            return out.toByteArray();
        } catch (IOException e) {
            throw new UncheckedIOException("Unable to render the CAPTCHA image", e);
        }
    }

    /** Only for tests and the development banner: reveals the answer without consuming the challenge. */
    String peek(String challengeId) {
        Entry entry = challenges.get(challengeId);
        return entry == null ? null : entry.answer().toLowerCase(Locale.ROOT);
    }
}
