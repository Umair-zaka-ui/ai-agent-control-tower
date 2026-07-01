import { apiClient } from '@/services/apiClient'
import type { ID } from '@/types'
import type {
  AuditComplianceSummary,
  AuditEventDetail,
  AuditEventListItem,
  AuditEventTypeInfo,
  AuditListParams,
  AuditSecuritySummary,
  AuditStatistics,
  AuditTimelineItem,
} from '../types'

/** Audit & Compliance Center API (Phase 3 Part 3.5). */
export const auditService = {
  async list(params: AuditListParams = {}): Promise<AuditEventListItem[]> {
    const { data } = await apiClient.get<AuditEventListItem[]>('/audit', { params })
    return data
  },

  async get(id: ID): Promise<AuditEventDetail> {
    const { data } = await apiClient.get<AuditEventDetail>(`/audit/${id}`)
    return data
  },

  async statistics(): Promise<AuditStatistics> {
    const { data } = await apiClient.get<AuditStatistics>('/audit/statistics')
    return data
  },

  async timeline(limit = 15): Promise<AuditTimelineItem[]> {
    const { data } = await apiClient.get<AuditTimelineItem[]>('/audit/timeline', {
      params: { limit },
    })
    return data
  },

  async eventTypes(): Promise<AuditEventTypeInfo[]> {
    const { data } = await apiClient.get<AuditEventTypeInfo[]>('/audit/events')
    return data
  },

  async security(): Promise<AuditSecuritySummary> {
    const { data } = await apiClient.get<AuditSecuritySummary>('/audit/security')
    return data
  },

  async compliance(): Promise<AuditComplianceSummary> {
    const { data } = await apiClient.get<AuditComplianceSummary>('/audit/compliance')
    return data
  },

  /** Full filtered event set for export (no pagination cap). Requires audit.export. */
  async export(params: AuditListParams = {}): Promise<AuditEventListItem[]> {
    const { data } = await apiClient.get<AuditEventListItem[]>('/audit/export', { params })
    return data
  },
}
