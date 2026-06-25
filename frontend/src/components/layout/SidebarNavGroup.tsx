import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'

import type { NavItem } from '@/constants/navigation'
import { cn } from '@/utils/cn'

/**
 * Expandable sidebar group (e.g. Agents). The group auto-opens when the current
 * route is within it, and reveals its child links.
 */
export function SidebarNavGroup({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { pathname } = useLocation()
  const Icon = item.icon
  const isWithin = pathname === item.path || pathname.startsWith(`${item.path}/`)
  const [open, setOpen] = useState(isWithin)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          'flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          isWithin ? 'text-foreground' : 'text-muted-foreground hover:bg-sidebar-accent hover:text-foreground',
        )}
      >
        <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
        <span className="flex-1 text-left">{item.label}</span>
        <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </button>

      {open ? (
        <ul className="ml-4 mt-1 space-y-1 border-l border-sidebar-border pl-3">
          {item.children?.map((child) => (
            <li key={child.path}>
              <NavLink
                to={child.path}
                end
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    'block rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-primary/15 text-primary'
                      : 'text-muted-foreground hover:bg-sidebar-accent hover:text-foreground',
                  )
                }
              >
                {child.label}
              </NavLink>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
