# Multi-stage: install and compile with the full toolchain, ship production dependencies only.
FROM node:24-bookworm-slim AS build
WORKDIR /src

# Dependencies are their own layer, so a source edit does not reinstall 500 packages.
COPY package.json package-lock.json ./
RUN npm ci

# The Prisma client is generated code; it must exist before tsc runs.
COPY prisma ./prisma
RUN npx prisma generate

COPY tsconfig.json nest-cli.json ./
COPY src ./src
RUN npm run build

# Deliberately no `npm prune --omit=dev`: it deletes node_modules/.prisma along with the dev
# packages, and the client then starts without a query engine ("could not locate the Query Engine
# for runtime debian-openssl-3.0.x"). A larger image beats a service that cannot reach the database.

FROM node:24-bookworm-slim
# OpenSSL is a runtime dependency of Prisma's query engine and is not in the slim image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /src/node_modules ./node_modules
COPY --from=build /src/dist ./dist
COPY --from=build /src/prisma ./prisma
COPY --from=build /src/package.json ./

# node:24 ships an unprivileged 'node' user; the service never needs to write to its own image.
USER node
EXPOSE 8089

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:8089/actuator/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/main.js"]
