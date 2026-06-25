import { useNavigate } from 'react-router-dom'
import { LogOut, User as UserIcon } from 'lucide-react'

import {
  Avatar,
  AvatarFallback,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { ROLE_LABELS } from '@/constants/roles'
import { useAuth } from '@/hooks/useAuth'

/** Returns up to two uppercase initials from a name or email. */
function initialsFrom(nameOrEmail: string): string {
  const parts = nameOrEmail.trim().split(/[\s@.]+/).filter(Boolean)
  const letters = parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '')
  return letters.join('') || '?'
}

/** Top-nav account dropdown: identity, profile link and logout. */
export function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const displayName = user?.full_name || user?.email || 'Guest'
  const roleLabel = user ? ROLE_LABELS[user.role] : 'Not signed in'

  const handleLogout = () => {
    logout()
    navigate(ROUTES.LOGIN, { replace: true })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-2 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Avatar>
          <AvatarFallback>{initialsFrom(displayName)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[14rem]">
        <DropdownMenuLabel>
          <div className="flex flex-col">
            <span className="truncate text-sm font-medium">{displayName}</span>
            <span className="text-xs font-normal text-muted-foreground">{roleLabel}</span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate(ROUTES.PROFILE)}>
          <UserIcon />
          Profile
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={handleLogout}>
          <LogOut />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
