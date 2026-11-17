# B18: the static web app (web/dist) and the landing page, served by nginx, which also proxies
# /api and /oauth to the api container and sets the TRD 8.7 response headers.
# Build context: the repository root (deploy/compose.yml sets it).

FROM node:24-bookworm-slim AS build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build
# Content-Security-Policy hashes of the landing page's inline script and style (no 'unsafe-inline').
COPY landing/ /src/landing/
COPY deploy/landing-csp.mjs /src/landing-csp.mjs
RUN node /src/landing-csp.mjs /src/landing/index.html > /src/landing-csp.conf

FROM nginx:1.28-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx.conf /etc/nginx/conf.d/matchdesk.conf
COPY --from=build /src/landing-csp.conf /etc/nginx/snippets/landing-csp.conf
COPY --from=build /src/web/dist /srv/app
COPY landing/index.html landing/favicon.svg /srv/landing/
# nginx's master process starts as root to bind; workers run as the image's "nginx" user.
EXPOSE 8080 8081
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
