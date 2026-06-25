# Frontend Coding Standards

These standards are enforced for the AI Agent Control Tower dashboard (Phase 3).
They implement SRS §5, §6 and §10.

## TypeScript

- **Strict mode, no `any`.** The project uses strict TypeScript. If a type is
  truly unknown, use `unknown` and narrow it — never `any`.
- Type-only imports use `import type { … }` (the build runs with
  `verbatimModuleSyntax`).
- Public domain types live in `src/types/` and are imported via the `@/types`
  barrel.

## Architecture (component-driven)

UI is composed from small, reusable components. **Never** build a page out of
inline markup.

```
Page  →  Layout  →  Section components  →  UI primitives
```

- **`pages/`** — route entry points. They compose components and call hooks.
  Pages contain no business logic and **never** import `axios`.
- **`layouts/`** — structural shells (dashboard shell, auth shell, error shell).
- **`components/ui/`** — shadcn/ui primitives (Button, Card, Input, …).
- **`components/common/`** — shared building blocks (PageHeader, EmptyState, …).
- **`components/<domain>/`** — feature components (dashboard, charts, navigation).

## Data & business logic

- **All HTTP calls live in `src/services/`** on top of the shared Axios client
  (`httpClient`). Components and pages never call `axios` directly.
- **Server state** is accessed through TanStack Query hooks in `src/hooks/`.
- **Client/shared state** lives in React Context (`src/contexts/`) and is
  consumed through a typed hook (e.g. `useAuth`, `useTheme`).
- Form state uses React Hook Form; validation uses Zod schemas in
  `src/utils/validation.ts`.

## Imports

- Use the `@/…` path alias for all intra-`src` imports (no `../../..`).
- Prefer barrel imports (`@/components/ui`, `@/services`, `@/hooks`).

## Styling

- TailwindCSS only. Use the **semantic theme tokens** (`bg-background`,
  `text-foreground`, `bg-card`, `text-primary`, `text-destructive`, …) rather
  than raw color values, so the design language stays consistent (SRS §7).
- Spacing follows the **8px grid** (Tailwind's default scale: `2 = 8px`,
  `4 = 16px`, `6 = 24px`, `8 = 32px`, `12 = 48px`, `16 = 64px`).
- Compose conditional classes with the `cn()` helper (`@/utils/cn`).
- Dark, enterprise theme. No gradients, no Material Design, minimal animation.

## Naming

- Components: `PascalCase` files and exports (`StatCard.tsx`).
- Hooks: `useThing.ts`, camelCase.
- Constants: `UPPER_SNAKE_CASE` values, grouped objects with `as const`.

## Don't repeat yourself

- Extract shared markup into a component (see `ComingSoon`, `EmptyState`).
- Extract shared logic into a hook or a `utils/` function.

## Commits

Conventional commits, one per completed feature:

```
feat(ui): dashboard layout
feat(auth): login page
fix(ui): responsive sidebar
docs: update README
```

## Quality gate

Before committing a feature:

```bash
npm run lint     # oxlint — no errors
npm run build    # tsc -b + vite build — must pass
```
