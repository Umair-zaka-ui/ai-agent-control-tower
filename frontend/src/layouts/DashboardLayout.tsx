import { useState } from 'react'
import { Outlet } from 'react-router-dom'

import { AppSidebar } from '@/components/layout/AppSidebar'
import { TopNavbar } from '@/components/layout/TopNavbar'

/**
 * Authenticated app shell (SRS §5): fixed sidebar + sticky top navbar with the
 * routed page rendered into the main content area. Responsive — the sidebar
 * collapses to a drawer below the `lg` breakpoint.
 */
export function DashboardLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <div className="min-h-screen bg-background">
      <AppSidebar open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

      <div className="flex min-h-screen flex-col lg:pl-64">
        <TopNavbar onMenuClick={() => setMobileNavOpen(true)} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
