import { useContext } from 'react'

import {
  NotificationsContext,
  type NotificationsContextValue,
} from '@/contexts/NotificationsContext'

/** Access toast notification helpers (success/error/info/warning). */
export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  if (!ctx) {
    throw new Error('useNotifications must be used within a <NotificationsProvider>')
  }
  return ctx
}
