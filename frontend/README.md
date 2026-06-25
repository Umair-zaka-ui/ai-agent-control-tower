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
> `AuthContext`, protected routes, the sidebar + top navbar, and logout. Feature
> pages remain placeholders until Phase 3 Part 3.

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
```

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
