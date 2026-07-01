import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

import { PageHeader } from '@/components/common/PageHeader'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/utils/cn'
import { canViewExecutive, canViewOperations } from '../utils/permissions'

interface Tab {
  label: string
  to: string
  end?: boolean
  show?: (perms: string[]) => boolean
}

const TABS: Tab[] = [
  { label: 'Overview', to: ROUTES.ANALYTICS, end: true },
  { label: 'Executive', to: `${ROUTES.ANALYTICS}/executive`, show: canViewExecutive },
  { label: 'Operations', to: `${ROUTES.ANALYTICS}/operations`, show: canViewOperations },
  { label: 'Risk', to: `${ROUTES.ANALYTICS}/risk` },
  { label: 'Performance', to: `${ROUTES.ANALYTICS}/performance` },
  { label: 'Agents', to: `${ROUTES.ANALYTICS}/agents` },
  { label: 'Policies', to: `${ROUTES.ANALYTICS}/policies` },
  { label: 'Costs', to: `${ROUTES.ANALYTICS}/costs` },
  { label: 'Reports', to: `${ROUTES.ANALYTICS}/reports` },
]

interface AnalyticsLayoutProps {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}

/** Shared analytics shell: page header + section tab nav (SRS §AnalyticsLayout). */
export function AnalyticsLayout({ title, description, actions, children }: AnalyticsLayoutProps) {
  const { permissions } = useAuth()
  const tabs = TABS.filter((t) => !t.show || t.show(permissions))

  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} actions={actions} />

      <nav className="-mb-px flex flex-wrap gap-1 border-b border-border" aria-label="Analytics sections">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                'border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      {children}
    </div>
  )
}
