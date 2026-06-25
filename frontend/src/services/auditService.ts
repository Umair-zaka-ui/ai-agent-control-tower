import type { AuditLog, ID } from '@/types'
import { apiClient } from './apiClient'

/** Audit log API (Phase 1/2 /audit-logs). */
export const auditService = {
  async list(): Promise<AuditLog[]> {
    const { data } = await apiClient.get<AuditLog[]>('/audit-logs')
    return data
  },

  async listForEntity(entityType: string, entityId: ID): Promise<AuditLog[]> {
    const { data } = await apiClient.get<AuditLog[]>(
      `/audit-logs/entity/${entityType}/${entityId}`,
    )
    return data
  },
}
