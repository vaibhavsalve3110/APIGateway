# Software Bill of Materials

CycloneDX 1.7 documents for everything this platform ships and runs, generated with
[Syft](https://github.com/anchore/syft). Regenerate them with `./generate.sh`.

Every file is `*.cdx.json` — valid CycloneDX JSON, which is what a scanner, a licence review or an
auditor expects to be handed. Nothing here is written by hand.

## What each file covers

| File | Subject | Why it exists |
| --- | --- | --- |
| `backend-python.cdx.json` | the `apigw-backend-python` image | The FastAPI control plane as deployed: Python packages **and** the Debian base |
| `backend-java.cdx.json` | the `apigw-backend-java` image | The Spring Boot control plane: the jar's Maven dependencies **and** the Debian base |
| `management-portal.cdx.json` | the `apigw-management-portal` image | What actually ships to a browser — an nginx image with a built bundle, so Alpine packages only |
| `developer-portal.cdx.json` | the `apigw-developer-portal` image | The same for the partner portal |
| `frontend-npm.cdx.json` | `frontend/package-lock.json` | The npm packages that reach production. **Not in any image**: the portal images contain the compiled bundle, not `node_modules` |
| `frontend-npm-with-dev.cdx.json` | the same lockfile | The full tree including build-time dependencies — 104 packages against 17. Use this one for supply-chain review, the other for "what runs" |
| `runtime-nginx.cdx.json` | `nginx:1.29-alpine` | The TLS terminator and router |
| `runtime-apisix.cdx.json` | `apache/apisix:3.18.0-debian` | Both gateways run this image |
| `runtime-etcd.cdx.json` | `quay.io/coreos/etcd:v3.5.33` | Gateway configuration store |
| `runtime-valkey.cdx.json` | `valkey/valkey:8.1-alpine` | Rate-limit counters |
| `runtime-postgres.cdx.json` | `postgres:17-alpine` | The bundled database image. Not normally running — the platform uses the host's PostgreSQL — but included because it ships with the stack |
| `source.cdx.json` | the repository | Declared dependencies from `pom.xml`, `package.json` and `pyproject.toml`, without resolving them |

## Things worth knowing before using these

**The portal images contain no npm packages.** They are nginx serving a compiled bundle. Reviewing
only the image SBOMs would miss React, the router and everything else the portals are built from —
that is what `frontend-npm*.cdx.json` is for.

**Two npm views, deliberately.** Syft excludes dev dependencies by default, which is right for "what
runs in production" (17 packages) and wrong for "what could compromise a build" (104). Both are here;
pick by the question being asked.

**File cataloguing is off.** With it on, Syft emits an entry per file and these documents run to
24,000 "components" of which 23,000 are files. The counts here are packages.

**Keycloak is not in this list.** It runs in the local stack but nothing connects to it — see the
container document. If it stays, add it; if it goes, nothing here changes.

**These describe images that exist locally.** Regenerate after a rebuild, or the SBOM describes a
build nobody is running.

## Next step this does not do

An SBOM lists what is present; it says nothing about what is vulnerable. These documents are the
input to that, not the answer. Grype reads them directly:

```bash
docker run --rm -v "$PWD/sbom:/sbom" anchore/grype:latest sbom:/sbom/backend-python.cdx.json
```

That belongs on a schedule rather than in a one-off run, because the documents stop changing while
the vulnerability feed does not.
