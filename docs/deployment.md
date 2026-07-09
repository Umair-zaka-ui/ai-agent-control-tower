# Deployment

_Phase 4.2.2.3.5 §24. How the stack is packaged, and the release checklist for a
real environment. This is a personal project, so "production" here means "the shape
an operator would deploy," with each control called out as **provided** or
**operator-supplied**._

## The stack

Three containers, defined in [`docker-compose.yml`](../docker-compose.yml):

| Service | Image | Role |
|---------|-------|------|
| `db` | `postgres:16-alpine` | The only datastore (ADR-0002). Named volume `act_pgdata`. |
| `api` | `./backend` (`python:3.12-slim`) | FastAPI. Runs `alembic upgrade head` on start; optional demo seed. |
| `web` | `./frontend` (build → `nginx:1.27-alpine`) | Serves the SPA and reverse-proxies `/api` to `api` (same origin — no CORS). |

```bash
docker compose up -d --build     # build & run web + api + db
# open http://localhost:8080
```

The SPA is built with `VITE_API_BASE_URL=""` so it calls `/api/...` on its own origin;
nginx forwards that to `api:8000`. Because the API sits behind the proxy, the api
service sets `TRUST_PROXY_HEADERS=true` so rate limiting and risk scoring see the real
client IP via `X-Forwarded-For`, and nginx propagates `X-Request-ID` for correlation.

## Release checklist (§24)

| Item | Status | Notes |
|------|--------|-------|
| Environment variables configured | **provided** | [`backend/.env.example`](../backend/.env.example) documents every setting; compose sets the container ones. |
| Database migrations executed | **provided** | The api entrypoint runs `alembic upgrade head` before serving. |
| SMTP configured | **operator-supplied** | `NOTIFICATIONS_ENABLED=false` by default; set real SMTP to send onboarding/recovery mail. See [email verification](identity/email-verification.md). |
| Secrets stored securely | **operator-supplied** | Rotate `JWT_SECRET_KEY` and the DB password out of compose into your secret store; `.env` is git-ignored and never baked into an image. |
| HTTPS enabled | **operator-supplied** | Terminate TLS at the edge (a load balancer, or an nginx/Caddy/Traefik in front of `web`). Then flip `SECURITY_HSTS_ENABLED=true` so HSTS is emitted. |
| Security headers | **provided** | `SecurityHeadersMiddleware` on every response (§16); see [HTTP conventions](api/http-conventions.md). |
| Rate limiting | **provided** | Postgres-backed, per-IP; `RATE_LIMIT_ENABLED=true` by default. |
| Audit logging | **provided** | Security-event stream + immutable audit logs across the identity surface. |
| Logging enabled | **provided / tune** | Uvicorn logs with correlation ids; raise `--log-level` for production verbosity. |
| Monitoring enabled | **operator-supplied** | `/health` is a liveness probe; wire it to your uptime/metrics system. Prometheus/OTel is a future phase. |
| Backups enabled | **operator-supplied** | Back up the `act_pgdata` volume / managed Postgres on your schedule. |

## Production hardening beyond compose

The bundled compose is a **complete, runnable full stack**, suitable as the template for
a real deployment. For production an operator should additionally:

- Put a TLS-terminating proxy in front of `web` and enable HSTS.
- Move `db` to managed Postgres (or a backed-up volume) and set a strong password.
- Supply secrets via the platform's secret manager, not inline environment values.
- Pin image digests and scan them in CI.
- Configure real SMTP and an alerting/metrics pipeline.

None of these change application code — the app is production-ready from an
architectural standpoint (§27); they are environment concerns owned by the deployer.
