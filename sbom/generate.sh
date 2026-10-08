#!/usr/bin/env bash
# Regenerates every CycloneDX document in this folder.
#
#   ./generate.sh
#
# Needs Docker and the images built — it describes what exists locally, so run it after a rebuild or
# it documents a build nobody is running:
#
#   docker compose --profile app build
#
# Nothing is installed: Syft runs from its own image.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

# File cataloguing off: with it on each document carries an entry per file and runs to ~24,000
# "components", of which ~23,000 are files rather than packages.
SYFT_ENV=(-e SYFT_FILE_METADATA_SELECTION=none)
SYFT_IMAGE="anchore/syft:latest"

# Git Bash rewrites container paths that look like Unix paths; this leaves them alone.
export MSYS_NO_PATHCONV=1

scan_image() {  # scan_image <image> <output name>
  printf '  %-24s ' "$2"
  if docker run --rm "${SYFT_ENV[@]}" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$here:/out" \
      "$SYFT_IMAGE" "$1" -o "cyclonedx-json=/out/$2.cdx.json" -q >/dev/null 2>&1; then
    echo "ok"
  else
    echo "FAILED — is the image built?"
  fi
}

echo "Images this project builds"
scan_image apigw-backend-python:latest   backend-python
scan_image apigw-backend-java:latest     backend-java
scan_image apigw-management-portal:latest management-portal
scan_image apigw-developer-portal:latest developer-portal

echo "Third-party images the stack runs"
scan_image nginx:1.29-alpine             runtime-nginx
scan_image apache/apisix:3.18.0-debian   runtime-apisix
scan_image quay.io/coreos/etcd:v3.5.33   runtime-etcd
scan_image valkey/valkey:8.1-alpine      runtime-valkey
scan_image postgres:17-alpine            runtime-postgres

echo "Sources"
# The portal images hold a compiled bundle, not node_modules, so the npm tree is only in the
# lockfile. Twice: once as it ships, once including the build-time packages.
printf '  %-24s ' "frontend-npm"
docker run --rm "${SYFT_ENV[@]}" -v "$root/frontend:/src:ro" -v "$here:/out" \
  "$SYFT_IMAGE" file:/src/package-lock.json \
  -o cyclonedx-json=/out/frontend-npm.cdx.json -q >/dev/null 2>&1 && echo "ok" || echo "FAILED"

printf '  %-24s ' "frontend-npm-with-dev"
docker run --rm "${SYFT_ENV[@]}" -e SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true \
  -v "$root/frontend:/src:ro" -v "$here:/out" \
  "$SYFT_IMAGE" file:/src/package-lock.json \
  -o cyclonedx-json=/out/frontend-npm-with-dev.cdx.json -q >/dev/null 2>&1 && echo "ok" || echo "FAILED"

printf '  %-24s ' "source"
docker run --rm "${SYFT_ENV[@]}" -v "$root:/src:ro" -v "$here:/out" \
  "$SYFT_IMAGE" dir:/src -o cyclonedx-json=/out/source.cdx.json -q \
  --exclude './**/node_modules' --exclude './**/.venv' --exclude './**/target' \
  --exclude './sbom' >/dev/null 2>&1 && echo "ok" || echo "FAILED"

echo
echo "Component counts:"
for f in "$here"/*.cdx.json; do
  count=$(grep -o '"bom-ref"' "$f" | wc -l)
  printf '  %-34s %s\n' "$(basename "$f")" "$count"
done
