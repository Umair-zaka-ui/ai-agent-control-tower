import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { sessionService } from '@/services/authService'
import type { ID } from '@/types'

export const securityKeys = {
  all: ['security'] as const,
  sessions: () => ['security', 'sessions'] as const,
  session: (id: ID) => ['security', 'sessions', id] as const,
  devices: () => ['security', 'devices'] as const,
}

/**
 * Active sessions. Refetched on window focus because a session can be revoked
 * from another device — a stale list here would let the user click "revoke" on
 * something that is already gone.
 */
export function useSessions() {
  return useQuery({
    queryKey: securityKeys.sessions(),
    queryFn: sessionService.listSessions,
    refetchOnWindowFocus: true,
    refetchInterval: 60_000,
  })
}

export function useDevices() {
  return useQuery({
    queryKey: securityKeys.devices(),
    queryFn: sessionService.listDevices,
  })
}

export function useRevokeSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: ID; reason?: string }) =>
      sessionService.revokeSession(id, reason),
    onSuccess: () => {
      // Revoking the *current* session invalidates this client's own token; the
      // apiClient 401 handler takes over from there. Refetching is still correct
      // for the ordinary case of revoking another device.
      void queryClient.invalidateQueries({ queryKey: securityKeys.all })
      toast.success('Session revoked')
    },
    onError: () => toast.error('Could not revoke the session'),
  })
}

export function useTrustDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: ID) => sessionService.trustDevice(id),
    onSuccess: (device) => {
      void queryClient.invalidateQueries({ queryKey: securityKeys.all })
      toast.success(`${device.device_name ?? 'Device'} marked as trusted`)
    },
    onError: () => toast.error('Could not trust the device'),
  })
}

export function useBlockDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: ID) => sessionService.blockDevice(id),
    onSuccess: (device) => {
      void queryClient.invalidateQueries({ queryKey: securityKeys.all })
      toast.success(`${device.device_name ?? 'Device'} blocked and signed out`)
    },
    onError: () => toast.error('Could not block the device'),
  })
}

export function useLogoutAllDevices() {
  return useMutation({
    mutationFn: sessionService.logoutAllDevices,
    onError: () => toast.error('Could not sign out of all devices'),
  })
}

/** The caller's own recent security activity (SRS §25). */
export function useMySecurityEvents() {
  return useQuery({
    queryKey: [...securityKeys.all, 'my-events'] as const,
    queryFn: () => sessionService.mySecurityEvents(25),
    refetchOnWindowFocus: true,
  })
}
