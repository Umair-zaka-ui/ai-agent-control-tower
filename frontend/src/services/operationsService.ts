import type { ID } from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/runtime'

/**
 * Phase 3.10 — the Release Operations Center's data layer.
 *
 * **Read + trigger, nothing else.** Every mutating call below hits an endpoint
 * that Phases 3.1–3.9 already built, and that already enforces authorization,
 * tenant isolation, idempotency, audit and the safety rules (kill-switch
 * dominance, fail-closed targets, gate verdicts). Nothing here implements a
 * deployment decision; a `rollback()` here *calls* 3.7's rollback, it does not
 * perform one.
 *
 * That matters for a reason beyond tidiness: the browser is not a trust
 * boundary. Anything this file could decide, a user could decide differently
 * with the developer console open. So it decides nothing — the four read
 * endpoints shape data for screens, and every other method is a thin call to a
 * server operation that re-authorizes it.
 */

// --------------------------------------------------------------------------- //
// Read-model shapes (the four Phase 3.10 aggregation endpoints)
// --------------------------------------------------------------------------- //
export interface VersionIdentity {
  id: ID
  semantic_version: string
  status: string
  checksum: string | null
  checksum_algorithm: string | null
  signature_id: string | null
  signed_at: string | null
  manifest_digest: string | null
  /** Collapsed from the three columns above so a screen never has to do forensics. */
  signature_state: 'SIGNED' | 'UNSIGNED'
  rollback_target_id: ID | null
}

export interface ReleaseHealth {
  health_state: string
  /**
   * False for UNKNOWN / INSUFFICIENT_DATA. Handed over by the server rather
   * than inferred here: "we do not know" must never render as "fine", and a
   * client-side string check is one refactor away from getting that wrong.
   */
  is_proving: boolean
  sample_count: number
  metrics: Record<string, unknown>
  evaluated_at: string | null
}

export interface ActiveRollout {
  id: ID
  kind: 'CANARY' | 'ROLLING'
  state: string
  current_stage_index: number
  state_reason: string | null
}

export interface OverviewRow {
  deployment_id: ID
  agent_id: ID
  agent_name: string | null
  agent_lifecycle_status: string | null
  /** The kill switch, as a first-class fact rather than a lifecycle string to parse. */
  kill_switch_active: boolean
  environment_id: ID | null
  environment_name: string | null
  is_production: boolean
  version: VersionIdentity | null
  deployment_strategy: string
  status: string
  lifecycle_state: string
  revision: number
  state_reason: string | null
  /** Phase 3.4's union-with-veto predicate, reported by the server. */
  servable: boolean
  traffic_weight: number | null
  health_status: string | null
  release_health: ReleaseHealth | null
  gate_verdict: 'PASS' | 'WARNING' | 'BLOCK' | null
  gate_evaluated_at: string | null
  active_rollout: ActiveRollout | null
  deployed_at: string | null
  updated_at: string | null
}

export interface EnvironmentSummary {
  id: ID
  name: string
  display_name: string
  is_production: boolean
}

export interface OperationsOverview {
  deployments: OverviewRow[]
  environments: EnvironmentSummary[]
  summary: {
    total: number
    serving: number
    kill_switched: number
    blocked: number
    rolling_out: number
  }
}

export interface TimelineEntry {
  id: ID
  kind: 'LIFECYCLE' | 'ROLLBACK'
  event_type: string
  from_state: string | null
  to_state: string | null
  reason: string | null
  actor_id: ID | null
  trigger?: string
  occurred_at: string | null
  deployment_id?: ID
  agent_id?: ID
  agent_name?: string | null
  environment_name?: string | null
}

export interface GateFinding {
  code: string
  severity: 'PASS' | 'WARNING' | 'BLOCK' | string
  message?: string
  remediation?: string
  [key: string]: unknown
}

