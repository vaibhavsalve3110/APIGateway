import type { ApiDocumentation, ApiField } from "./types";

export function emptyDocumentation(): ApiDocumentation {
  return {
    source: "MANUAL",
    queryParameters: [],
    requestHeaders: [],
    requestBodyFields: [],
    requestBodyExample: null,
    responseHeaders: [],
    responses: [],
  };
}

export function emptyField(): ApiField {
  return { name: "", type: "string", required: false, example: null, description: null };
}

/** Pretty-prints JSON; returns the text unchanged when it is not JSON. */
export function prettyJson(text: string | null | undefined): string {
  if (!text) {
    return "";
  }
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export function isValidJson(text: string | null | undefined): boolean {
  if (!text || !text.trim()) {
    return true;
  }
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

function typeOf(value: unknown): string {
  if (Array.isArray(value)) return "array";
  if (value === null) return "string";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (typeof value === "object") return "object";
  return typeof value; // string | boolean
}

/** Field table derived from an example payload (same rules as the backend importer). */
export function inferFields(exampleJson: string | null | undefined, maxDepth = 5): ApiField[] {
  if (!exampleJson || !exampleJson.trim()) {
    return [];
  }
  let root: unknown;
  try {
    root = JSON.parse(exampleJson);
  } catch {
    return [];
  }
  const out: ApiField[] = [];
  const visit = (node: unknown, prefix: string, depth: number) => {
    if (depth > maxDepth || node === null || typeof node !== "object" || Array.isArray(node)) {
      return;
    }
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      const name = prefix ? `${prefix}.${key}` : key;
      const scalar = value === null || typeof value !== "object";
      out.push({ name, type: typeOf(value), required: false, example: scalar && value !== null ? String(value) : null, description: null });
      if (Array.isArray(value)) {
        if (value.length > 0 && typeof value[0] === "object" && value[0] !== null) {
          visit(value[0], `${name}[]`, depth + 1);
        }
      } else if (!scalar) {
        visit(value, name, depth + 1);
      }
    }
  };
  visit(Array.isArray(root) ? root[0] : root, "", 0);
  return out;
}

/** Keeps descriptions / required flags already written for fields that still exist after re-inferring. */
export function mergeFields(existing: ApiField[], inferred: ApiField[]): ApiField[] {
  const byName = new Map(existing.map((f) => [f.name, f]));
  return inferred.map((f) => {
    const old = byName.get(f.name);
    return old ? { ...f, required: old.required, description: old.description, type: old.type || f.type } : f;
  });
}

/** Names of the {param} segments in a proxy path, in order. */
export function pathParams(path: string): string[] {
  return [...path.matchAll(/\{([A-Za-z0-9_\-.]+)}/g)].map((m) => m[1]!);
}

/** Replaces {param} segments with encoded values; missing values keep the placeholder. */
export function fillPath(path: string, values: Record<string, string>): string {
  return path.replace(/\{([A-Za-z0-9_\-.]+)}/g, (whole, name: string) => {
    const v = values[name];
    return v ? encodeURIComponent(v) : whole;
  });
}

export const COMMON_STATUS_CODES: { code: number; label: string }[] = [
  { code: 200, label: "OK" },
  { code: 201, label: "Created" },
  { code: 202, label: "Accepted" },
  { code: 204, label: "No Content" },
  { code: 400, label: "Bad Request" },
  { code: 401, label: "Unauthorized" },
  { code: 403, label: "Forbidden" },
  { code: 404, label: "Not Found" },
  { code: 409, label: "Conflict" },
  { code: 422, label: "Unprocessable" },
  { code: 429, label: "Too Many Requests" },
  { code: 500, label: "Server Error" },
  { code: 503, label: "Unavailable" },
];

export function statusTone(code: number): "ok" | "info" | "warn" | "bad" {
  if (code < 300) return "ok";
  if (code < 400) return "info";
  if (code < 500) return "warn";
  return "bad";
}
