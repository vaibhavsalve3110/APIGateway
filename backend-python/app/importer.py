"""Reading a Swagger / OpenAPI file or a Postman collection into draft APIs (BRD CP-API-06).

Nothing here writes anything. It turns an uploaded file into a list of operations that pre-fill the
Add API editor, and a person decides which to keep. That is why an unreadable file is a 400 and a
partially readable one is a result with warnings: the editor can show both.

Ported from backend-java's importer, which leaned on `swagger-parser` for `$ref` resolution and for
converting Swagger 2.0 into OpenAPI 3. There is no equivalent single library here, so both are done
in this module. Two deliberate differences from that library, both security decisions:

* **`$ref` is resolved locally only.** A specification saying `$ref: "http://attacker/x.yaml"` is a
  server-side request forgery vector — the platform would fetch a URL of the uploader's choosing,
  from inside the network. Remote references are refused with a warning rather than followed.
* **YAML is parsed with `safe_load`.** The unsafe loader constructs arbitrary Python objects, which
  on an uploaded file is remote code execution.

Reference cycles are handled by depth limits rather than by tracking visited nodes: a specification
that refers to itself produces a finite, shallow sample instead of hanging.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from .common.problem import ApiException

#: Nesting depth for flattening schemas and building examples. Matches MAX_DEPTH in the Java code.
MAX_DEPTH = 5

#: How many times a $ref chain may be followed before it is treated as a cycle.
MAX_REF_DEPTH = 20

SUPPORTED = ("GET", "POST", "PUT", "PATCH", "DELETE")

_POSTMAN_BASE = re.compile(r"^(\{\{[^}]+\}\}|https?://[^/?#]+)")

_REASON = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content", 400: "Bad Request",
    401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict",
    422: "Unprocessable Entity", 429: "Too Many Requests", 500: "Internal Server Error",
    502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
}


# --------------------------------------------------------------------------- shared helpers


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _first_non_blank(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


#: Jackson's DefaultPrettyPrinter puts a space before the colon, and backend-java generated every
#: imported example with it. Matched here so a file imported before and after this port produces
#: byte-identical examples — they are shown in the editor and a diff would look like a change.
_JACKSON = (",", " : ")


def pretty(value: Any) -> str | None:
    """A JSON example as the editor shows it. A string that is already JSON is re-indented."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), indent=2, separators=_JACKSON)
        except (json.JSONDecodeError, TypeError):
            return _truncate(value, 20_000)
    return _truncate(json.dumps(value, indent=2, separators=_JACKSON, default=str), 20_000)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return _truncate(value if isinstance(value, str) else pretty(value), 20_000)


def sanitize_path(path: str | None) -> str:
    """`/v1/payments/:txnId` and `/v1/{{version}}/x` become the `{param}` form the gateway accepts."""
    if not path or not path.strip():
        return "/"
    cleaned = path.strip()
    query = cleaned.find("?")
    if query >= 0:
        cleaned = cleaned[:query]
    cleaned = re.sub(r"\{\{\s*([A-Za-z0-9_\-.]+)\s*\}\}", r"{\1}", cleaned)
    cleaned = re.sub(r"(^|/):([A-Za-z0-9_]+)", r"\1{\2}", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9/_\-{}.]", "", cleaned)
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return re.sub(r"/{2,}", "/", cleaned)


def _status_code(code: Any) -> int | None:
    try:
        status = int(str(code).strip())
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


# --------------------------------------------------------------------------- OpenAPI / Swagger


