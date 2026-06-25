import { NavLink } from 'react-router-dom'

import type { NavItem } from '@/constants/navigation'
import { cn } from '@/utils/cn'

/** A single sidebar link with active-state styling. */
export function SidebarNavItem({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.path}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          isActive
            ? 'bg-primary/15 text-primary'
            : 'text-muted-foreground hover:bg-sidebar-accent hover:text-foreground',
        )
      }
    >
      <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
      <span>{item.label}</span>
    </NavLink>
  )
}
