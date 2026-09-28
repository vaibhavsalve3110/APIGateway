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

COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/packages ./packages
COPY frontend/apps ./apps
RUN npm ci

# Portals call the control plane through nginx on the same origin, so no API base URL is baked in:
# the bundle works behind any hostname the stack is reached by.
RUN npm run build -w "$APP"

FROM nginx:1.29-alpine
ARG APP
COPY --from=build /src/apps/${APP}/dist /usr/share/nginx/html
COPY infra/nginx/portal.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
