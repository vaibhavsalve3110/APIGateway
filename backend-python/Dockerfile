# Multi-stage: build wheels with the toolchain present, run on a slim image without it.
#
# The base is pinned to a Debian release, not to `slim` alone, because the base is where almost all
# of this image's CVE count comes from. Debian 12 (bookworm) accumulated a long tail of advisories
# with no fixed version available — six critical ones in libcurl alone — which no amount of
# dependency pinning touches. Moving to 13 (trixie) clears them, and brings a Python that is itself
# not on an advisory. Re-check this when scanning: a base image goes stale on its own.
FROM python:3.13-slim-trixie AS build
WORKDIR /src

# Dependencies are their own layer, so a source edit does not rebuild every wheel.
#
# From requirements.lock, not from pyproject.toml: the ranges there would resolve differently on
# every build, which makes the image unreproducible and the SBOM in sbom/ a description of some
# earlier build. --require-hashes additionally checks each dist against the sha256 in that file, so
# a substituted or tampered package fails the build. Regenerate with backend-python/tools/relock.sh
# after changing pyproject.toml.
COPY requirements.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.13-slim-trixie
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# No apt install at all. The health check used to need curl, which is not in the slim image — and
# curl plus libcurl4 were between them the largest single source of unfixed critical advisories in
# this image, for a binary used once every fifteen seconds to fetch a local URL. The check below
# does the same thing with the standard library.
RUN useradd --system --uid 10002 apigw

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
# The schema. This service owns the migrations now, so they ship with it rather than with
# backend-java — a deployment without them would start against a database it cannot create.
COPY migrations ./migrations

USER apigw
EXPOSE 8090

# Equivalent to the `curl -fsS` it replaces: urlopen raises on a non-2xx, and anything else that
# goes wrong exits non-zero too. Deliberately *not* asserting "status":"UP" — the endpoint answers
# 200 with DOWN while the database is unreachable, on purpose, so a slow database is reported rather
# than turned into a restart loop.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/actuator/health',timeout=2)"]

# One worker: the service is async and the container is the unit of scaling, so extra worker
# processes here would only multiply database connections.
#
# --no-server-header drops `Server: uvicorn` from every response. nginx already hides an upstream's
# Server header, so this only shows through on the control plane's own port — which is exactly where
# a scanner reaches it, and naming the framework and its version is free reconnaissance.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", \
     "--no-access-log", "--no-server-header"]
