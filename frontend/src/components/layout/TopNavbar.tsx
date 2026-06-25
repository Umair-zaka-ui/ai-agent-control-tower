import { useLocation } from 'react-router-dom'
import { Bell, Menu, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PRIMARY_NAV } from '@/constants/navigation'
import { ROUTES } from '@/constants/routes'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

interface TopNavbarProps {
  /** Opens the mobile sidebar drawer. */
  onMenuClick: () => void
}

/** Resolve a human page title for the current path. */
function usePageTitle(): string {
  const { pathname } = useLocation()
  const navMatch = PRIMARY_NAV.find((item) => item.path === pathname)
  if (navMatch) return navMatch.label
  if (pathname === ROUTES.PROFILE) return 'Profile'
  return 'AI Agent Control Tower'
}

/**
 * Top navigation bar (SRS §8): page title, search, notifications, theme toggle
 * and the user/profile menu (with logout). Search + notifications are
 * placeholders wired in a later Part.
 */
export function TopNavbar({ onMenuClick }: TopNavbarProps) {
  const pageTitle = usePageTitle()

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onMenuClick}
        aria-label="Open navigation"
      >
        <Menu className="h-5 w-5" />
      </Button>

      <h1 className="shrink-0 text-base font-semibold text-foreground">{pageTitle}</h1>

      {/* Search (placeholder) */}
      <div className="relative ml-2 hidden max-w-sm flex-1 md:block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Search agents, policies, actions…"
          className="pl-9"
          aria-label="Search"
          disabled
        />
      </div>

      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="icon" aria-label="Notifications" className="relative">
          <Bell className="h-5 w-5" />
          <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-primary" />
        </Button>
        <ThemeToggle />
        <div className="mx-1 h-6 w-px bg-border" />
        <UserMenu />
      </div>
    </header>
  )
}
