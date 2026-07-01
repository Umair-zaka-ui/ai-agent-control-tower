import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ID } from '@/types'
import { identityService } from '../services/identityService'
import type { CreateUserInput } from '../types'

export const identityKeys = {
  all: ['identity'] as const,
  users: ['identity', 'users'] as const,
  organizations: ['identity', 'organizations'] as const,
  departments: ['identity', 'departments'] as const,
  roles: ['identity', 'roles'] as const,
}

export function useIdentityUsers() {
  return useQuery({
    queryKey: identityKeys.users,
    queryFn: identityService.listUsers,
    placeholderData: keepPreviousData,
  })
}

export function useIdentityOrganizations() {
  return useQuery({
    queryKey: identityKeys.organizations,
    queryFn: identityService.listOrganizations,
  })
}

export function useIdentityDepartments() {
  return useQuery({
    queryKey: identityKeys.departments,
    queryFn: identityService.listDepartments,
  })
}

export function useIdentityRoles() {
  return useQuery({
    queryKey: identityKeys.roles,
    queryFn: identityService.listRoles,
    staleTime: 60_000,
  })
}

export function useSetUserActive() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, active }: { id: ID; active: boolean }) =>
      identityService.setUserActive(id, active),
    onSuccess: () => qc.invalidateQueries({ queryKey: identityKeys.users }),
  })
}

export function useCreateIdentityUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateUserInput) => identityService.createUser(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: identityKeys.users }),
  })
}
