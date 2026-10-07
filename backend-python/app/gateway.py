"""APISIX Admin API payloads and the client that pushes them.

The payload builders are pure functions, so the gateway contract is testable without a gateway. That
matters more here than anywhere else in the port: APISIX accepts almost any JSON it is given, so
wrong configuration is not rejected — it is applied, and the gateway then quietly misroutes, stops
rate-limiting, or stops checking keys. Nothing fails loudly.
"""

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .common.problem import ApiException
from .settings import Settings, get_settings

log = logging.getLogger(__name__)

#: Header partners send their security key in (see the Developer Portal documentation).
KEY_HEADER = "X-Security-Key"

SHORT_CODE = {"SANDBOX": "sbx", "PRODUCTION": "prd"}
RATE_WINDOW_SECONDS = {"MINUTE": 60, "HOUR": 3_600, "DAY": 86_400}

#: Runs before key-auth: replaces the presented key with its SHA-256 hex digest, so the gateway only
#: ever compares hashes and never stores a usable key (BRD v1.3, CP-SEC-09). Byte-identical to the
#: Java constant — a difference here changes what the gateway computes, not just how it reads.
HASH_PRESENTED_KEY = """return function(conf, ctx)
  local core = require("apisix.core")
  local key = core.request.header(ctx, "%s")
  if key and #key > 0 then
    local sha256 = require("resty.sha256")
    local str = require("resty.string")
    local digest = sha256:new()
    digest:update(key)
    core.request.set_header(ctx, "%s", str.to_hex(digest:final()))
  end
end
""" % (KEY_HEADER, KEY_HEADER)  # noqa: UP031 - mirrors the Java formatted() call exactly

PATH_PARAM = re.compile(r"\{([A-Za-z0-9_\-.]+)\}")


def route_id(api_id: str, environment: str) -> str:
    return f"api-{api_id}-{SHORT_CODE[environment]}"


def gateway_uri(proxy_path: str) -> str:
    """APISIX's router matches path parameters as `:name`; proxy paths use OpenAPI's `{name}`."""
    return PATH_PARAM.sub(lambda m: ":" + m.group(1).replace("-", "_").replace(".", "_"), proxy_path)


def rewrite(proxy_path: str, backend_path: str | None) -> dict[str, Any] | None:
    """How the partner-facing path maps onto the backend path.

    A static backend path is used as-is; one carrying `{params}` is filled from the matching
    parameters of the proxy path with a regex rewrite; an empty backend path forwards unchanged.
    """
    if not backend_path or backend_path == "/":
        return None
    proxy_params = [m.group(1) for m in PATH_PARAM.finditer(proxy_path)]
    if not proxy_params or not PATH_PARAM.search(backend_path):
        return {"uri": backend_path}

    # The dot escaping happens before the parameters are substituted, as it does on the Java side.
    regex = "^" + PATH_PARAM.sub("([^/]+)", proxy_path.replace(".", r"\.")) + "$"

    def to_group(match: re.Match[str]) -> str:
        try:
            return f"${proxy_params.index(match.group(1)) + 1}"
        except ValueError:
            return match.group(0)

    return {"regex_uri": [regex, PATH_PARAM.sub(to_group, backend_path)]}


def backend_parts(url: str) -> tuple[str, str, int, str]:
    """scheme, host, port and path of a backend URL, defaulting the port the way URI.getPort does."""
    parsed = urlparse(url)
    scheme = parsed.scheme
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, parsed.hostname or "", port, parsed.path or ""


