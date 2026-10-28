"""Gate: the hardening a VAPT report asks about — response headers, the banner, the docs, the lock.

Five things, each of which has been a finding on someone else's report:

* **Security response headers on all four hostnames.** CSP is the one that matters: with
  `script-src 'self'` and no `'unsafe-inline'`, a stored string that reaches the DOM as markup
  cannot execute. The rest (nosniff, frame-ancestors, Referrer-Policy, Permissions-Policy, COOP)
  are cheap and are what scanners enumerate.
* **HSTS is absent or real, never literal.** It is rendered from `$NGINX_HSTS` by envsubst, so the
  failure mode to catch is a header whose value is the unsubstituted `${NGINX_HSTS}` — which looks
  set, and is not. Empty is correct on a developer machine; see snippets/security-headers.conf.
* **No framework banner.** `Server: uvicorn` on the control plane's own port names the framework
  for free. nginx hides an upstream Server header, so this is only visible where a scanner reaches
  the service directly — which is exactly where it matters.
* **The API reference is off under the production profile.** A complete map of every route, with
  parameter names and response shapes, is reconnaissance. Checked by building the app in a
  subprocess under each profile, so this cannot pass by reading the source and believing it.
* **The dependency lockfile is complete and hashed.** Ranges in pyproject.toml mean two builds a
  month apart ship different code, and make the SBOM a description of a build nobody is running.

The header checks need the stack up. The last two do not.

Run:  python tests/check_security_headers.py
"""

import contextlib
import http.client
import json
import re
import ssl
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = "127.0.0.1"
PYTHON_DIRECT = ("127.0.0.1", 18090)

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def through_nginx(host: str, path: str) -> dict[str, str] | None:
    """Headers for a request to one of the four virtual hosts.

    Connects to the loopback address and sets Host by hand rather than resolving the name, so this
    runs without hosts-file entries. The certificate is self-signed, hence the unverified context —
    this gate is about headers, and check_payload_crypto.py is the one that cares about the TLS.
    """
    context = ssl._create_unverified_context()
    try:
        connection = http.client.HTTPSConnection(NGINX, 443, context=context, timeout=15)
        connection.request("GET", path, headers={"Host": host})
        response = connection.getresponse()
        response.read()
        # Header names are case-insensitive on the wire; normalise so a lookup cannot miss.
        return {name.lower(): value for name, value in response.getheaders()}
    except OSError as exc:
        check(f"{host}{path} is reachable", False, str(exc))
        return None
    finally:
        with contextlib.suppress(Exception):
            connection.close()


# --------------------------------------------------------------------------- 1. the shared headers

BASE_EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "x-permitted-cross-domain-policies": "none",
}

print("Shared response headers, per hostname")
for host in ("admin.apigw.com", "developer.apigw.com", "sandbox-api.apigw.com", "api.apigw.com"):
    headers = through_nginx(host, "/")
    if headers is None:
        continue
    for name, expected in BASE_EXPECTED.items():
        check(f"{host} {name}", headers.get(name) == expected, f"got {headers.get(name)!r}")
    check(f"{host} permissions-policy denies hardware",
          "camera=()" in (headers.get("permissions-policy") or ""),
          f"got {headers.get('permissions-policy')!r}")

    # Rendered, not literal. An unsubstituted variable is the one way this can look configured and
    # do nothing at all.
    hsts = headers.get("strict-transport-security")
    if hsts is None:
        check(f"{host} HSTS absent (NGINX_HSTS unset — correct for a self-signed stack)", True)
    else:
        check(f"{host} HSTS is a rendered value", "${" not in hsts and bool(
            re.match(r"^max-age=\d+", hsts.strip())), f"got {hsts!r}")

    # nginx's own version, not just its name.
    check(f"{host} Server header carries no version",
          not re.search(r"\d", headers.get("server") or ""), f"got {headers.get('server')!r}")

# --------------------------------------------------------------------------- 2. Content-Security-Policy

print()
print("Content-Security-Policy")

PORTAL_REQUIRED = [
    # The directive that turns an injected string into inert text. 'unsafe-inline' here would
    # undo the whole policy, so its absence is asserted rather than assumed.
    "script-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    # The CAPTCHA arrives as a data: URI; this is why img-src is not bare 'self'.
    "img-src 'self' data:",
    "connect-src 'self'",
]

for host in ("admin.apigw.com", "developer.apigw.com"):
    headers = through_nginx(host, "/")
    if headers is None:
        continue
    csp = headers.get("content-security-policy") or ""
    for directive in PORTAL_REQUIRED:
        check(f"{host} CSP has {directive}", directive in csp, f"policy is {csp!r}")
    # The exact string matters: "script-src 'self' 'unsafe-inline'" also contains "script-src
    # 'self'", so the check above would pass while the policy was worthless.
    script = re.search(r"script-src ([^;]*)", csp)
    check(f"{host} CSP script-src excludes 'unsafe-inline'",
          script is not None and "unsafe-inline" not in script.group(1),
          f"script-src is {script.group(1) if script else None!r}")

for host in ("sandbox-api.apigw.com", "api.apigw.com"):
    headers = through_nginx(host, "/")
    if headers is None:
        continue
    csp = headers.get("content-security-policy") or ""
    check(f"{host} CSP allows nothing", "default-src 'none'" in csp, f"policy is {csp!r}")

