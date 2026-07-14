import type {
  ID,
  OwnershipHistoryEntry,
  ProtectedResource,
  ResourceACLEntry,
  ResourceAuthorizeResult,
  ResourceDelegation,
  ResourcePolicyRule,
  ResourceShare,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Resource-based authorization API (Phase 4.3.4, mounted at /api/v1).
 * Owners administer their own resources; `resource.view` / `resource.manage`
 * gate the org-wide admin surface. Every mutation is audited server-side (§23).
 */
export const resourceAuthzService = {
  // --- Registry (§3, §6) --- //
  async resourceTypes(): Promise<string[]> {
    const { data } = await apiClient.get<string[]>('/api/v1/resources/types')
    return data
  },
  async resources(resourceType?: string): Promise<ProtectedResource[]> {
    const { data } = await apiClient.get<ProtectedResource[]>('/api/v1/resources', {
      params: resourceType ? { resource_type: resourceType } : undefined,
    })
    return data
  },
  async resource(id: ID): Promise<ProtectedResource> {
    const { data } = await apiClient.get<ProtectedResource>(`/api/v1/resources/${id}`)
    return data
  },
  async register(payload: {
    resource_type: string
    resource_id?: ID | null
    name?: string | null
    visibility?: string
    owner_id?: ID | null
    owner_type?: string
    project_id?: ID | null
  }): Promise<ProtectedResource> {
    const { data } = await apiClient.post<ProtectedResource>('/api/v1/resources', payload)
    return data
  },
  async update(id: ID, payload: { name?: string; visibility?: string; status?: string }): Promise<ProtectedResource> {
    const { data } = await apiClient.put<ProtectedResource>(`/api/v1/resources/${id}`, payload)
    return data
  },

  // --- Ownership (§6–§8) --- //
  async transferOwnership(id: ID, payload: {
    new_owner_id: ID
    new_owner_type: string
    reason?: string | null
  }): Promise<ProtectedResource> {
    const { data } = await apiClient.post<ProtectedResource>(
      `/api/v1/resources/${id}/transfer-ownership`, payload,
    )
    return data
  },
  async ownershipHistory(id: ID): Promise<OwnershipHistoryEntry[]> {
    const { data } = await apiClient.get<OwnershipHistoryEntry[]>(
      `/api/v1/resources/${id}/ownership-history`,
    )
    return data
  },

  // --- ACL (§10) --- //
  async acl(id: ID): Promise<ResourceACLEntry[]> {
    const { data } = await apiClient.get<ResourceACLEntry[]>(`/api/v1/resources/${id}/acl`)
    return data
  },
  async addAclEntry(id: ID, payload: {
    principal_type: string
    principal_id: ID
    permission: string
    effect: string
    expires_at?: string | null
  }): Promise<ResourceACLEntry> {
    const { data } = await apiClient.post<ResourceACLEntry>(`/api/v1/resources/${id}/acl`, payload)
    return data
  },
  async updateAclEntry(id: ID, aclId: ID, payload: {
    permission?: string
    effect?: string
    expires_at?: string | null
  }): Promise<ResourceACLEntry> {
    const { data } = await apiClient.put<ResourceACLEntry>(
      `/api/v1/resources/${id}/acl/${aclId}`, payload,
    )
    return data
  },
  async deleteAclEntry(id: ID, aclId: ID): Promise<void> {
    await apiClient.delete(`/api/v1/resources/${id}/acl/${aclId}`)
  },

  // --- Sharing (§12) --- //
  async shares(id: ID): Promise<ResourceShare[]> {
    const { data } = await apiClient.get<ResourceShare[]>(`/api/v1/resources/${id}/shares`)
    return data
  },
  async share(id: ID, payload: {
    shared_with_type: string
    shared_with_id: ID
    access_level: string
    expires_at?: string | null
  }): Promise<ResourceShare> {
    const { data } = await apiClient.post<ResourceShare>(`/api/v1/resources/${id}/share`, payload)
    return data
  },
  async updateShare(id: ID, shareId: ID, payload: {
    access_level?: string
    expires_at?: string | null
  }): Promise<ResourceShare> {
    const { data } = await apiClient.put<ResourceShare>(
      `/api/v1/resources/${id}/share/${shareId}`, payload,
    )
    return data
  },
  async revokeShare(id: ID, shareId: ID): Promise<void> {
    await apiClient.delete(`/api/v1/resources/${id}/share/${shareId}`)
  },

  // --- Delegation (§13) --- //
  async delegations(id: ID): Promise<ResourceDelegation[]> {
    const { data } = await apiClient.get<ResourceDelegation[]>(`/api/v1/resources/${id}/delegations`)
    return data
  },
  async delegate(id: ID, payload: {
    delegate_id: ID
    permissions: string[]
    expires_at?: string | null
    reason?: string | null
  }): Promise<ResourceDelegation> {
    const { data } = await apiClient.post<ResourceDelegation>(
      `/api/v1/resources/${id}/delegate`, payload,
    )
    return data
  },
  async revokeDelegation(id: ID, delegationId: ID): Promise<ResourceDelegation> {
    const { data } = await apiClient.delete<ResourceDelegation>(
      `/api/v1/resources/${id}/delegate/${delegationId}`,
    )
    return data
  },

  // --- Policy (§14) --- //
  async setPolicy(id: ID, policy: ResourcePolicyRule[] | null): Promise<ProtectedResource> {
    const { data } = await apiClient.put<ProtectedResource>(`/api/v1/resources/${id}/policy`, { policy })
    return data
  },

  // --- Authorize / inspector (§18, §21) --- //
  async authorize(id: ID, payload: {
    permission: string
    identity_id?: ID | null
  }): Promise<ResourceAuthorizeResult> {
    const { data } = await apiClient.post<ResourceAuthorizeResult>(
      `/api/v1/resources/${id}/authorize`, payload,
    )
    return data
  },
}