export interface DeploymentDetail {
  deployment_id: ID
  agent: { id: ID; name: string | null; lifecycle_status: string | null }
  kill_switch_active: boolean
  version: VersionIdentity | null
  rollback_target: VersionIdentity | null
  environment: { id: ID | null; name: string | null; is_production: boolean }
  deployment_strategy: string
  status: string
  lifecycle_state: string
  revision: number
  state_reason: string | null
  servable: boolean
  health_status: string | null
  release_health: ReleaseHealth | null
  gate: { verdict: string; findings: GateFinding[]; evaluated_at: string | null } | null
  allocation: {
    revision: number
    weights: { agent_version_id: ID; semantic_version: string | null; weight: number }[]
    updated_at: string | null
  } | null
  rollout: (ActiveRollout & {
    cohort_plan: Record<string, unknown> | null
    stages: RolloutStage[]
  }) | null
  approvals: {
    id: ID; status: string; requested_action: string
    reviewed_by: ID | null; decision_comment: string | null; created_at: string | null
  }[]
  initiated_by: ID | null
  deployed_at: string | null
  retired_at: string | null
  updated_at: string | null
  duration_seconds: number | null
  timeline: TimelineEntry[]
}

export interface RolloutStage {
  stage_index: number
  target_weight: number
  min_duration_seconds: number
  min_samples: number
  health_requirement: string
  advance_mode: string
  entered_at: string | null
  id?: ID
}

export interface RolloutSummary {
  id: ID
  kind: 'CANARY' | 'ROLLING'
  state: string
  current_stage_index: number
  state_reason: string | null
  agent_id: ID
  agent_name: string | null
  environment_id: ID
  environment_name: string | null
  candidate_version: string | null
  stable_version: string | null
  stage_count: number
  is_live: boolean
  created_at: string | null
  updated_at: string | null
}

export interface RolloutPlanDetail {
  id: ID
  kind?: 'CANARY' | 'ROLLING'
  agent_id: ID
  environment_id: ID
  candidate_version_id: ID
  stable_version_id: ID | null
  state: string
  current_stage_index: number
  state_reason: string | null
  revision: number
  cohort_plan?: Record<string, unknown> | null
  stages: RolloutStage[]
  gate_evaluation?: Record<string, unknown> | null
}

export interface TrafficWeightEntry {
  agent_version_id: ID
  weight: number
}

export interface TrafficAllocation {
  id?: ID
  revision: number
  weights: TrafficWeightEntry[]
  reason?: string | null
  created_at?: string | null
  is_current?: boolean
}

export interface FleetWorker {
  worker_id: string
  cohort: string
  status: 'RUNNING' | 'DRAINING' | 'STOPPED'
  concurrency: number
  active_count: number
  hostname: string | null
  heartbeat_at: string | null
  registered_at: string | null
  stopped_at: string | null
}

export interface FleetView {
  workers: FleetWorker[]
  capacity_by_cohort: Record<string, number>
}

export interface QueueDepth {
  queued: number
  running: number
  workers: number
  workers_accepting_work: number
  capacity: number
  active: number
  available_slots: number
}

export interface JobDefinition {
  id: ID
  organization_id: ID | null
  name: string
  handler_key: string
  schedule_kind: string
  schedule_spec: Record<string, unknown>
  params: Record<string, unknown>
  enabled: boolean
  timeout_seconds: number
  retry_policy: Record<string, unknown>
  concurrency_policy: string
  next_run_at: string | null
  last_claimed_at: string | null
}

export interface JobRun {
  id: ID
  job_definition_id: ID
  occurrence_key: string
  status: string
  attempt: number
  lease_owner: string | null
  started_at: string | null
  ended_at: string | null
  error: string | null
  result: Record<string, unknown> | null
  created_at: string | null
}

export interface EnvironmentRecord {
  id: ID
  name: string
  display_name: string
  is_production: boolean
  policy: Record<string, unknown>
}

export interface PromotionPath {
  id: ID
  from_environment_id: ID
  to_environment_id: ID
  requires_approval: boolean
}

export interface PreflightResult {
  id?: ID
  deployment_id: ID
  verdict: 'PASS' | 'WARNING' | 'BLOCK'
  findings: GateFinding[]
  evaluated_at: string | null
}

export interface RollbackEventRecord {
  id: ID
  deployment_id: ID
  trigger: string
  status: string
  reason: string | null
  from_version_id: ID | null
  to_version_id: ID | null
  initiated_by: ID | null
  created_at: string | null
}