# The documentation page needs a looser policy — jsdelivr and an inline bootstrap script — so it has
# its own, and the point of scoping it to that location is that the portal's stays strict. If this
# policy ever equals the portal's, one of the two is wrong.
docs = through_nginx("admin.apigw.com", "/swagger-ui.html")
portal = through_nginx("admin.apigw.com", "/")
if docs and portal:
    docs_csp = docs.get("content-security-policy") or ""
    check("the docs CSP is its own policy",
          bool(docs_csp) and docs_csp != portal.get("content-security-policy"),
          "the docs location is inheriting the portal policy or has none")
    # Re-including the shared headers inside that location is easy to forget, and nginx drops every
    # inherited add_header as soon as a location declares one of its own.
    for name, expected in BASE_EXPECTED.items():
        check(f"/swagger-ui.html kept {name}", docs.get(name) == expected, f"got {docs.get(name)!r}")

# --------------------------------------------------------------------------- 3. the banner

print()
print("Framework banner on the control plane's own port")
try:
    connection = http.client.HTTPConnection(*PYTHON_DIRECT, timeout=15)
    connection.request("GET", "/actuator/health")
    response = connection.getresponse()
    response.read()
    server = response.getheader("Server")
    check("no Server header on :18090", server is None, f"got {server!r}")
    connection.close()
except OSError as exc:
    check("backend-python answers on :18090", False, str(exc))

# --------------------------------------------------------------------------- 4. the docs, per profile

print()
print("API reference, by profile")

# One process per profile: get_settings() is lru_cached and the routes are decided once, when
# main.py builds the app, so the only honest way to see both answers is to build it twice.
#
# Inside the container, not here: this machine has no virtualenv for the service, and the
# environment that matters is the one that ships. `docker compose exec -e` overrides the profile for
# that one command without touching the running service.
PROBE = (
    "import json;"
    "import app.main as m;"
    "print(json.dumps(sorted(getattr(r, 'path', '') for r in m.app.routes)))"
)

COMPOSE = ["docker", "compose", "-f", str(ROOT.parent / "infra" / "docker-compose.yml"),
           "--profile", "app"]

DOC_PATHS = {"/swagger-ui.html", "/redoc", "/v3/api-docs"}


def routes_under(environment: str, docs_enabled: str = "") -> set[str] | None:
    command = [
        *COMPOSE, "exec", "-T",
        "-e", f"ENVIRONMENT={environment}",
        # Explicit rather than inherited: an operator's DOCS_ENABLED in infra/.env must not decide
        # the answer to this check.
        "-e", f"DOCS_ENABLED={docs_enabled}",
        "backend-python", "python", "-c", PROBE,
    ]
    label = f"ENVIRONMENT={environment}" + (f" DOCS_ENABLED={docs_enabled}" if docs_enabled else "")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        check(f"the app builds under {label}", False, str(exc))
        return None
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()
        check(f"the app builds under {label}", False, tail[-1] if tail else "no output")
        return None
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


demo_routes = routes_under("demo")
if demo_routes is not None:
    # Non-vacuity: if the paths are missing here too, the check below proves nothing.
    check("the reference is served outside production", demo_routes >= DOC_PATHS,
          f"missing {sorted(DOC_PATHS - demo_routes)}")
    check("and the app has its real route table", len(demo_routes) > 60, f"{len(demo_routes)} routes")

production_routes = routes_under("production")
if production_routes is not None:
    leaked = DOC_PATHS & production_routes
    check("the reference is gone under the production profile", not leaked, f"still served: {sorted(leaked)}")
    check("and the rest of the API is untouched", len(production_routes) > 60,
          f"{len(production_routes)} routes")

forced = routes_under("production", docs_enabled="true")
if forced is not None:
    # The override exists for a deployment that keeps this port internal. If it does not work, the
    # setting is decoration and the profile is the only control.
    check("DOCS_ENABLED=true overrides the profile", forced >= DOC_PATHS,
          f"missing {sorted(DOC_PATHS - forced)}")

# --------------------------------------------------------------------------- 5. the lockfile

print()
print("Dependency lockfile")

lock_path = ROOT / "requirements.lock"
if not lock_path.is_file():
    check("requirements.lock exists", False, "run tools/relock.sh")
else:
    lines = [
        line.strip() for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    check("requirements.lock is not empty", bool(lines))

    pinned: dict[str, str] = {}
    malformed = []
    for line in lines:
        match = re.match(r"^([A-Za-z0-9._-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})$", line)
        if match:
            pinned[match.group(1).lower().replace("_", "-")] = match.group(2)
        else:
            malformed.append(line)
    check("every line is pinned and hashed", not malformed, f"{len(malformed)}: {malformed[:2]}")
    check("the lock covers the transitive tree, not just the direct list", len(pinned) > 20,
          f"{len(pinned)} packages")

    # Every name declared in pyproject must appear, or the build installs something the lock does
    # not describe — and with --require-hashes it would not install at all.
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = []
    for spec in declared["project"]["dependencies"]:
        name = re.split(r"[<>=!~\[;\s]", spec, maxsplit=1)[0].strip().lower()
        names.append(name.replace("_", "-"))
    absent = [name for name in names if name not in pinned]
    check("every declared dependency is locked", not absent, f"missing {absent}")

    # And the Dockerfile has to actually use it; a lockfile nothing installs from is a document.
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    check("the Dockerfile installs from the lock with --require-hashes",
          "--require-hashes" in dockerfile and "requirements.lock" in dockerfile)
    check("and no longer resolves ranges at build time",
          not re.search(r"pip install[^\n]*\s\.(\s|$)", dockerfile),
          "a bare `pip install .` would re-resolve pyproject's ranges")

print()
print("FAILED" if failures else "all security hardening checks passed")
sys.exit(1 if failures else 0)
