#!/usr/bin/env bash
# Resolve pyproject.toml's dependency ranges into requirements.lock: every package the service
# installs, transitive ones included, pinned to one version and one sha256.
#
#   bash tools/relock.sh
#
# Why a lockfile at all: pyproject declares ranges ("fastapi>=0.118,<0.120"), so two builds a month
# apart ship different code. That makes a build unreproducible, and it makes the SBOM in sbom/ a
# description of one past build rather than of the image you are running. The Dockerfile installs
# from this file with --require-hashes, which also means a tampered or substituted dist fails the
# build instead of shipping.
#
# Resolution happens inside the same base image the Dockerfile uses, because the answer is
# platform-specific: a wheel chosen for linux/amd64 and CPython 3.12 is not the one this machine
# would pick. pip alone does the work — no pip-tools, no uv — via its --report output.
#
# Re-run this after any edit to pyproject.toml's dependencies, and commit the result.
set -euo pipefail

cd "$(dirname "$0")/.."
root=$(pwd)
# Docker Desktop on Windows wants D:/path, not Git Bash's /d/path.
if command -v cygpath >/dev/null 2>&1; then
  root=$(cygpath -m "$root")
fi

image=$(awk -F'[ :]+' '/^FROM python:/ { print $2 ":" $3; exit }' Dockerfile)
echo "Resolving against ${image}"

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "${root}:/src:ro" \
  -v "${root}/tools:/tools:ro" \
  "$image" sh -c '
    set -e
    cd /tmp && cp /src/pyproject.toml .
    pip install --quiet --dry-run --ignore-installed --report /tmp/report.json . >/dev/null
    python /tools/lockfile.py /tmp/report.json
  ' > requirements.lock.new

mv requirements.lock.new requirements.lock
echo "requirements.lock: $(grep -c '^[a-zA-Z0-9]' requirements.lock) packages pinned"
