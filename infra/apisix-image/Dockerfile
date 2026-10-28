# The two gateways, built rather than run straight from apache/apisix:3.18.0-debian.
#
# Same reason as infra/nginx/Dockerfile: the published image carries Debian packages that Debian has
# already fixed. Scanned on 2026-10-28 it had ten critical advisories, and the ones with a fix
# available were all in openssl/libssl3 and perl-base — the TLS library the data plane links against
# and the interpreter in the base image. This layer takes the published patch level, nothing more:
# **the APISIX version is unchanged**, because moving it is a platform decision with configuration
# consequences, while patching its base is not.
#
# A long tail of advisories without a fixed version remains. Clearing those means a newer APISIX on
# a newer base, which is the open item in docs/operations/production.md.
FROM apache/apisix:3.18.0-debian

# Root only to patch, then straight back to the image's own user — otherwise the gateways would run
# as root, which would be a worse finding than the ones this fixes.
USER root
RUN apt-get update -qq \
 && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
USER apisix
