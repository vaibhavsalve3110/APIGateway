package com.apigw.platform.crypto;

import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.web.filter.OncePerRequestFilter;

import com.apigw.platform.crypto.PayloadCrypto.PayloadCryptoException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.ServletOutputStream;
import jakarta.servlet.WriteListener;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpServletResponseWrapper;

/**
 * Decrypts encrypted request bodies and encrypts every response, so that controllers, validators and
 * the error handling all go on dealing in ordinary JSON.
 *
 * <p>Registered at highest precedence (see {@code PayloadEncryptionFilterConfig}), which puts it outside
 * the Spring Security chain. That matters in both directions: the body is decrypted before anything
 * parses it, and Spring Security's own 401 and 403 responses are encrypted on the way out rather than
 * escaping in the clear.
 *
 * <p>The counterpart is {@code backend-python/app/middleware.py}; the two must behave alike, because
 * nginx routes portal traffic between the services per method and path and the portal cannot tell which
 * one answered.
 *
 * <p>Query strings are deliberately not encrypted: they name the route and its filters, and encrypting
 * them would mean turning every filtered GET into a POST. Nothing sensitive travels in one.
 *
 * @see PayloadCrypto
 */

public class PayloadEncryptionFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(PayloadEncryptionFilter.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    /**
     * Paths that never carry an encrypted payload: the public key itself (a client cannot encrypt
     * before it has the key), the health probe (a probe needing a key is not a probe), gateway usage
     * ingest (not portal traffic; it authenticates with its own shared token), and the documentation,
     * which is not an API call.
     */
    private static final String[] EXEMPT_PREFIXES = {
            "/api/crypto/", "/actuator/", "/internal/", "/v3/api-docs", "/swagger-ui", "/redoc",
    };

    private final PayloadCrypto crypto;
    private final boolean enforced;

    public PayloadEncryptionFilter(PayloadCrypto crypto, Environment env) {
        this.crypto = crypto;
        boolean prod = Arrays.asList(env.getActiveProfiles()).contains("prod");
        boolean flag = Boolean.parseBoolean(
                env.getProperty("apigw.payload.encryption-enforced", "false"));
        // Production always enforces, whatever the flag says, so a deployment cannot end up accepting
        // plaintext because someone left a default alone. Note the asymmetry with the Python service,
        // which reads ENVIRONMENT=production where this reads the "prod" Spring profile: both have to
        // be set on a real deployment.
        this.enforced = prod || flag;
        if (this.enforced) {
            log.info("Payload encryption is ENFORCED — unencrypted /api requests will be refused");
        }
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        for (String prefix : EXEMPT_PREFIXES) {
            if (path.startsWith(prefix)) {
                return true;
            }
        }
        // A CORS preflight carries no body and no key by definition, and refusing it would block the
        // request it is asking permission for.
        return "OPTIONS".equalsIgnoreCase(request.getMethod());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws jakarta.servlet.ServletException, IOException {

        String declared = request.getHeader(PayloadCrypto.HEADER_VERSION);
        String wrappedKey = request.getHeader(PayloadCrypto.HEADER_KEY);

        if (declared == null && wrappedKey == null) {
            if (enforced && request.getRequestURI().startsWith("/api/")) {
                reject(response, 400, "ENCRYPTION_REQUIRED",
                        "This endpoint accepts encrypted payloads only. Wrap the request as described at "
                                + "GET /api/crypto/public-key.", request.getRequestURI());
                return;
            }
            chain.doFilter(request, response);
            return;
        }

        if (declared != null && !PayloadCrypto.VERSION.equals(declared)) {
            reject(response, 400, "ENCRYPTION_VERSION",
                    "Unsupported payload encryption version '" + declared + "'; this service speaks '"
                            + PayloadCrypto.VERSION + "'.", request.getRequestURI());
            return;
        }

        if (wrappedKey == null) {
            reject(response, 400, "ENCRYPTION_KEY_MISSING",
                    PayloadCrypto.HEADER_VERSION + " was sent without " + PayloadCrypto.HEADER_KEY
                            + ", so there is no key to decrypt the payload with.", request.getRequestURI());
            return;
        }

        SecretKeySpec key;
        try {
            key = crypto.unwrapKey(wrappedKey);
        } catch (PayloadCryptoException e) {
            String presented = request.getHeader(PayloadCrypto.HEADER_KID);
            String hint = "";
            if (presented != null && !presented.equals(crypto.keyId())) {
                // By far the most common cause, and invisible otherwise: the page was loaded before a
                // key rotation and is still encrypting to the old public key.
                hint = " The key you used (" + presented + ") is not the current one (" + crypto.keyId()
                        + "); reload the portal.";
            }
            reject(response, 400, "ENCRYPTION_KEY_INVALID", e.getMessage() + "." + hint,
                    request.getRequestURI());
            return;
        }

        byte[] plaintext;
        try {
            plaintext = decryptBody(request, key);
        } catch (PayloadCryptoException e) {
            reject(response, 400, "ENCRYPTION_PAYLOAD_INVALID", e.getMessage() + ".",
                    request.getRequestURI());
            return;
        } catch (EnvelopeException e) {
            reject(response, 400, "ENCRYPTION_ENVELOPE_INVALID", e.getMessage(),
                    request.getRequestURI());
            return;
        }

        BufferingResponse buffered = new BufferingResponse(response);
        chain.doFilter(new DecryptedRequest(request, plaintext), buffered);
        encryptResponse(buffered, response, key);
    }

    // ---------------------------------------------------------------- request

    private byte[] decryptBody(HttpServletRequest request, SecretKeySpec key)
            throws IOException, PayloadCryptoException, EnvelopeException {
        byte[] raw = request.getInputStream().readAllBytes();
        if (raw.length == 0) {
            // A GET or DELETE: nothing to decrypt, but the response still is.
            return new byte[0];
        }
        String iv;
        String data;
        try {
            JsonNode envelope = JSON.readTree(raw);
            iv = envelope.get("iv").asText();
            data = envelope.get("data").asText();
        } catch (Exception e) {
            throw new EnvelopeException(
                    "An encrypted request body must be {\"iv\": \"...\", \"data\": \"...\"} with both base64.");
        }
        return crypto.decrypt(key, iv, data);
    }

    /** Hands the pipeline the decrypted body in place of the ciphertext that arrived. */
    private static final class DecryptedRequest extends HttpServletRequestWrapper {

        private final byte[] body;

        DecryptedRequest(HttpServletRequest request, byte[] body) {
            super(request);
            this.body = body;
        }

        @Override
        public int getContentLength() {
            return body.length;
        }

        @Override
        public long getContentLengthLong() {
            return body.length;
        }

        @Override
        public String getHeader(String name) {
            // Content-Length in the real request describes the ciphertext, which is longer. A
            // controller or converter that trusted it would read past the end of the decrypted body.
            if ("content-length".equalsIgnoreCase(name)) {
                return String.valueOf(body.length);
            }
            return super.getHeader(name);
        }

        @Override
        public ServletInputStream getInputStream() {
            ByteArrayInputStream source = new ByteArrayInputStream(body);
            return new ServletInputStream() {
                @Override
                public int read() {
                    return source.read();
                }

                @Override
                public boolean isFinished() {
                    return source.available() == 0;
                }

                @Override
                public boolean isReady() {
                    return true;
                }

                @Override
                public void setReadListener(ReadListener listener) {
                    throw new UnsupportedOperationException("the decrypted body is already in memory");
                }
            };
        }

        @Override
        public BufferedReader getReader() {
            return new BufferedReader(new InputStreamReader(getInputStream(), StandardCharsets.UTF_8));
        }
    }

    // ---------------------------------------------------------------- response

    /**
     * Collects the response so it can be encrypted as one message.
     *
     * <p>Buffered rather than streamed because GCM authenticates the whole message: a per-chunk envelope
     * would need its own IV and tag per chunk for the client to reassemble in order. Every response here
     * is a small JSON document, so there is nothing to stream.
     */
    private static final class BufferingResponse extends HttpServletResponseWrapper {

        private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        private ServletOutputStream stream;
        private PrintWriter writer;

        BufferingResponse(HttpServletResponse response) {
            super(response);
        }

        @Override
        public ServletOutputStream getOutputStream() {
            if (writer != null) {
                throw new IllegalStateException("getWriter() has already been called on this response");
            }
            if (stream == null) {
                stream = new ServletOutputStream() {
                    @Override
                    public void write(int b) {
                        buffer.write(b);
                    }

                    @Override
                    public boolean isReady() {
                        return true;
                    }

                    @Override
                    public void setWriteListener(WriteListener listener) {
                        throw new UnsupportedOperationException("the response is buffered in memory");
                    }
                };
            }
            return stream;
        }

        @Override
        public PrintWriter getWriter() {
            if (stream != null) {
                throw new IllegalStateException("getOutputStream() has already been called on this response");
            }
            if (writer == null) {
                writer = new PrintWriter(new java.io.OutputStreamWriter(buffer, StandardCharsets.UTF_8), true);
            }
            return writer;
        }

        @Override
        public void flushBuffer() throws IOException {
            if (writer != null) {
                writer.flush();
            }
            // Deliberately not flushing to the real response: committing it here would make the status
            // and headers unchangeable, and the body is still plaintext at this point.
        }

        byte[] body() {
            if (writer != null) {
                writer.flush();
            }
            return buffer.toByteArray();
        }
    }

    private void encryptResponse(BufferingResponse buffered, HttpServletResponse real, SecretKeySpec key)
            throws IOException {
        byte[] plaintext = buffered.body();

        if (plaintext.length == 0) {
            // A 204, or a response that genuinely has no body. An envelope around nothing would just
            // be a lie with a tag on it.
            return;
        }

        String contentType = buffered.getContentType();
        if (contentType == null || !contentType.contains("json")) {
            // Anything non-JSON passes through untouched; nothing under /api/ answers this way.
            real.getOutputStream().write(plaintext);
            return;
        }

        byte[] envelope;
        try {
            PayloadCrypto.Envelope sealed = crypto.encrypt(key, plaintext);
            envelope = JSON.writeValueAsBytes(sealed);
        } catch (PayloadCryptoException e) {
            // Must not fall back to sending the plaintext it failed to encrypt.
            log.error("Could not encrypt a response body", e);
            real.reset();
            reject(real, 500, "ENCRYPTION_FAILED", "The response could not be encrypted.", "");
            return;
        }

        // The envelope is JSON whatever the original was, so problem+json becomes json here. The
        // status is left alone: a 404 stays a 404, with its body encrypted.
        real.setContentType("application/json");
        real.setContentLength(envelope.length);
        real.setHeader(PayloadCrypto.HEADER_VERSION, PayloadCrypto.VERSION);
        real.setHeader(PayloadCrypto.HEADER_KID, crypto.keyId());
        // The body is ciphertext; nothing between here and the browser should hold on to it.
        real.setHeader("Cache-Control", "no-store");
        real.getOutputStream().write(envelope);
    }

    // ---------------------------------------------------------------- rejection

    /**
     * Answers in plaintext.
     *
     * <p>A client that got the envelope wrong cannot be assumed able to decrypt the explanation, and an
     * unreadable error about encryption is how an afternoon disappears. These carry no data beyond the
     * fact that encryption failed.
     */
    private void reject(HttpServletResponse response, int status, String code, String detail, String instance)
            throws IOException {
        response.setStatus(status);
        response.setContentType("application/problem+json");
        byte[] body = JSON.writeValueAsBytes(java.util.Map.of(
                "type", "about:blank",
                "title", status == 400 ? "Bad Request" : "Internal Server Error",
                "status", status,
                "detail", detail,
                "code", code,
                "instance", instance));
        response.setContentLength(body.length);
        response.getOutputStream().write(body);
    }

    /** A body that was not a valid envelope at all, as distinct from one that failed to decrypt. */
    private static final class EnvelopeException extends Exception {

        EnvelopeException(String message) {
            super(message);
        }
    }
}
