# AI Agent Control Tower — Frontend (Phase 3)

Enterprise AI governance dashboard. A React + TypeScript single-page app that
consumes the Phase 1 / Phase 2 FastAPI backend so administrators, reviewers,
auditors and operators can manage AI agents visually instead of via Swagger.

> **Phase 3 — Part 1** delivered the project scaffold, tooling, dark enterprise
> theme and the service/hook/type layers.
>
> **Phase 3 — Part 2** delivers the working **authentication system and app
> shell**: JWT login (React Hook Form + Zod) against the backend, token storage,
> an Axios client that attaches the token and redirects to `/login` on 401, an
> `AuthContext`, protected routes, the sidebar + top navbar, and logout.
>
> **Phase 3 — Part 3.1** turns the dashboard into a live **operational control
> center**: six KPI cards, an agent-activity line chart, a 30-day risk-trend
> chart, a pending-approval queue with inline approve/reject, recent agent
> actions, recent audit logs, and a system-health widget — all fed by the
> backend, auto-refreshing every 60 seconds, with skeleton / error / empty
> states throughout.
>
> **Phase 3 — Part 3.2a** adds the **Agent Management module** (`src/modules/agents/`):
> a server-driven agents table (debounced search, status/type/risk filters,
> sortable columns, pagination, CSV/JSON export, row lifecycle actions), a
> five-step **Create Agent wizard** (with one-time API-key reveal), an agent
> **Details** page (Overview + live stats) and an **Edit** form. The backend
> gained agent metadata fields, two new statuses (ARCHIVED/BLOCKED), and
> paginated list / update / delete / stats endpoints. (Activity timeline,
> API-key rotation, permission matrix, policy assignment and bulk actions land
> in Part 3.2b.)

## Tech stack

| Concern        | Choice                                  |
| -------------- | --------------------------------------- |
| Framework      | React 19 + TypeScript (strict)          |
| Build tool     | Vite                                    |
| Styling        | TailwindCSS (dark enterprise theme)     |
| Components     | shadcn/ui (Radix primitives)            |
| Charts         | Recharts                                |
| Server state   | TanStack Query                          |
| Client state   | React Context                           |
| HTTP           | Axios (single configured client)        |
| Routing        | React Router v7                         |
| Forms          | React Hook Form + Zod                   |
| Icons          | Lucide React                            |
| Notifications  | Sonner                                  |
| Animation      | Framer Motion                           |

## Getting started

```bash
cd frontend
npm install
cp .env.example .env     # Windows: copy .env.example .env
npm run dev              # http://localhost:5173
```

The dev server expects the backend at `http://localhost:8000` (configurable via
`VITE_API_BASE_URL` in `.env`). See the backend README to start the API.

## Scripts

```bash
npm run dev       # start the Vite dev server (HMR)
npm run build     # type-check (tsc -b) + production build
npm run preview   # preview the production build
npm run lint      # oxlint
npm test          # run the Vitest unit/component suite
```

## Dashboard (Part 3.1)

The dashboard (`/dashboard`) is fully data-driven. Each widget is a small
component backed by a TanStack Query hook that polls every 60s; a manual
**Refresh** button re-fetches everything without a page reload. Charts
(Recharts) are lazy-loaded so the shell paints fast.

| Widget | Hook | Backend endpoint |
| ------ | ---- | ---------------- |
| KPI cards (6) | `useDashboardSummary` | `GET /dashboard/summary` |
| Agent Activity chart | `useAgentActivity` | `GET /dashboard/activity?days=7` |
| Risk Trend chart | `useRiskTrend` | `GET /dashboard/risk-trend?days=30` |
| Pending Approvals | `usePendingApprovals` / `useApprovalActions` | `GET /dashboard/pending-approvals`, `POST /approvals/{id}/approve\|reject` |
| Recent Agent Actions | `useRecentActions` | `GET /dashboard/recent-actions` |
| Recent Audit Logs | `useRecentAuditLogs` | `GET /audit-logs?limit=` |
| System Health | `useSystemHealth` | `GET /system/health` |

The summary, activity, risk-trend and system-health endpoints were added to the
FastAPI backend in this part; the rest already existed. When the organization
has no agents, the dashboard shows a welcome / "Create Agent" onboarding state.

> Screenshots: capture `/dashboard` once you have seeded demo data and drop them
> in `docs/` — they aren't committed here to keep the repo lean.

## Agent Management module (Part 3.2a)

Lives in `src/modules/agents/` and never mixes into dashboard code. All agent
HTTP is in the module's `agentService`; pages use the module's hooks.

| Page | Route | Backend |
| ---- | ----- | ------- |
| Agents list | `/agents` | `GET /agents` (search, status/type/risk filters, sort, pagination) |
| Create wizard | `/agents/new` | `POST /agents` (returns one-time API key) |
| Agent details | `/agents/:id` | `GET /agents/:id`, `GET /agents/:id/stats` |
| Edit agent | `/agents/:id/edit` | `PUT /agents/:id` |
| Lifecycle (suspend/activate/archive) | — | `PATCH /agents/:id/status` |
| Delete | — | `DELETE /agents/:id` |

Search debounces at 300ms; the table sorts and paginates server-side; export
produces CSV/JSON from the loaded rows. The sidebar's **Agents** entry is an
expandable group (All Agents / Create Agent).

## Project structure

```
src/
├── components/
│   ├── ui/          # shadcn/ui primitives (Button, Card, Input, …)
│   ├── common/      # shared building blocks (PageHeader, EmptyState, Spinner)
│   ├── layout/      # AppSidebar, TopNavbar, ProtectedRoute, PublicRoute, UserMenu
│   ├── dashboard/   # dashboard sections (StatsCards, StatCard)
│   └── charts/      # Recharts wrappers (RiskTrendChart)
├── config/          # env + TanStack Query client
├── constants/       # routes, navigation, roles, query keys
├── contexts/        # Auth, Theme, Notifications providers
├── hooks/           # context + data hooks (useAuth, useAgents, …)
├── layouts/         # DashboardLayout, AuthLayout, ErrorLayout
├── modules/         # self-contained feature modules
│   └── agents/      #   components / pages / hooks / services / types / utils / tests
├── pages/           # route entry points (auth/LoginPage, DashboardPage, …)
├── routes/          # AppRoutes route tree
├── services/        # apiClient + one service per backend resource
├── types/           # TypeScript domain types
├── utils/           # tokenStorage, cn, formatters, validation, permissions
├── App.tsx          # provider stack + router
└── main.tsx         # React entry
```

## Authentication flow (Part 2)

1. `/login` collects credentials, validated with Zod, and calls
   `authService.login()` → `POST /auth/login`.
2. The JWT is saved via `utils/tokenStorage` and `apiClient` attaches it as a
   `Bearer` token on every request.
3. On app load, `AuthContext` bootstraps from the stored token by calling
   `GET /auth/me`; an invalid token is discarded.
4. `ProtectedRoute` redirects unauthenticated users to `/login`; `PublicRoute`
   keeps authenticated users out of `/login`.
5. A `401` from the API clears the token and redirects to `/login`.
6. Logout clears the token and returns to `/login`.

## Conventions

See [CODING_STANDARDS.md](./CODING_STANDARDS.md). In short: strict TypeScript
(no `any`), component-driven UI, every API call inside `services/`, pages never
import `axios`, semantic Tailwind tokens on an 8px grid.

## Notes

- The production bundle currently ships as a single chunk; route-level code
  splitting is a planned optimization for a later Part.
