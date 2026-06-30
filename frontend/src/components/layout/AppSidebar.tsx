import { X } from 'lucide-react'

import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { PRIMARY_NAV } from '@/constants/navigation'
import { cn } from '@/utils/cn'
import { SidebarNavGroup } from './SidebarNavGroup'
import { SidebarNavItem } from './SidebarNavItem'

interface AppSidebarProps {
  /** Mobile drawer open state. */
  open: boolean
  onClose: () => void
}

/**
 * Primary navigation sidebar (SRS §8). Fixed on desktop, slide-over drawer on
 * mobile/tablet.
 */
export function AppSidebar({ open, onClose }: AppSidebarProps) {
  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={cn(
          'fixed inset-0 z-30 bg-background/80 backdrop-blur-sm transition-opacity lg:hidden',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={onClose}
        aria-hidden
      />

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-sidebar-border bg-sidebar transition-transform duration-200 lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center justify-between px-4">
          <Logo />
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={onClose}
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {PRIMARY_NAV.map((item) =>
            item.children ? (
              <SidebarNavGroup key={item.path} item={item} onNavigate={onClose} />
            ) : (
              <SidebarNavItem key={item.path} item={item} onNavigate={onClose} />
            ),
          )}
        </nav>

        <div className="border-t border-sidebar-border p-4">
          <p className="text-[11px] text-muted-foreground">AI Agent Control Tower</p>
          <p className="text-[11px] text-muted-foreground/70">Phase 3 · Part 3.5 · v0.3.0</p>
        </div>
      </aside>
    </>
  )
}
