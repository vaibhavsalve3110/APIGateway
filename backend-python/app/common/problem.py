"""The error contract.

Every error leaves this service as the same RFC 9457 problem document backend-java produces, because
the portals are shared and read `code`, `detail`, `title` and `fields` (see packages/ui/src/api.ts).
Returning FastAPI's default `{"detail": ...}` would lose the `code` the portals switch on.
"""

from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiException(Exception):
    """A business-rule failure with a stable machine-readable code the portals react to."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields

    @staticmethod
    def not_found(what: str, identifier: Any) -> "ApiException":
        return ApiException(404, "NOT_FOUND", f"{what} {identifier} was not found")

    @staticmethod
    def conflict(code: str, message: str) -> "ApiException":
        return ApiException(409, code, message)

    @staticmethod
    def forbidden(code: str, message: str) -> "ApiException":
        return ApiException(403, code, message)

    @staticmethod
    def bad_request(code: str, message: str) -> "ApiException":
        return ApiException(400, code, message)


def default_code(status: int) -> str:
    return {
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "ENDPOINT_NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
    }.get(status, f"HTTP_{status}")


def problem_response(
    request: Request,
    status: int,
    code: str,
    detail: str,
    fields: dict[str, str] | None = None,
    reference: str | None = None,
) -> JSONResponse:
    """Field order and membership follow what Spring's ProblemDetail serialises."""
    body: dict[str, Any] = {
        "detail": detail,
        "instance": request.url.path,
        "status": status,
        "title": HTTPStatus(status).phrase if status in {s.value for s in HTTPStatus} else "Error",
        "code": code,
    }
    if fields:
        body["fields"] = fields
    if reference:
        body["reference"] = reference
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")
