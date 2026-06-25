import type { ReactNode } from 'react'

import { Logo } from '@/components/common/Logo'

/** Minimal centered layout for error / not-found pages. */
export function ErrorLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background px-4 text-center">
      <Logo />
      {children}
    </div>
  )
}
