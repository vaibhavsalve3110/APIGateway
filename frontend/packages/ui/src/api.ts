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

/** Minimal fetch wrapper; the portals' dev servers proxy /api to the backend. */
export function createApiClient(headers: HeaderProvider, baseUrl = ""): ApiClient {
  async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(baseUrl + path, {
      method,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(await headers()),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw await toApiError(response);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }
  return {
    get: (path) => send("GET", path),
    post: (path, body) => send("POST", path, body),
    put: (path, body) => send("PUT", path, body),
    del: (path) => send("DELETE", path),
  };
}
