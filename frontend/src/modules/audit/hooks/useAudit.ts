import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { ID } from '@/types'
import { auditService } from '../services/auditService'
import type { AuditListParams } from '../types'
import { auditKeys } from './auditKeys'

/** Filterable, server-paginated audit event table. */
export function useAudit(params: AuditListParams = {}) {
  return useQuery({
    queryKey: auditKeys.list(params),
    queryFn: () => auditService.list(params),
    placeholderData: keepPreviousData,
  })
}

/** A single audit event's full forensic detail. */
export function useAuditEvent(id: ID | undefined) {
  return useQuery({
    queryKey: auditKeys.detail(id ?? ''),
    queryFn: () => auditService.get(id as ID),
    enabled: Boolean(id),
  })
}

/** Headline statistics for the audit dashboard cards. */
export function useAuditStatistics() {
  return useQuery({
    queryKey: auditKeys.statistics,
    queryFn: auditService.statistics,
    staleTime: 30_000,
  })
}

/** Recent-activity timeline (newest first). */
export function useAuditTimeline(limit = 15) {
  return useQuery({
    queryKey: auditKeys.timeline(limit),
    queryFn: () => auditService.timeline(limit),
    staleTime: 15_000,
  })
}

/** The supported event-type catalog (filter dropdowns / reference). */
export function useAuditEventTypes() {
  return useQuery({
    queryKey: auditKeys.eventTypes,
    queryFn: auditService.eventTypes,
    staleTime: Infinity,
  })
}

/** Security-focused aggregation. Requires `audit.export`. */
export function useSecurityEvents() {
  return useQuery({
    queryKey: auditKeys.security,
    queryFn: auditService.security,
    staleTime: 30_000,
  })
}

/** Informational compliance posture. Requires `audit.export`. */
export function useComplianceSummary() {
  return useQuery({
    queryKey: auditKeys.compliance,
    queryFn: auditService.compliance,
    staleTime: 60_000,
  })
}
