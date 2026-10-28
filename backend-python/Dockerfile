# Multi-stage: build wheels with the toolchain present, run on a slim image without it.
FROM python:3.12-slim-bookworm AS build
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

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is not in the slim image and the compose health check needs it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10002 apigw

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
# The schema. This service owns the migrations now, so they ship with it rather than with
# backend-java — a deployment without them would start against a database it cannot create.
COPY migrations ./migrations

USER apigw
EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8090/actuator/health || exit 1

# One worker: the service is async and the container is the unit of scaling, so extra worker
# processes here would only multiply database connections.
#
# --no-server-header drops `Server: uvicorn` from every response. nginx already hides an upstream's
# Server header, so this only shows through on the control plane's own port — which is exactly where
# a scanner reaches it, and naming the framework and its version is free reconnaissance.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", \
     "--no-access-log", "--no-server-header"]
