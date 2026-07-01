import { apiClient } from '@/services/apiClient'
import type { ID } from '@/types'
import type {
  CreateUserInput,
  IdentityDepartment,
  IdentityOrganization,
  IdentityRole,
  IdentityUser,
} from '../types'

/** Enterprise Identity Platform API (Phase 4 Part 4.1), versioned at /api/v1. */
const BASE = '/api/v1/identity'

export const identityService = {
  async listUsers(): Promise<IdentityUser[]> {
    const { data } = await apiClient.get<IdentityUser[]>(`${BASE}/users`)
    return data
  },

  async getUser(id: ID): Promise<IdentityUser> {
    const { data } = await apiClient.get<IdentityUser>(`${BASE}/users/${id}`)
    return data
  },

  async createUser(input: CreateUserInput): Promise<IdentityUser> {
    const { data } = await apiClient.post<IdentityUser>(`${BASE}/users`, input)
    return data
  },

  async setUserActive(id: ID, active: boolean): Promise<IdentityUser> {
    const action = active ? 'activate' : 'suspend'
    const { data } = await apiClient.post<IdentityUser>(`${BASE}/users/${id}/${action}`)
    return data
  },

  async listOrganizations(): Promise<IdentityOrganization[]> {
    const { data } = await apiClient.get<IdentityOrganization[]>(`${BASE}/organizations`)
    return data
  },

  async listDepartments(): Promise<IdentityDepartment[]> {
    const { data } = await apiClient.get<IdentityDepartment[]>(`${BASE}/departments`)
    return data
  },

  async listRoles(): Promise<IdentityRole[]> {
    const { data } = await apiClient.get<IdentityRole[]>(`${BASE}/roles`)
    return data
  },
}
