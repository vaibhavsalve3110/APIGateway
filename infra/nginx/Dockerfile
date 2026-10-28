# The TLS terminator, built rather than run straight from nginx:1.29-alpine.
#
# Why build at all: that image is published with whatever Alpine packages its own build picked up,
# and it goes stale between nginx releases. Scanned on 2026-10-28 it carried 28 critical and 103
# high advisories — none in nginx, all in packages Alpine had already fixed: curl, libcurl,
# libcrypto3, libssl3, brotli, tiff, zlib. Pulling the tag again changed nothing, because the tag
# itself is behind. Two lines here clear all of them.
#
# This is the component with the largest exposure in the platform — it terminates TLS for all four
# hostnames and is the only thing a partner or an attacker reaches directly — so it is the one least
# worth leaving on a stale base.
FROM nginx:1.29-alpine

# `upgrade` brings every package to the current Alpine patch level. `del curl` then removes curl and
# libcurl outright: between them they accounted for twenty of those critical advisories, nothing in
# the image depends on them (checked with `apk info -r`), and the health check here is `nginx -t`,
# which needs no HTTP client at all.
RUN apk --no-cache upgrade \
 && apk --no-cache del curl \
 && nginx -t

# The configuration, the certificates and the header snippets all arrive as read-only mounts from
# docker-compose.yml — deliberately, so a routing or header change is a file edit and a restart
# rather than a rebuild. Nothing is copied in here.
EXPOSE 80 443
