import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { queryClient } from '@/config/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { NotificationsProvider } from '@/contexts/NotificationsContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { AppRoutes } from '@/routes/AppRoutes'

/**
 * Application root. Composes the provider stack (data, theme, notifications,
 * routing, auth, tooltips) around the route tree.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotificationsProvider>
          <BrowserRouter>
            <AuthProvider>
              <TooltipProvider delayDuration={200}>
                <AppRoutes />
                <Toaster />
              </TooltipProvider>
            </AuthProvider>
          </BrowserRouter>
        </NotificationsProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