export const operationsService = {
  // ----- Read models (Phase 3.10's four aggregation endpoints) ------------ //
  async overview(environmentId?: ID): Promise<OperationsOverview> {
    const suffix = environmentId ? `?environment_id=${environmentId}` : ''
    const { data } = await apiClient.get<OperationsOverview>(`${BASE}/operations/overview${suffix}`)
    return data
  },

  async releaseHistory(filters: { agent_id?: ID; environment_id?: ID; limit?: number } = {})
    : Promise<TimelineEntry[]> {
    const params = new URLSearchParams()
    if (filters.agent_id) params.set('agent_id', filters.agent_id)
    if (filters.environment_id) params.set('environment_id', filters.environment_id)
    params.set('limit', String(filters.limit ?? 100))
    const { data } = await apiClient.get<TimelineEntry[]>(
      `${BASE}/operations/release-history?${params.toString()}`)
    return data
  },

  async deploymentDetail(id: ID): Promise<DeploymentDetail> {
    const { data } = await apiClient.get<DeploymentDetail>(`${BASE}/operations/deployments/${id}`)
    return data
  },

  async rollouts(filters: { agent_id?: ID; environment_id?: ID; active_only?: boolean } = {})
    : Promise<RolloutSummary[]> {
    const params = new URLSearchParams()
    if (filters.agent_id) params.set('agent_id', filters.agent_id)
    if (filters.environment_id) params.set('environment_id', filters.environment_id)
    if (filters.active_only) params.set('active_only', 'true')
    const suffix = params.toString() ? `?${params.toString()}` : ''
    const { data } = await apiClient.get<RolloutSummary[]>(`${BASE}/rollouts${suffix}`)
    return data
  },

  // ----- Rollouts: Phase 3.5's engine, triggered ------------------------- //
  async rollout(id: ID): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.get<RolloutPlanDetail>(`${BASE}/rollouts/${id}`)
    return data
  },
  async rolloutHealth(id: ID): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get<Record<string, unknown>>(`${BASE}/rollouts/${id}/health`)
    return data
  },
  async advanceRollout(id: ID): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(`${BASE}/rollouts/${id}/advance`, {})
    return data
  },
  async pauseRollout(id: ID, reason: string): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(`${BASE}/rollouts/${id}/pause`, { reason })
    return data
  },
  async resumeRollout(id: ID, reason: string): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(`${BASE}/rollouts/${id}/resume`, { reason })
    return data
  },
  async abortRollout(id: ID, reason: string): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(`${BASE}/rollouts/${id}/abort`, { reason })
    return data
  },
  async requestRolloutRollback(id: ID, reason: string): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(
      `${BASE}/rollouts/${id}/request-rollback`, { reason })
    return data
  },

  // ----- Traffic: Phase 3.4's allocator, never bypassed ------------------ //
  async traffic(agentId: ID, environmentId: ID): Promise<TrafficAllocation | null> {
    const { data } = await apiClient.get<TrafficAllocation | null>(
      `${BASE}/agents/${agentId}/environments/${environmentId}/traffic`)
    return data
  },
  async trafficHistory(agentId: ID, environmentId: ID): Promise<TrafficAllocation[]> {
    const { data } = await apiClient.get<TrafficAllocation[]>(
      `${BASE}/agents/${agentId}/environments/${environmentId}/traffic/history`)
    return data
  },
  /**
   * The only way this UI changes weights. Phase 3.4 validates the total, checks
   * every version's eligibility, writes a new revision and audits it — none of
   * which is re-implemented here.
   */
  async setTraffic(agentId: ID, environmentId: ID,
                   weights: TrafficWeightEntry[], reason: string): Promise<TrafficAllocation> {
    const { data } = await apiClient.put<TrafficAllocation>(
      `${BASE}/agents/${agentId}/environments/${environmentId}/traffic`, { weights, reason })
    return data
  },

  // ----- Release gates: Phase 3.3 ---------------------------------------- //
  async preflight(deploymentId: ID): Promise<PreflightResult | null> {
    const { data } = await apiClient.get<PreflightResult | null>(
      `${BASE}/deployments/${deploymentId}/preflight`)
    return data
  },
  async runPreflight(deploymentId: ID): Promise<PreflightResult> {
    const { data } = await apiClient.post<PreflightResult>(
      `${BASE}/deployments/${deploymentId}/preflight`, {})
    return data
  },
  async preflightHistory(deploymentId: ID): Promise<PreflightResult[]> {
    const { data } = await apiClient.get<PreflightResult[]>(
      `${BASE}/deployments/${deploymentId}/preflight/history`)
    return data
  },

  // ----- Environments & promotion: Phase 3.2 ----------------------------- //
  async environments(): Promise<EnvironmentRecord[]> {
    const { data } = await apiClient.get<EnvironmentRecord[]>(`${BASE}/environments`)
    return data
  },
  async promotionPaths(): Promise<PromotionPath[]> {
    const { data } = await apiClient.get<PromotionPath[]>(`${BASE}/promotion-paths`)
    return data
  },
  async promote(deploymentId: ID, targetEnvironmentId: ID): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${deploymentId}/promote`,
      { target_environment_id: targetEnvironmentId })
    return data
  },

  // ----- Rollback: Phase 3.7 --------------------------------------------- //
  async rollbackHistory(deploymentId: ID): Promise<RollbackEventRecord[]> {
    const { data } = await apiClient.get<RollbackEventRecord[]>(
      `${BASE}/deployments/${deploymentId}/rollback/history`)
    return data
  },
  async executeRollback(deploymentId: ID, reason: string): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${deploymentId}/rollback/execute`,
      { reason })
    return data
  },
  /** Elevated: requires `runtime.deployment.force_rollback`, which the server checks. */
  async forceRollback(deploymentId: ID, targetVersionId: ID, justification: string): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${deploymentId}/rollback/force`,
      { target_version_id: targetVersionId, justification })
    return data
  },

  // ----- Deployment lifecycle: Phase 3.1 --------------------------------- //
  async pauseDeployment(id: ID, reason: string): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${id}/lifecycle/pause`, { reason })
    return data
  },
  async resumeDeployment(id: ID, reason: string): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${id}/lifecycle/resume`, { reason })
    return data
  },

  // ----- Strategies: Phases 3.6 / 3.9 ------------------------------------ //
  async executeStrategy(deploymentId: ID): Promise<unknown> {
    const { data } = await apiClient.post(`${BASE}/deployments/${deploymentId}/strategy/execute`, {})
    return data
  },
  async startRolling(deploymentId: ID, options: Record<string, unknown> = {}): Promise<RolloutPlanDetail> {
    const { data } = await apiClient.post<RolloutPlanDetail>(
      `${BASE}/deployments/${deploymentId}/strategy/rolling`, options)
    return data
  },
  async blueGreenSwitch(deploymentId: ID): Promise<unknown> {
    const { data } = await apiClient.post(
      `${BASE}/deployments/${deploymentId}/strategy/blue-green/switch`, {})
    return data
  },

  // ----- Worker fleet: Phase 3.9 (at /fleet — M1 owns /workers) ---------- //
  async fleet(): Promise<FleetView> {
    const { data } = await apiClient.get<FleetView>(`${BASE}/fleet`)
    return data
  },
  async queueDepth(): Promise<QueueDepth> {
    const { data } = await apiClient.get<QueueDepth>(`${BASE}/fleet/queue-depth`)
    return data
  },
  async drainWorker(workerId: string): Promise<FleetWorker> {
    const { data } = await apiClient.post<FleetWorker>(
      `${BASE}/fleet/workers/${encodeURIComponent(workerId)}/drain`, {})
    return data
  },
  async reapFleet(): Promise<QueueDepth> {
    const { data } = await apiClient.post<QueueDepth>(`${BASE}/fleet/reap`, {})
    return data
  },

  // ----- Scheduler: Phase 3.8 -------------------------------------------- //
  async jobs(): Promise<JobDefinition[]> {
    const { data } = await apiClient.get<JobDefinition[]>(`${BASE}/scheduler/jobs`)
    return data
  },
  async jobRuns(definitionId: ID): Promise<JobRun[]> {
    const { data } = await apiClient.get<JobRun[]>(`${BASE}/scheduler/jobs/${definitionId}/runs`)
    return data
  },
  async setJobEnabled(definitionId: ID, enabled: boolean): Promise<JobDefinition> {
    const { data } = await apiClient.patch<JobDefinition>(
      `${BASE}/scheduler/jobs/${definitionId}`, { enabled })
    return data
  },
}
