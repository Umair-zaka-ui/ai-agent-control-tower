import { Outlet } from 'react-router-dom'

import { Logo } from '@/components/common/Logo'

/**
 * Centered layout for unauthenticated pages (login). The routed auth page is
 * rendered inside the card via <Outlet>.
 */
export function AuthLayout() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm space-y-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo />
          <div className="space-y-1">
            <h1 className="text-xl font-semibold text-foreground">AI Agent Control Tower</h1>
            <p className="text-sm text-muted-foreground">
              Govern, audit, and control autonomous AI agents.
            </p>
          </div>
        </div>

        <Outlet />

        <p className="text-center text-xs text-muted-foreground">
          Phase 3 · Enterprise Dashboard UI · v0.3.0
        </p>
      </div>
    </div>
  )
}