def _resolve_refs(node: Any, root: dict[str, Any], warnings: list[str], depth: int = 0) -> Any:
    """Replace every local `$ref` with what it points at. Remote references are refused.

    Depth-limited rather than cycle-tracked: a self-referential schema is common and legal, and the
    result only needs to be deep enough to document.
    """
    if depth > MAX_REF_DEPTH:
        return {}
    if isinstance(node, list):
        return [_resolve_refs(item, root, warnings, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        if not ref.startswith("#/"):
            # Following this would make the platform fetch a URL the uploader chose, from inside
            # the network. The operation is still imported, without whatever the reference held.
            warnings.append(f"Remote reference '{ref}' was not followed — only local $ref is resolved")
            return {}
        target: Any = root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                warnings.append(f"Reference '{ref}' could not be resolved")
                return {}
            target = target[part]
        resolved = _resolve_refs(target, root, warnings, depth + 1)
        # Anything beside the $ref (a description, say) stays and wins, as OpenAPI 3.1 allows.
        rest = {k: v for k, v in node.items() if k != "$ref"}
        if isinstance(resolved, dict) and rest:
            return {**resolved, **_resolve_refs(rest, root, warnings, depth + 1)}
        return resolved

    return {k: _resolve_refs(v, root, warnings, depth + 1) for k, v in node.items()}


def _raw_type(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    if schema.get("type"):
        kind = schema["type"]
        if isinstance(kind, list):  # OpenAPI 3.1 allows a list of types
            return next((t for t in kind if t != "null"), None)
        return str(kind)
    return "object" if schema.get("properties") else None


def _type_of(schema: dict[str, Any] | None) -> str:
    kind = _raw_type(schema)
    if kind is None:
        return "string"
    fmt = (schema or {}).get("format")
    return f"{kind}({fmt})" if fmt else kind


def _sample(schema: dict[str, Any] | None, depth: int = 0) -> Any:
    """An example value built from a schema, for a file that provides none."""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return None
    if schema.get("example") is not None:
        return schema["example"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = _raw_type(schema)
    if schema.get("properties"):
        return {name: _sample(child, depth + 1) for name, child in schema["properties"].items()}
    if kind == "array":
        item = _sample(schema.get("items"), depth + 1)
        return [] if item is None else [item]
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return True
    if kind == "object":
        return {}
    fmt = schema.get("format")
    if fmt == "date-time":
        return "2026-09-14T08:00:00Z"
    if fmt == "date":
        return "2026-09-14"
    if fmt == "uuid":
        return "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    return "string"


def _flatten(schema: dict[str, Any] | None, prefix: str, out: list[dict[str, Any]], depth: int = 0) -> None:
    """One row per field, with `[]` marking an array and dots marking nesting."""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return
    is_array = _raw_type(schema) == "array" and isinstance(schema.get("items"), dict)
    target = schema["items"] if is_array else schema
    base = prefix if not is_array else ("[]" if not prefix else prefix + "[]")
    properties = target.get("properties") if isinstance(target, dict) else None
    if not isinstance(properties, dict):
        return
    required = target.get("required") if isinstance(target.get("required"), list) else []
    for name, child in properties.items():
        full = name if not base else f"{base}.{name}"
        example = child.get("example") if isinstance(child, dict) else None
        if example is None and isinstance(child, dict) and child.get("enum"):
            example = child["enum"][0]
        out.append({
            "name": _truncate(full, 120),
            "type": _type_of(child),
            "required": name in required,
            "example": _as_text(example),
            "description": _truncate((child or {}).get("description"), 1000),
        })
        if isinstance(child, dict) and (child.get("properties") or _raw_type(child) == "array"):
            _flatten(child, full, out, depth + 1)


def _pick_media(content: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prefer JSON; otherwise whatever the file listed first."""
    if not isinstance(content, dict) or not content:
        return None
    for media_type, media in content.items():
        if "json" in str(media_type).lower():
            return media if isinstance(media, dict) else None
    first = next(iter(content.values()))
    return first if isinstance(first, dict) else None


def _example_of(media: dict[str, Any]) -> str | None:
    if media.get("example") is not None:
        return pretty(media["example"])
    examples = media.get("examples")
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and first.get("value") is not None:
            return pretty(first["value"])
    schema = media.get("schema")
    return pretty(_sample(schema)) if isinstance(schema, dict) else None


def _response_doc(status: int, response: dict[str, Any], swagger2: bool) -> dict[str, Any]:
    media = (
        {"schema": response.get("schema")} if swagger2 and response.get("schema")
        else _pick_media(response.get("content"))
    )
    fields: list[dict[str, Any]] = []
    example = None
    if media:
        example = _example_of(media)
        if isinstance(media.get("schema"), dict):
            _flatten(media["schema"], "", fields)
    description = _first_non_blank(response.get("description")) or _REASON.get(status)
    return {
        "statusCode": status,
        "description": _truncate(description, 500),
        "bodyExample": example,
        "bodyFields": fields,
    }


def _parameters(params: list[Any], swagger2: bool) -> tuple[list[dict], list[dict], dict | None]:
    """Split into query and header fields; Swagger 2 also carries the request body here."""
    query: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    body_schema: dict[str, Any] | None = None
    for parameter in params:
        if not isinstance(parameter, dict):
            continue
        location = parameter.get("in")
        if swagger2 and location == "body":
            if isinstance(parameter.get("schema"), dict):
                body_schema = parameter["schema"]
            continue
        # Swagger 2 puts the type on the parameter; OpenAPI 3 puts it in a schema.
        schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else parameter
        example = parameter.get("example")
        if example is None and isinstance(parameter.get("schema"), dict):
            example = parameter["schema"].get("example")
        field = {
            "name": parameter.get("name"),
            "type": _type_of(schema),
            "required": parameter.get("required") is True,
            "example": _as_text(example),
            "description": parameter.get("description"),
        }
        if location == "query":
            query.append(field)
        elif location == "header":
            headers.append(field)
    return query, headers, body_schema


def _openapi(spec: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    swagger2 = str(spec.get("swagger", "")).startswith("2")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise ApiException.bad_request(
            "UNREADABLE_SPECIFICATION", "The file could not be read as Swagger / OpenAPI"
        )

    operations: list[dict[str, Any]] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") if isinstance(item.get("parameters"), list) else []
        for method, operation in item.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"):
                continue
            if not isinstance(operation, dict):
                continue
            if method.upper() not in SUPPORTED:
                warnings.append(
                    f"{method.upper()} {path} skipped — only GET, POST, PUT, PATCH and DELETE are supported"
                )
                continue
            operations.append(
                _operation(path, method.upper(), shared, operation, swagger2, warnings)
            )

    if swagger2:
        host, base_path = spec.get("host"), spec.get("basePath") or ""
        # swagger-parser leaves this scheme-relative ("//host/api") when the file declares no
        # schemes. Deliberately not matched: the value pre-fills the backend URL field, which only
        # accepts http(s), so Java's version is pre-filled and then rejected by its own form.
        schemes = spec.get("schemes") or ["https"]
        server = f"{schemes[0]}://{host}{base_path}" if host else None
    else:
        servers = spec.get("servers")
        server = servers[0].get("url") if isinstance(servers, list) and servers else None

    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    return {
        "format": "OPENAPI",
        "title": info.get("title"),
        "suggestedBackendBaseUrl": None if server in (None, "/") else server,
        "operations": operations,
        "warnings": warnings,
    }


def _operation(
    path: str, method: str, shared: list[Any], operation: dict[str, Any], swagger2: bool,
    warnings: list[str],
) -> dict[str, Any]:
    own = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
    query, headers, swagger2_body = _parameters([*shared, *own], swagger2)

    body_fields: list[dict[str, Any]] = []
    body_example = None
    if swagger2_body is not None:
        body_example = pretty(_sample(swagger2_body))
        _flatten(swagger2_body, "", body_fields)
    elif isinstance(operation.get("requestBody"), dict):
        media = _pick_media(operation["requestBody"].get("content"))
        if media:
            body_example = _example_of(media)
            if isinstance(media.get("schema"), dict):
                _flatten(media["schema"], "", body_fields)

    responses: list[dict[str, Any]] = []
    response_headers: dict[str, dict[str, Any]] = {}
    for code, response in (operation.get("responses") or {}).items():
        if not isinstance(response, dict):
            continue
        status = _status_code(code)
        if status is None:
            warnings.append(
                f"{method} {path}: response '{code}' skipped — only numeric status codes are kept"
            )
            continue
        responses.append(_response_doc(status, response, swagger2))
        if 200 <= status < 300 and isinstance(response.get("headers"), dict):
            for name, header in response["headers"].items():
                if name in response_headers or not isinstance(header, dict):
                    continue
                response_headers[name] = {
                    "name": name,
                    # Swagger 2 puts the type on the header; OpenAPI 3 wraps it in a schema.
                    "type": _type_of(
                        header["schema"] if isinstance(header.get("schema"), dict) else header
                    ),
                    "required": header.get("required") is True,
                    "example": _as_text(header.get("example")),
                    "description": header.get("description"),
                }

    tags = operation.get("tags")
    name = _first_non_blank(operation.get("summary"), operation.get("operationId"), f"{method} {path}")
    return {
        "name": _truncate(name, 160),
        "category": _truncate(tags[0] if isinstance(tags, list) and tags else "Imported", 60),
        "httpMethod": method,
        "proxyPath": sanitize_path(path),
        "description": _truncate(
            _first_non_blank(operation.get("description"), operation.get("summary")), 2000
        ),
        "documentation": {
            "source": "OPENAPI",
            "queryParameters": query,
            "requestHeaders": headers,
            "requestBodyFields": body_fields,
            "requestBodyExample": body_example,
            "responseHeaders": list(response_headers.values()),
            "responses": responses,
        },
    }


# --------------------------------------------------------------------------- Postman


def _looks_like_postman(root: Any) -> bool:
    if not isinstance(root, dict):
        return False
    info = root.get("info") if isinstance(root.get("info"), dict) else {}
    return (
        "_postman_id" in info
        or "getpostman.com" in str(info.get("schema", ""))
        or ("item" in root and "openapi" not in root and "swagger" not in root)
    )


def _postman_fields(entries: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("disabled") is True:
            continue
        out.append({
            "name": entry.get("key"),
            "type": "string",
            "required": False,
            "example": _as_text(entry.get("value")),
            "description": entry.get("description") if isinstance(entry.get("description"), str) else None,
        })
    return out


def _postman_operation(
    item: dict[str, Any], folder: str, warnings: list[str], base: list[str | None]
) -> dict[str, Any] | None:
    request = item.get("request")
    name = item.get("name") or "Untitled request"
    if isinstance(request, str):
        request = {"method": "GET", "url": request}
    if not isinstance(request, dict):
        return None

    method = str(request.get("method") or "GET").upper()
    if method not in SUPPORTED:
        warnings.append(f"{name} skipped — {method} is not supported")
        return None

    url = request.get("url")
    raw = url if isinstance(url, str) else (url or {}).get("raw", "") if isinstance(url, dict) else ""
    if isinstance(url, dict) and isinstance(url.get("path"), list) and url["path"]:
        segments = [s if isinstance(s, str) else str((s or {}).get("value", "")) for s in url["path"]]
        path = "/" + "/".join(segments)
    else:
        path = _POSTMAN_BASE.sub("", str(raw), count=1)

    if base[0] is None and raw:
        match = _POSTMAN_BASE.match(str(raw))
        if match:
            base[0] = match.group(1)

    query = _postman_fields((url or {}).get("query") if isinstance(url, dict) else None)
    headers = _postman_fields(request.get("header"))

    body_example = None
    body = request.get("body") if isinstance(request.get("body"), dict) else {}
    mode = body.get("mode")
    if mode == "raw":
        body_example = pretty(body.get("raw"))
    elif mode:
        warnings.append(f"{name}: '{mode}' body mode is not imported — document it manually")

    responses: list[dict[str, Any]] = []
    seen: set[int] = set()
    for saved in item.get("response") if isinstance(item.get("response"), list) else []:
        if not isinstance(saved, dict):
            continue
        status = _status_code(saved.get("code"))
        if status is None or status in seen:
            continue
        seen.add(status)
        example = pretty(saved.get("body"))
        responses.append({
            "statusCode": status,
            "description": _truncate(saved.get("name") or _REASON.get(status), 500),
            "bodyExample": example,
            "bodyFields": _fields_from_example(example),
        })

    return {
        "name": _truncate(str(name), 160),
        "category": _truncate(folder, 60),
        "httpMethod": method,
        "proxyPath": sanitize_path(path),
        "description": _truncate(
            request.get("description") if isinstance(request.get("description"), str) else None, 2000
        ),
        "documentation": {
            "source": "POSTMAN",
            "queryParameters": query,
            "requestHeaders": headers,
            "requestBodyFields": _fields_from_example(body_example),
            "requestBodyExample": body_example,
            "responseHeaders": [],
            "responses": responses,
        },
    }


def _fields_from_example(example: str | None) -> list[dict[str, Any]]:
    """Postman has no schema, so the field list is inferred from the example body."""
    if not example:
        return []
    try:
        parsed = json.loads(example)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict[str, Any]] = []
    _collect(parsed, "", out, 0)
    return out


def _collect(node: Any, prefix: str, out: list[dict[str, Any]], depth: int) -> None:
    if not isinstance(node, dict) or depth > MAX_DEPTH:
        return
    for key, value in node.items():
        name = key if not prefix else f"{prefix}.{key}"
        kind = (
            "array" if isinstance(value, list)
            else "object" if isinstance(value, dict)
            else "boolean" if isinstance(value, bool)
            else "integer" if isinstance(value, int)
            else "number" if isinstance(value, float)
            else "string"
        )
        out.append({
            "name": _truncate(name, 120), "type": kind, "required": False,
            "example": None if isinstance(value, (dict, list)) else _as_text(value),
            "description": None,
        })
        if isinstance(value, dict):
            _collect(value, name, out, depth + 1)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            _collect(value[0], f"{name}[]", out, depth + 1)


def _postman(root: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    base: list[str | None] = [None]

    def walk(items: Any, folder: str) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if "item" in item:
                walk(item["item"], str(item.get("name") or folder))
            elif "request" in item:
                operation = _postman_operation(item, folder, warnings, base)
                if operation:
                    operations.append(operation)

    walk(root.get("item"), "Imported")
    info = root.get("info") if isinstance(root.get("info"), dict) else {}
    suggested = base[0]
    if suggested and suggested.startswith("{{"):
        # A collection variable, which is only useful once resolved to its value.
        variables = {
            v.get("key"): v.get("value")
            for v in (root.get("variable") or [])
            if isinstance(v, dict)
        }
        suggested = variables.get(suggested.strip("{}"), suggested)
    return {
        "format": "POSTMAN",
        "title": info.get("name"),
        "suggestedBackendBaseUrl": suggested,
        "operations": operations,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- entry point


def read(content: str | None) -> dict[str, Any]:
    """Parse an uploaded file into operations. Raises a 400 when it cannot be read at all."""
    text = (content or "").strip()
    if not text:
        raise ApiException.bad_request("EMPTY_FILE", "The file is empty")

    warnings: list[str] = []
    try:
        # safe_load, never load: the unsafe loader constructs arbitrary Python objects, which on an
        # uploaded file is remote code execution. It reads JSON too, JSON being a subset of YAML.
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ApiException.bad_request(
            "UNREADABLE_SPECIFICATION",
            f"The file could not be read as Swagger / OpenAPI or a Postman collection: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise ApiException.bad_request(
            "UNREADABLE_SPECIFICATION",
            "The file could not be read as Swagger / OpenAPI or a Postman collection",
        )

    if _looks_like_postman(parsed):
        result = _postman(parsed, warnings)
    else:
        result = _openapi(_resolve_refs(parsed, parsed, warnings), warnings)

    if not result["operations"]:
        raise ApiException.bad_request(
            "NO_OPERATIONS",
            "The file was read, but it contains no GET, POST, PUT, PATCH or DELETE operations",
        )
    return result
