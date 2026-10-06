"""FastAPI control plane.

Runs against the same PostgreSQL schema and the same signing secret as backend-java, so the two can
serve the portals side by side while routes move across one at a time.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .common import errors
from .common.problem import ApiException, default_code, problem_response
from .routers import catalogue, usage
from .settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s : %(message)s")
log = logging.getLogger("apigw")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("Connecting to PostgreSQL (schema %s)", settings.db_schema)
    if not await db.ping():
        # Not fatal: the health endpoint reports DOWN and the orchestrator can restart us, which is
        # kinder than crash-looping while the database comes up.
        log.error("Database is not reachable at startup")
    else:
        log.info("Connected to PostgreSQL")
    yield
    await db.dispose()


app = FastAPI(
    title="API Gateway platform (Python)",
    description="FastAPI control plane. Serves the same contract as backend-java against the same database.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/swagger-ui.html",
    openapi_url="/v3/api-docs",
)

app.include_router(catalogue.router)
app.include_router(usage.router)


def _actor(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    return getattr(principal, "username", None)


@app.exception_handler(ApiException)
async def _api_exception(request: Request, exc: ApiException) -> JSONResponse:
    reference = None
    # A 4xx is the API working as designed (a duplicate name, a revoked key); only a 5xx is our fault.
    if exc.status >= 500:
        reference = await errors.record(
            errors.API,
            exc.code,
            exc.message,
            actor=_actor(request),
            request=f"{request.method} {request.url.path}",
            client_ip=request.client.host if request.client else None,
        )
    return problem_response(request, exc.status, exc.code, exc.message, exc.fields, reference)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten pydantic's output into the {field: message} map the portals render beside inputs."""
    fields: dict[str, str] = {}
    for error in exc.errors():
        # loc is ('query', 'limit') or ('body', 'name'); the field name is what the portal knows.
        location = [str(part) for part in error.get("loc", []) if part not in ("body", "query", "path")]
        name = ".".join(location) or "request"
        fields.setdefault(name, error.get("msg", "is invalid"))
    return problem_response(request, 400, "VALIDATION_FAILED", "Some fields are invalid", fields)


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return problem_response(request, exc.status_code, default_code(exc.status_code), detail)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Anything not handled above is a defect: record it with its traceback and give a reference."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    reference = await errors.record(
        errors.API,
        "INTERNAL_ERROR",
        str(exc) or exc.__class__.__name__,
        detail=repr(exc),
        actor=_actor(request),
        request=f"{request.method} {request.url.path}",
        client_ip=request.client.host if request.client else None,
    )
    return problem_response(
        request,
        500,
        "INTERNAL_ERROR",
        "Something went wrong on our side. Quote the reference to your administrator.",
        reference=reference,
    )


@app.get("/actuator/health", tags=["health"])
async def health() -> dict[str, object]:
    """Same path and shape as Spring Actuator's, so every probe is indifferent to which service answers."""
    up = await db.ping()
    return {"status": "UP" if up else "DOWN", "components": {"db": {"status": "UP" if up else "DOWN"}}}
