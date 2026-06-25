# Phase 3 — Part 1: Enterprise Dashboard UI (Scaffold)

This document records what was delivered in Part 1 against the SRS (v0.3.0).

## Goal

Stand up a modern enterprise SaaS frontend (`frontend/`) that consumes the
existing Phase 1 / Phase 2 FastAPI backend. No backend business logic was
changed.

## Definition of Done — status

| # | Requirement | Status |
| - | ----------- | ------ |
| 1 | React + TypeScript project created | ✅ |
| 2 | Vite configured | ✅ (alias `@/`, dev port 5173) |
| 3 | TailwindCSS configured | ✅ (v3, dark theme tokens) |
| 4 | shadcn/ui installed | ✅ (manual setup; primitives added) |
| 5 | React Router installed | ✅ (v7, route tree + guards) |
| 6 | Axios configured | ✅ (single client + interceptors) |
| 7 | TanStack Query configured | ✅ (shared QueryClient + hooks) |
| 8 | React Hook Form + Zod configured | ✅ (login form + schemas) |
| 9 | Folder structure created | ✅ (per SRS §6) |
| 10 | Dark theme implemented | ✅ (SRS §7 palette as HSL tokens) |
| 11 | Base dashboard layout | ✅ (`DashboardLayout`) |
| 12 | Sidebar placeholder | ✅ (`Sidebar`, responsive drawer) |
| 13 | Top navigation placeholder | ✅ (`TopNav`: search/bell/theme/user) |
| 14 | Authentication layout scaffold | ✅ (`AuthLayout` + `LoginPage`) |
| 15 | Coding standards documented | ✅ (`frontend/CODING_STANDARDS.md`) |
| 16 | Builds successfully | ✅ (`npm run build` + `npm run dev`) |

## Design language (SRS §7)

The palette is implemented as HSL CSS variables in `src/index.css` and mapped to
Tailwind semantic tokens (`bg-background`, `bg-card`, `text-primary`, …):

| Token | Hex | Usage |
| ----- | --- | ----- |
| background | `#0F172A` | app background |
| card | `#1E293B` | surfaces |
| primary | `#2563EB` | actions, active nav |
| success | `#16A34A` | allow / healthy |
| warning | `#EAB308` | pending / medium risk |
| destructive | `#DC2626` | block / high risk |
| foreground | `#F8FAFC` | text |

Typography is Inter (400/500/600/700); spacing follows the 8px grid.

## Architecture

Component-driven, per SRS §5/§6: pages compose layouts and feature components;
all HTTP lives in `services/`; server state via TanStack Query hooks; shared
state via React Context consumed through typed hooks. Strict TypeScript, no
`any`.

## How to run

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (expects backend at :8000)
```
