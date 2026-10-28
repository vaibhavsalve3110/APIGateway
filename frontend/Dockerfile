# Builds one portal and serves the static bundle from nginx.
#
# The build context is the REPOSITORY ROOT, not frontend/: the apps are npm workspaces that share
# packages/ui, and the nginx config for the SPA fallback lives under infra/.
#
#   docker build -f frontend/Dockerfile --build-arg APP=management-portal .
ARG APP=management-portal

FROM node:24-bookworm-slim AS build
ARG APP
WORKDIR /src

# tsconfig.base.json is not optional: every app and package extends it, and without it tsc silently
# loses "jsx": "react-jsx" and fails on the shared .tsx components with TS6142.
COPY frontend/package.json frontend/package-lock.json frontend/tsconfig.base.json ./
COPY frontend/packages ./packages
COPY frontend/apps ./apps
RUN npm ci

# Portals call the control plane through nginx on the same origin, so no API base URL is baked in:
# the bundle works behind any hostname the stack is reached by.
RUN npm run build -w "$APP"

FROM nginx:1.29-alpine
ARG APP

# The published nginx alpine image ships whatever Alpine packages its own build picked up, and the
# tag goes stale between nginx releases: scanned on 2026-10-28 it carried 28 critical and 103 high
# advisories, none of them in nginx itself and all of them already fixed upstream. `upgrade` clears
# them; `del curl` removes curl and libcurl, which accounted for twenty of the criticals and which
# nothing in this image — serving static files on port 80 behind the stack's own nginx — has any use
# for. See infra/nginx/Dockerfile, which does the same for the TLS terminator.
RUN apk --no-cache upgrade \
 && apk --no-cache del curl \
 && nginx -t

COPY --from=build /src/apps/${APP}/dist /usr/share/nginx/html
COPY infra/nginx/portal.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
