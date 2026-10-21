/**
 * Hybrid encryption for everything the portals send and receive (VAPT: payload confidentiality).
 *
 * Per request: a fresh AES-256 key, wrapped with the platform's RSA public key and sent in a header,
 * with the body and the reply as AES-256-GCM under that key.
 *
 *     X-Encrypted:   v1
 *     X-Encrypt-Kid: which public key was used
 *     X-Encrypt-Key: base64( RSA-OAEP-SHA256( 32-byte AES key ) )
 *
 *     body, and every response:  {"iv": "base64(12 bytes)", "data": "base64(ciphertext||tag)"}
 *
 * The key goes in a header rather than the body so one path covers every method: a GET has no body to
 * carry it, but its response still has to be encrypted. The reply reuses the request's key with a
 * fresh IV, so the browser needs no keypair of its own and nothing has to be stored between requests.
 *
 * Both backends serve the same public key and the same `kid` — nginx may route a call to either, and
 * this code cannot tell which answered.
 *
 * This sits on top of TLS rather than replacing it. It keeps payloads unreadable in an intercepting
 * proxy, which is how these findings are raised. It is not a secret kept from the user: the public key
 * is public and this page can read its own cleartext.
 *
 * Needs `crypto.subtle`, which browsers expose only in a secure context — https, or localhost. Over
 * plain http on any other host it is simply absent, which `isAvailable` reports so the caller can say
 * so rather than failing with "cannot read property encrypt of undefined".
 */

const VERSION = "v1";
export const HEADER_VERSION = "X-Encrypted";
export const HEADER_KEY = "X-Encrypt-Key";
export const HEADER_KID = "X-Encrypt-Kid";

const AES_KEY_BITS = 256;
const IV_BYTES = 12;

interface KeyDescriptor {
  kid: string;
  algorithm: string;
  publicKeyPem: string;
}

/** What one request needs: the headers to send, and the key its reply will come back under. */
export interface Sealed {
  headers: Record<string, string>;
  body?: string;
  key: CryptoKey;
}

export function isAvailable(): boolean {
  return typeof crypto !== "undefined" && typeof crypto.subtle !== "undefined";
}

function base64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  // A spread into String.fromCharCode overflows the call stack on large bodies, so step through it.
  for (let i = 0; i < view.length; i += 1) {
    binary += String.fromCharCode(view[i]);
  }
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function derFromPem(pem: string): Uint8Array {
  const body = pem
    .replace(/-----BEGIN PUBLIC KEY-----/, "")
    .replace(/-----END PUBLIC KEY-----/, "")
    .replace(/\s+/g, "");
  return fromBase64(body);
}

/**
 * The platform's public key, fetched once and kept.
 *
 * Held as the promise rather than the result so that several calls made before the first one returns
 * share a single fetch instead of racing — which on a portal's first render is every call on the page.
 */
let pending: Promise<{ descriptor: KeyDescriptor; key: CryptoKey }> | null = null;

async function publicKey(baseUrl: string): Promise<{ descriptor: KeyDescriptor; key: CryptoKey }> {
  if (!pending) {
    pending = (async () => {
      const response = await fetch(`${baseUrl}/api/crypto/public-key`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Could not fetch the encryption key (HTTP ${response.status})`);
      }
      const descriptor = (await response.json()) as KeyDescriptor;
      const key = await crypto.subtle.importKey(
        "spki",
        derFromPem(descriptor.publicKeyPem) as unknown as ArrayBuffer,
        { name: "RSA-OAEP", hash: "SHA-256" },
        false,
        ["encrypt"],
      );
      return { descriptor, key };
    })();
    // A failed fetch must not be cached, or the portal never recovers without a reload.
    pending.catch(() => {
      pending = null;
    });
  }
  return pending;
}

/** Forget the cached key, so the next call fetches the current one. Used after a rotation. */
export function forgetKey(): void {
  pending = null;
}

/** Wraps a request: a new key, the headers that carry it, and the encrypted body if there is one. */
export async function seal(baseUrl: string, body: unknown): Promise<Sealed> {
  const { descriptor, key: rsaKey } = await publicKey(baseUrl);

  const aesKey = await crypto.subtle.generateKey({ name: "AES-GCM", length: AES_KEY_BITS }, true, [
    "encrypt",
    "decrypt",
  ]);
  const rawKey = await crypto.subtle.exportKey("raw", aesKey);
  const wrapped = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsaKey, rawKey);

  const headers: Record<string, string> = {
    [HEADER_VERSION]: VERSION,
    [HEADER_KID]: descriptor.kid,
    [HEADER_KEY]: base64(wrapped),
  };

  if (body === undefined) {
    return { headers, key: aesKey };
  }

  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const data = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    aesKey,
    new TextEncoder().encode(JSON.stringify(body)) as unknown as ArrayBuffer,
  );
  return {
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ iv: base64(iv), data: base64(data) }),
    key: aesKey,
  };
}

/** Opens a reply that came back encrypted. Throws if it has been altered — GCM authenticates. */
export async function open(key: CryptoKey, text: string): Promise<string> {
  const envelope = JSON.parse(text) as { iv: string; data: string };
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64(envelope.iv) as unknown as ArrayBuffer },
    key,
    fromBase64(envelope.data) as unknown as ArrayBuffer,
  );
  return new TextDecoder().decode(plaintext);
}
