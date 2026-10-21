/**
 * Gate: does the browser's WebCrypto interoperate with both backends' payload encryption?
 *
 * This covers the one risk the server-side gate cannot. `crypto.subtle` is the same API in Node and in
 * a browser, and the bytes it produces are what matter: RSA-OAEP's MGF1 digest and AES-GCM's tag
 * placement have to match what Python's `cryptography` and Java's JCE expect. Get that wrong and
 * everything typechecks, every unit test passes, and the portal fails in the browser with
 * "decryption failed" — which is a miserable thing to debug from a screenshot.
 *
 * It mirrors `frontend/packages/ui/src/payloadCrypto.ts` step for step on purpose: if this passes and
 * the portal does not, the fault is in the portal's wiring rather than in the crypto.
 *
 * Both backends are checked, because nginx routes portal traffic between them per method and path and
 * the portal cannot tell which one answered.
 *
 * Needs the stack up:  node infra/tools/check-webcrypto-interop.mjs
 */

import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

const TARGETS = [
  ["backend-python", "http://127.0.0.1:18090"],
  ["backend-java", "http://127.0.0.1:18088"],
];

const TOKEN = execFileSync(process.execPath, [join(HERE, "mint-token.js"), "admin@apigw.local", "ADMIN"], {
  encoding: "utf-8",
}).trim();

let failures = 0;

function check(label, ok, detail = "") {
  if (ok) {
    console.log(`  ok    ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` : ${detail}` : ""}`);
  }
}

const b64 = (buffer) => Buffer.from(buffer).toString("base64");
const fromB64 = (value) => new Uint8Array(Buffer.from(value, "base64"));

function derFromPem(pem) {
  return fromB64(
    pem
      .replace(/-----BEGIN PUBLIC KEY-----/, "")
      .replace(/-----END PUBLIC KEY-----/, "")
      .replace(/\s+/g, ""),
  );
}

async function openEnvelope(aesKey, text) {
  const envelope = JSON.parse(text);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromB64(envelope.iv) },
    aesKey,
    fromB64(envelope.data),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

const kids = new Set();

for (const [name, base] of TARGETS) {
  console.log(`\n--- ${name}`);

  const descriptor = await (await fetch(`${base}/api/crypto/public-key`)).json();
  kids.add(descriptor.kid);

  const rsaKey = await crypto.subtle.importKey(
    "spki",
    derFromPem(descriptor.publicKeyPem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
  const aesKey = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
    "encrypt",
    "decrypt",
  ]);
  const wrapped = await crypto.subtle.encrypt(
    { name: "RSA-OAEP" },
    rsaKey,
    await crypto.subtle.exportKey("raw", aesKey),
  );

  const headers = {
    Accept: "application/json",
    Authorization: `Bearer ${TOKEN}`,
    "X-Encrypted": "v1",
    "X-Encrypt-Kid": descriptor.kid,
    "X-Encrypt-Key": b64(wrapped),
  };

  // A GET has no body to encrypt, but its reply still must come back sealed.
  const read = await fetch(`${base}/api/admin/apis`, { headers });
  check("accepts a key wrapped by WebCrypto", read.ok, `HTTP ${read.status}`);
  check("marks the reply encrypted", read.headers.get("x-encrypted") === "v1");
  const apis = await openEnvelope(aesKey, await read.text());
  check("WebCrypto decrypts what it sealed", Array.isArray(apis) && apis.length > 0);

  // A POST, sent deliberately invalid: nothing is created, and the validation message is proof the
  // decrypted body was the one the handler parsed.
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    aesKey,
    new TextEncoder().encode(JSON.stringify({ name: "" })),
  );
  const write = await fetch(`${base}/api/admin/partner-groups`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ iv: b64(iv), data: b64(data) }),
  });
  check("parses a body encrypted by WebCrypto", write.status === 400,
    `expected a validation failure, got HTTP ${write.status}`);
  check("encrypts the error reply too", write.headers.get("x-encrypted") === "v1",
    "an error answered in the clear leaks field names and detail");
  const problem = await openEnvelope(aesKey, await write.text());
  check("the error decrypts to a problem document", typeof problem.code === "string",
    JSON.stringify(problem).slice(0, 120));
}

console.log();
check(`both services serve one key (${[...kids].join(", ")})`, kids.size === 1,
  "the portal encrypts to one public key and nginx may route to either service");

console.log(failures ? "\nFAILED" : "\nWebCrypto interoperates with both backends");
process.exit(failures ? 1 : 0);