def route(api: dict[str, Any], environment: str, settings: Settings) -> dict[str, Any]:
    backend_url = (
        api["backendUrlProduction"] if environment == "PRODUCTION" else api["backendUrlSandbox"]
    )
    scheme, host, port, path = backend_parts(backend_url)
    target_hosts = (
        settings.gateway_production_hosts if environment == "PRODUCTION"
        else settings.gateway_sandbox_hosts
    )

    plugins: dict[str, Any] = {
        "serverless-pre-function": {"phase": "rewrite", "functions": [HASH_PRESENTED_KEY]},
        "key-auth": {"header": KEY_HEADER, "hide_credentials": True},
        # Counted per consumer, and each consumer is one Client ID — so a partner's overlapping keys
        # share one limit rather than doubling it during a rotation.
        "limit-count": {
            "count": api["rateLimitCount"],
            "time_window": RATE_WINDOW_SECONDS[api["rateLimitWindow"]],
            "key_type": "var",
            "key": "consumer_name",
            "policy": "redis",
            "redis_host": settings.gateway_redis_host,
            "redis_port": settings.gateway_redis_port,
            "rejected_code": 429,
            "show_limit_quota_header": True,
        },
    }
    path_rewrite = rewrite(api["proxyPath"], path)
    if path_rewrite is not None:
        plugins["proxy-rewrite"] = path_rewrite

    result: dict[str, Any] = {
        "name": f"{api['name']} ({environment.lower()})",
        "uri": gateway_uri(api["proxyPath"]),
        "methods": [api["httpMethod"]],
    }
    if target_hosts:
        result["hosts"] = target_hosts
    result["upstream"] = {
        "type": "roundrobin",
        "scheme": scheme,
        "pass_host": "node",
        "nodes": {f"{host}:{port}": 1},
    }
    result["plugins"] = plugins
    result["labels"] = {"api_id": str(api["id"]), "env": SHORT_CODE[environment]}
    return result


def consumer(client_id: str, partner_code: str, partner_name: str) -> dict[str, Any]:
    return {"username": client_id, "desc": partner_name, "labels": {"partner": partner_code}}


def credential(key_hash: str) -> dict[str, Any]:
    return {"plugins": {"key-auth": {"key": key_hash}}}


class GatewayClient:
    """Pushes configuration to both APISIX deployments.

    Disabled (`GATEWAY_SYNC_ENABLED=false`) it does nothing and says so, which is what lets the
    service run on a developer machine with no gateway. Everything else raises, because an API that
    looks saved but was never published to the gateway is worse than a failed save.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _target(self, environment: str) -> tuple[str, str]:
        if environment == "PRODUCTION":
            return self.settings.apisix_production_admin_url, self.settings.apisix_production_admin_key
        return self.settings.apisix_sandbox_admin_url, self.settings.apisix_sandbox_admin_key

    async def _request(self, method: str, environment: str, path: str, body: Any = None) -> None:
        if not self.settings.gateway_sync_enabled:
            log.debug("Gateway sync disabled; skipping %s %s on %s", method, path, environment)
            return
        base, key = self._target(environment)
        url = f"{base}/apisix/admin{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method, url, headers={"X-API-KEY": key}, json=body
                )
            # Deleting is idempotent: a route already gone is the state we wanted.
            if method == "DELETE" and response.status_code == 404:
                return
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiException(
                503,
                "GATEWAY_UNAVAILABLE",
                f"The {environment.lower()} gateway did not accept the change: {exc}",
            ) from exc

    async def sync_api(self, api: dict[str, Any]) -> None:
        """Publish or withdraw this API on both gateways, by its current status and backend URLs."""
        for environment in ("SANDBOX", "PRODUCTION"):
            backend = (
                api["backendUrlProduction"] if environment == "PRODUCTION"
                else api["backendUrlSandbox"]
            )
            path = f"/routes/{route_id(api['id'], environment)}"
            if api["status"] == "ACTIVE" and backend and backend.strip():
                await self._request("PUT", environment, path, route(api, environment, self.settings))
            else:
                # Not active, or no backend for this environment: the route must not exist.
                await self._request("DELETE", environment, path)

    async def remove_api(self, api_id: str) -> None:
        for environment in ("SANDBOX", "PRODUCTION"):
            await self._request("DELETE", environment, f"/routes/{route_id(api_id, environment)}")

    async def ensure_consumer(
        self, environment: str, client_id: str, partner_code: str, partner_name: str
    ) -> None:
        await self._request(
            "PUT", environment, "/consumers", consumer(client_id, partner_code, partner_name)
        )

    async def put_credential(
        self, environment: str, client_id: str, credential_id: str, key_hash: str
    ) -> None:
        await self._request(
            "PUT",
            environment,
            f"/consumers/{client_id}/credentials/{credential_id}",
            credential(key_hash),
        )

    async def delete_credential(
        self, environment: str, client_id: str, credential_id: str
    ) -> None:
        await self._request(
            "DELETE", environment, f"/consumers/{client_id}/credentials/{credential_id}"
        )
