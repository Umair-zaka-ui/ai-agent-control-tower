# AI Agent Control Tower — Frontend (Phase 3)

Enterprise AI governance dashboard. A React + TypeScript single-page app that
consumes the Phase 1 / Phase 2 FastAPI backend so administrators, reviewers,
auditors and operators can manage AI agents visually instead of via Swagger.

> **Phase 3 — Part 1** delivers the project scaffold, tooling, dark enterprise
> theme, base app shell (sidebar + top nav), auth scaffold and the
> service/hook/type layers wired to the backend APIs. Feature pages are
> placeholders that get built out in later Parts.

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
├── assets/          # static assets imported by code
├── components/
│   ├── ui/          # shadcn/ui primitives (Button, Card, Input, …)
│   ├── common/      # shared building blocks (PageHeader, EmptyState, Spinner)
│   ├── navigation/  # Sidebar, TopNav, UserMenu, ThemeToggle
│   ├── dashboard/   # dashboard sections (StatsCards, StatCard)
│   └── charts/      # Recharts wrappers (RiskTrendChart)
├── config/          # env + TanStack Query client
├── constants/       # routes, navigation, roles, query keys
├── contexts/        # Auth, Theme, Notifications providers
├── hooks/           # context + data hooks (useAuth, useAgents, …)
├── layouts/         # DashboardLayout, AuthLayout, ErrorLayout
├── pages/           # route entry points
├── routes/          # route tree + ProtectedRoute / PublicRoute guards
├── services/        # Axios client + one service per backend resource
├── types/           # TypeScript domain types
├── utils/           # cn, formatters, validation, permission helpers
├── App.tsx          # provider stack + router
└── main.tsx         # React entry
```

## Conventions

See [CODING_STANDARDS.md](./CODING_STANDARDS.md). In short: strict TypeScript
(no `any`), component-driven UI, every API call inside `services/`, pages never
import `axios`, semantic Tailwind tokens on an 8px grid.

## Notes

- The production bundle currently ships as a single chunk; route-level code
  splitting is a planned optimization for a later Part.
