# --- AI Agent Control Tower SPA image (build → static nginx) ---
# Stage 1: build the Vite bundle.
FROM node:22-alpine AS build
WORKDIR /app

# Install deps against the lockfile first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Baked in at build time. Empty = same-origin: the SPA calls "/api/..." and nginx
# (below) reverse-proxies it to the api service, so no CORS and no hardcoded host.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# Stage 2: serve the static bundle and proxy the API.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
