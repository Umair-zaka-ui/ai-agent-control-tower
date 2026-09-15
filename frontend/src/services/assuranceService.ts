import { apiClient } from './apiClient'

/**
 * Phase 5.9 — the assurance data layer.
 *
 * Read + trigger over endpoints Phase 5.9 already authorizes. Note what no type
 * here declares: there is no `compliant`, no `status`, no `score` and no
 * coverage percentage, because the API returns none — the contract is the right
 * place to make a compliance badge impossible rather than relying on every view
 * to decline to render one.
 */

const AS = '/api/v1/assurance'

export interface AssuranceEvaluation {
  id: string
  control_id: string
  catalog_version: string
  scope: string
  subject_id: string | null
  /** PASS | FAIL | INSUFFICIENT_EVIDENCE — never a compliance verdict. */
  result: string
  reason: string
  /** What the control read, or the absence it found. */
  evidence: Record<string, unknown>
  evidence_as_of: string | null
  stale: boolean
  remediation: string | null
  exception_reason: string | null
  exception_at: string | null
  evaluated_at: string
}

export interface FrameworkSummary {
  id: string
  name: string
  revision: string
  scope_note: string
  mapped_controls: number
  mapping_version: string
}

export interface FrameworkReport {
  framework: { id: string; name: string; revision: string; scope_note: string }
  mapping_version: string
  catalog_version: string
  generated_at: string
  controls: {
    control_ref: string
    title: string
    rationale: string
    act_control_ids: string[]
    evaluations: AssuranceEvaluation[]
    counts: {
      evaluated: number
      passed: number
      failed: number
      insufficient_evidence: number
      stale: number
    }
    evidence_available: boolean
  }[]
  /** Rendered verbatim, never paraphrased into a UI label. */
  disclaimer: string
}

export interface EvidenceBundle {
  bundle_id: string
  content_digest: string
  signed: boolean
  signature: Record<string, unknown> | null
  signing_key_id: string | null
  /** Says in words whether this bundle is tamper-evident. */
  tamper_evidence: string
  document: Record<string, unknown>
}

export const assuranceService = {
  controls: () => apiClient.get<unknown[]>(`${AS}/controls`).then((r) => r.data),
  frameworks: () => apiClient.get<FrameworkSummary[]>(`${AS}/frameworks`).then((r) => r.data),
  frameworkReport: (id: string) =>
    apiClient.get<FrameworkReport>(`${AS}/frameworks/${id}`).then((r) => r.data),
  evaluations: (params: Record<string, unknown> = {}) =>
    apiClient.get<AssuranceEvaluation[]>(`${AS}/evaluations`, { params }).then((r) => r.data),

  // --- triggers: each dispatches to the endpoint that owns it --- //
  evaluateTenant: () => apiClient.post(`${AS}/evaluate`, {}).then((r) => r.data),
  evaluateAgent: (agentId: string) =>
    apiClient.post(`${AS}/agents/${agentId}/evaluate`, {}).then((r) => r.data),
  recordException: (evaluationId: string, reason: string) =>
    apiClient.post(`${AS}/evaluations/${evaluationId}/exception`, { reason })
      .then((r) => r.data),
  exportBundle: (params: Record<string, unknown> = {}) =>
    apiClient.post<EvidenceBundle>(`${AS}/export`, {}, { params }).then((r) => r.data),
}
