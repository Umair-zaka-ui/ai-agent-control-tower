import type {
  BusinessUnit,
  Delegation,
  Department,
  HierarchyNode,
  ID,
  OrganizationEntity,
  Project,
  ResourceOwnership,
  Team,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Enterprise organization hierarchy API (Phase 4.3.3, mounted at /api/v1).
 * Reads need `organization.view`; writes need `organization.manage`. Every call is
 * org-scoped server-side (cross-org isolation §9).
 */
export const hierarchyService = {
  // --- Organizations --- //
  async organizations(): Promise<OrganizationEntity[]> {
    const { data } = await apiClient.get<OrganizationEntity[]>('/api/v1/organizations')
    return data
  },

  // --- Business units --- //
  async businessUnits(): Promise<BusinessUnit[]> {
    const { data } = await apiClient.get<BusinessUnit[]>('/api/v1/business-units')
    return data
  },
  async createBusinessUnit(name: string): Promise<BusinessUnit> {
    const { data } = await apiClient.post<BusinessUnit>('/api/v1/business-units', { name })
    return data
  },
  async deleteBusinessUnit(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/business-units/${id}`)
  },

  // --- Departments --- //
  async departments(): Promise<Department[]> {
    const { data } = await apiClient.get<Department[]>('/api/v1/departments')
    return data
  },
  async createDepartment(payload: { name: string; business_unit_id?: ID | null }): Promise<Department> {
    const { data } = await apiClient.post<Department>('/api/v1/departments', payload)
    return data
  },
  async deleteDepartment(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/departments/${id}`)
  },

  // --- Teams --- //
  async teams(): Promise<Team[]> {
    const { data } = await apiClient.get<Team[]>('/api/v1/teams')
    return data
  },
  async createTeam(payload: { name: string; department_id: ID }): Promise<Team> {
    const { data } = await apiClient.post<Team>('/api/v1/teams', payload)
    return data
  },
  async deleteTeam(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/teams/${id}`)
  },

  // --- Projects --- //
  async projects(): Promise<Project[]> {
    const { data } = await apiClient.get<Project[]>('/api/v1/projects')
    return data
  },
  async createProject(payload: { name: string; team_id: ID }): Promise<Project> {
    const { data } = await apiClient.post<Project>('/api/v1/projects', payload)
    return data
  },
  async deleteProject(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/projects/${id}`)
  },

  // --- Tree (§17) --- //
  async tree(): Promise<HierarchyNode> {
    const { data } = await apiClient.get<HierarchyNode>('/api/v1/hierarchy/tree')
    return data
  },

  // --- Resource ownership (§6) --- //
  async assignOwnership(payload: {
    resource_type: string
    resource_id: ID
    project_id?: ID | null
    team_id?: ID | null
    department_id?: ID | null
    owner_id?: ID | null
  }): Promise<ResourceOwnership> {
    const { data } = await apiClient.post<ResourceOwnership>('/api/v1/resource-ownership', payload)
    return data
  },

  // --- Delegation (§10) --- //
  async delegations(): Promise<Delegation[]> {
    const { data } = await apiClient.get<Delegation[]>('/api/v1/delegations')
    return data
  },
  async createDelegation(payload: {
    delegatee_id: ID
    scope_type: string
    scope_id?: ID | null
    permission?: string | null
  }): Promise<Delegation> {
    const { data } = await apiClient.post<Delegation>('/api/v1/delegations', payload)
    return data
  },
  async revokeDelegation(id: ID): Promise<Delegation> {
    const { data } = await apiClient.delete<Delegation>(`/api/v1/delegations/${id}`)
    return data
  },
}
