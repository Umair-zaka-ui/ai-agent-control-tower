import { createContext, useMemo, type ReactNode } from 'react'
import { toast } from 'sonner'

/**
 * Thin wrapper over Sonner so components depend on our notification API rather
 * than the toast library directly (keeps the dependency swappable).
 */
export interface NotificationsContextValue {
  success: (message: string, description?: string) => void
  error: (message: string, description?: string) => void
  info: (message: string, description?: string) => void
  warning: (message: string, description?: string) => void
}

// eslint-disable-next-line react-refresh/only-export-components
export const NotificationsContext = createContext<NotificationsContextValue | null>(null)

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const value = useMemo<NotificationsContextValue>(
    () => ({
      success: (message, description) => toast.success(message, { description }),
      error: (message, description) => toast.error(message, { description }),
      info: (message, description) => toast(message, { description }),
      warning: (message, description) => toast.warning(message, { description }),
    }),
    [],
  )

  return (
    <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
  )
}
