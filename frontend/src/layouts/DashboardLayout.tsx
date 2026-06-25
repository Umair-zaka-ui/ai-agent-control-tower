import { useState } from 'react'
import { Outlet } from 'react-router-dom'

import { Sidebar } from '@/components/navigation/Sidebar'
import { TopNav } from '@/components/navigation/TopNav'

/**
 * Authenticated app shell (SRS §5): fixed sidebar + sticky top nav with the
 * routed page rendered into the main content area.
 */
export function DashboardLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <div className="min-h-screen bg-background">
      <Sidebar open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

      <div className="flex min-h-screen flex-col lg:pl-64">
        <TopNav onMenuClick={() => setMobileNavOpen(true)} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
