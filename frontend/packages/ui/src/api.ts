import * as payloadCrypto from "./payloadCrypto";

/** Error returned by the platform API as an RFC 9457 problem document with a stable `code`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string>;

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export type HeaderProvider = () => Promise<Record<string, string>> | Record<string, string>;

export interface ApiClient {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  put<T>(path: string, body?: unknown): Promise<T>;
  del(path: string): Promise<void>;
}

/** Turns a failed response into an ApiError, whatever shape its body has. */
export async function toApiError(response: Response): Promise<ApiError> {
  let problem: { code?: string; detail?: string; title?: string; fields?: Record<string, string> } = {};
  try {
    problem = await response.json();
  } catch {
    // not JSON — fall through to the status text
  }
  const fallback =
    response.status === 401 ? "Your session has expired — sign in again"
      : response.status === 403 ? "You do not have access to this"
        : response.statusText || "Request failed";
  return new ApiError(
    response.status,
    problem.code ?? `HTTP_${response.status}`,
    problem.detail ?? problem.title ?? fallback,
    problem.fields ?? {},
  );
}

/** So the insecure-context warning is said once, not on every call the page makes. */
let insecureWarningShown = false;

/** Turns a failed response into an ApiError from a body that has already been read. */
function toApiErrorFrom(status: number, statusText: string, text: string): ApiError {
  let problem: { code?: string; detail?: string; title?: string; fields?: Record<string, string> } = {};
  try {
    problem = JSON.parse(text);
  } catch {
    // not JSON — fall through to the status text
  }
  const fallback =
    status === 401 ? "Your session has expired — sign in again"
      : status === 403 ? "You do not have access to this"
        : statusText || "Request failed";
  return new ApiError(
    status,
    problem.code ?? `HTTP_${status}`,
    problem.detail ?? problem.title ?? fallback,
    problem.fields ?? {},
  );
}

/**
 * Minimal fetch wrapper; the portals' dev servers proxy /api to the backend.
 *
 * Every request and reply is encrypted (see payloadCrypto.ts), which is why the body is read as text
 * and parsed here rather than with `response.json()`: it may be an envelope that has to be opened
 * first. Error bodies included — the backends encrypt those too, so a validation failure's `fields`
 * does not travel in the clear.
 *
 * Query strings are not encrypted, by decision: it would mean turning every filtered GET into a POST.
 * Nothing sensitive belongs in one.
 */
export function createApiClient(headers: HeaderProvider, baseUrl = ""): ApiClient {
  async function send<T>(method: string, path: string, body?: unknown, retrying = false): Promise<T> {
    let extra: Record<string, string> = {};
    let payload: string | undefined;
    let key: CryptoKey | undefined;

    if (payloadCrypto.isAvailable()) {
      const sealed = await payloadCrypto.seal(baseUrl, body);
      extra = sealed.headers;
      payload = sealed.body;
      key = sealed.key;
    } else {
      // crypto.subtle exists only in a secure context. Sending in the clear is refused outright by a
      // production backend, so say why here rather than letting it fail as an opaque 400.
      if (!insecureWarningShown) {
        insecureWarningShown = true;
        console.warn(
          "Payload encryption is unavailable because this page is not in a secure context. " +
            "Open the portal over https (or on localhost). A production backend will refuse these requests.",
        );
      }
      extra = body === undefined ? {} : { "Content-Type": "application/json" };
      payload = body === undefined ? undefined : JSON.stringify(body);
    }

    const response = await fetch(baseUrl + path, {
      method,
      headers: { Accept: "application/json", ...extra, ...(await headers()) },
      body: payload,
    });

    const raw = response.status === 204 ? "" : await response.text();
    let text = raw;
    if (key && raw && response.headers.get("X-Encrypted")) {
      text = await payloadCrypto.open(key, raw);
    }

    if (!response.ok) {
      const error = toApiErrorFrom(response.status, response.statusText, text);
      // The portal was loaded before the platform's key changed, so it is still encrypting to the old
      // one. Fetch the current key and try once; a second failure is a real error.
      if (error.code === "ENCRYPTION_KEY_INVALID" && !retrying) {
        payloadCrypto.forgetKey();
        return send<T>(method, path, body, true);
      }
      throw error;
    }
    if (!text) {
      return undefined as T;
    }
    return JSON.parse(text) as T;
  }
  return {
    get: (path) => send("GET", path),
    post: (path, body) => send("POST", path, body),
    put: (path, body) => send("PUT", path, body),
    del: (path) => send("DELETE", path),
  };
}
