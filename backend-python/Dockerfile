# Multi-stage: build wheels with the toolchain present, run on a slim image without it.
FROM python:3.12-slim-bookworm AS build
WORKDIR /src

# Dependencies are their own layer, so a source edit does not rebuild every wheel.
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir .

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

USER apigw
EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8090/actuator/health || exit 1

# One worker: the service is async and the container is the unit of scaling, so extra worker
# processes here would only multiply database connections.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
