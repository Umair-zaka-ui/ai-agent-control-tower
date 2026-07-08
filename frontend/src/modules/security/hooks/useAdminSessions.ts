import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { adminSessionService } from '@/services/authService'
import type { ID } from '@/types'

export const adminSecurityKeys = {
  all: ['security', 'admin'] as const,
  users: () => ['security', 'admin', 'users'] as const,
  sessions: (userId: ID) => ['security', 'admin', 'sessions', userId] as const,
  devices: (userId: ID) => ['security', 'admin', 'devices', userId] as const,
}

/** Organization members, for the admin user picker. */
export function useOrgUsers(enabled: boolean) {
  return useQuery({
    queryKey: adminSecurityKeys.users(),
    queryFn: adminSessionService.listUsers,
    enabled,
  })
}

export function useAdminUserSessions(userId: ID | null) {
  return useQuery({
    queryKey: adminSecurityKeys.sessions(userId ?? ''),
    queryFn: () => adminSessionService.listUserSessions(userId as ID),
    enabled: Boolean(userId),
    refetchOnWindowFocus: true,
  })
}

export function useAdminUserDevices(userId: ID | null) {
  return useQuery({
    queryKey: adminSecurityKeys.devices(userId ?? ''),
    queryFn: () => adminSessionService.listUserDevices(userId as ID),
    enabled: Boolean(userId),
  })
}

export function useAdminRevokeSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, reason }: { sessionId: ID; reason?: string }) =>
      adminSessionService.revokeSession(sessionId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminSecurityKeys.all })
      toast.success('Session revoked. That device is signed out.')
    },
    onError: () => toast.error('Could not revoke the session'),
  })
}

export function useAdminRevokeAllSessions() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, reason }: { userId: ID; reason?: string }) =>
      adminSessionService.revokeAllSessions(userId, reason),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: adminSecurityKeys.all })
      const n = result.revoked_session_ids.length
      toast.success(`Signed out of ${n} ${n === 1 ? 'device' : 'devices'}`)
    },
    onError: () => toast.error('Could not sign the user out'),
  })
}

/** The organization's security-event stream (DoD §32 "…and audit"). */
export function useAdminSecurityEvents(
  params: { actorId?: ID; sessionId?: ID; eventType?: string; limit?: number },
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...adminSecurityKeys.all, 'events', params] as const,
    queryFn: () => adminSessionService.listSecurityEvents(params),
    enabled,
  })
}

/** One session's full history, oldest first. */
export function useSessionEvents(sessionId: ID | null) {
  return useQuery({
    queryKey: [...adminSecurityKeys.all, 'session-events', sessionId ?? ''] as const,
    queryFn: () => adminSessionService.listSessionEvents(sessionId as ID),
    enabled: Boolean(sessionId),
  })
}
