import type {
  AgentCapability,
  AgentDefinition,
  AgentExecution,
  AgentIdentityRecord,
  AgentLifecycleEventEntry,
  AgentTool,
  AgentVersion,
  Capability,
  ChangeCategory,
  Deployment,
  DeploymentHealth,
  DuplicateMatch,
  DuplicateReviewDecision,
  ExecutionAttempt,
  ExportJob,
  ExportType,
  ID,
  ImportItem,
  ImportJob,
  MigrationRecord,
  AgentOwnershipHistoryEntry,
  OwnerRole,
  ReleaseArtifact,
  ReleaseArtifactType,
  ReleaseChannel,
  ReleaseMetadata,
  ReleaseNote,
  ReleaseNoteCategory,
  RuntimeAgent,
  RuntimeApproval,
  RuntimeDashboard,
  RuntimeEvent,
  RuntimeTool,
  ToolCall,
  ValidationRun,
  VersionComparison,
  VersionReadiness,
  VersionSnapshot,
  VersionStatusHistoryEntry,
  WorkerStatus,
} from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/runtime'

export interface AgentSearchFilters {
  query?: string
  project_id?: ID
  owner_id?: ID
  status?: string
  agent_type?: string
  framework?: string
  criticality?: string
  risk_level?: string
  data_classification?: string
  autonomy_level?: string
  tag?: string[]
  view?: string
  page?: number
  page_size?: number
  sort?: string
}

export interface AgentRegistrationPayload {
  name: string
  display_name?: string
  description?: string
  business_purpose?: string
  agent_type?: string
  tags?: string[]
  external_reference?: string
  documentation_url?: string
  repository_url?: string
  project_id?: ID
  business_unit_id?: ID
  department_id?: ID
  team_id?: ID
  owner_type?: string
  owner_id?: ID
  technical_owner_id?: ID
  compliance_owner_id?: ID
  support_contact?: string
  identity_id?: ID
  definition: {
    name: string
    description?: string
    framework?: string
    framework_version?: string
    entrypoint_type?: string
    entrypoint: string
    runtime_language?: string
    system_instructions?: string
    configuration_schema?: Record<string, unknown>
    input_schema?: Record<string, unknown>
    output_schema?: Record<string, unknown>
    capability_declarations?: string[]
    tool_declarations?: string[]
    model_requirements?: Record<string, unknown>
    memory_requirements?: Record<string, unknown>
    data_requirements?: Record<string, unknown>
    network_requirements?: Record<string, unknown>
    secret_requirements?: Record<string, unknown>
    runtime_requirements?: Record<string, unknown>
    metadata?: Record<string, unknown>
  }
  criticality?: string
  risk_level?: string
  data_classification?: string
  autonomy_level?: string
  default_environment?: string
  metadata?: Record<string, unknown>
}

/**
 * Agent Runtime & Lifecycle Management API (Phase 5.0 §66, mounted at
 * /api/v1/runtime). Every call is re-authorized server-side against the
 * runtime.* permission set; execution requests additionally pass through
 * the Runtime Gateway's RBAC/ABAC/policy/approval pipeline.
 */
export const runtimeService = {
  // --- Dashboard (§70) --- //
  async dashboard(): Promise<RuntimeDashboard> {
    const { data } = await apiClient.get<RuntimeDashboard>(`${BASE}/dashboard`)
    return data
  },

  // --- Agent registry (Phase 5.1 §16, §36-§38, §54, §56, §66) --- //
  async agents(filters: AgentSearchFilters = {}): Promise<RuntimeAgent[]> {
    const q = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null || value === '') continue
      if (Array.isArray(value)) { for (const v of value) q.append(key, v); continue }
      q.set(key, String(value))
    }
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<RuntimeAgent[]>(`${BASE}/agents${suffix}`)
    return data
  },
  async agent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.get<RuntimeAgent>(`${BASE}/agents/${id}`)
    return data
  },
  async registerAgent(payload: AgentRegistrationPayload): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents`, payload)
    return data
  },
  async updateAgent(id: ID, payload: Record<string, unknown> & { row_version: number }): Promise<RuntimeAgent> {
    const { data } = await apiClient.patch<RuntimeAgent>(`${BASE}/agents/${id}`, payload)
    return data
  },
  async deleteAgent(id: ID): Promise<void> {
    await apiClient.delete(`${BASE}/agents/${id}`)
  },
  async agentDefinitions(id: ID): Promise<AgentDefinition[]> {
    const { data } = await apiClient.get<AgentDefinition[]>(`${BASE}/agents/${id}/definitions`)
    return data
  },

  // --- Lifecycle actions (§19, §20, §54) --- //
  async registerLifecycleAction(id: ID, reason?: string): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/register`, { reason })
    return data
  },
  async validateAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/validate`)
    return data
  },
  async submitForApproval(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/submit-for-approval`)
    return data
  },
  async approveAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/approve`)
    return data
  },
  async rejectAgent(id: ID, reason: string): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/reject`, { reason })
    return data
  },
  async activateAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/activate`)
    return data
  },
  async suspendAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/suspend`)
    return data
  },
  async resumeAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/resume`)
    return data
  },
  async deprecateAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/deprecate`)
    return data
  },
  async archiveAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/archive`)
    return data
  },
  async restoreAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/restore`)
    return data
  },
  async retireAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/retire`)
    return data
  },

  // --- Ownership (§12, §13, §54) --- //
  async getOwnership(id: ID): Promise<{
    owner_type: string | null; owner_id: ID | null
    technical_owner_id: ID | null; compliance_owner_id: ID | null
  }> {
    const { data } = await apiClient.get(`${BASE}/agents/${id}/ownership`)
    return data
  },
  async transferOwnership(id: ID, payload: {
    owner_role: OwnerRole; new_owner_type: string; new_owner_id: ID; reason: string
  }): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/ownership/transfer`, payload)
    return data
  },
  async ownershipHistory(id: ID): Promise<AgentOwnershipHistoryEntry[]> {
    const { data } = await apiClient.get<AgentOwnershipHistoryEntry[]>(`${BASE}/agents/${id}/ownership/history`)
    return data
  },

  // --- Machine identity (§11, §54) --- //
  async getIdentity(id: ID): Promise<AgentIdentityRecord | null> {
    const { data } = await apiClient.get<AgentIdentityRecord | null>(`${BASE}/agents/${id}/identity`)
    return data
  },
  async associateIdentity(id: ID, identity_id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/identity/associate`, { identity_id })
    return data
  },
  async createAndAssociateIdentity(id: ID, payload: {
    client_id: string; credential_type?: string; expires_at?: string
  }): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(
      `${BASE}/agents/${id}/identity/create-and-associate`, payload)
    return data
  },
  async replaceIdentity(id: ID, payload: {
    client_id: string; credential_type?: string; expires_at?: string; reason: string
  }): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/identity/replace`, payload)
    return data
  },

  // --- Validation (§25-§30, §54) --- //
  async validations(id: ID): Promise<ValidationRun[]> {
    const { data } = await apiClient.get<ValidationRun[]>(`${BASE}/agents/${id}/validations`)
    return data
  },
  async testSchema(id: ID, payload: {
    schema_type: 'INPUT' | 'OUTPUT' | 'CONFIGURATION'; payload: Record<string, unknown>
  }): Promise<{ valid: boolean; errors: string[] }> {
    const { data } = await apiClient.post(`${BASE}/agents/${id}/schemas/test`, payload)
    return data
  },

  // --- Duplicate detection (§32, §33, §54, §64) --- //
  async duplicateCheck(id: ID): Promise<DuplicateMatch[]> {
    const { data } = await apiClient.post<DuplicateMatch[]>(`${BASE}/agents/${id}/duplicate-check`)
    return data
  },
  async duplicateMatches(id: ID): Promise<DuplicateMatch[]> {
    const { data } = await apiClient.get<DuplicateMatch[]>(`${BASE}/agents/${id}/duplicate-matches`)
    return data
  },
  async reviewDuplicate(agentId: ID, matchId: ID, payload: {
    review_decision: DuplicateReviewDecision; review_reason: string
  }): Promise<DuplicateMatch> {
    const { data } = await apiClient.post<DuplicateMatch>(
      `${BASE}/agents/${agentId}/duplicate-matches/${matchId}/review`, payload)
    return data
  },

  // --- Import / export (§39-§45, §54) --- //
  async importAgents(payload: {
    file_name: string; format: 'JSON' | 'YAML' | 'CSV'
    mode: 'CREATE_ONLY' | 'UPDATE_DRAFTS' | 'UPSERT_NON_ACTIVE' | 'VALIDATE_ONLY'; content: string
  }): Promise<ImportJob> {
    const { data } = await apiClient.post<ImportJob>(`${BASE}/agents/import`, payload)
    return data
  },
  async importJob(jobId: ID): Promise<ImportJob> {
    const { data } = await apiClient.get<ImportJob>(`${BASE}/agents/import/${jobId}`)
    return data
  },
  async importItems(jobId: ID): Promise<ImportItem[]> {
    const { data } = await apiClient.get<ImportItem[]>(`${BASE}/agents/import/${jobId}/items`)
    return data
  },
  async exportAgents(payload: {
    export_type: ExportType; format: 'JSON' | 'YAML' | 'CSV'; filters?: Record<string, unknown>
  }): Promise<ExportJob> {
    const { data } = await apiClient.post<ExportJob>(`${BASE}/agents/export`, payload)
    return data
  },
  async exportJob(jobId: ID): Promise<ExportJob> {
    const { data } = await apiClient.get<ExportJob>(`${BASE}/agents/export/${jobId}`)
    return data
  },
  exportDownloadUrl(jobId: ID): string {
    return `${BASE}/agents/export/${jobId}/download`
  },

  // --- Legacy migration classification (§70-§73) --- //
  async classifyLegacyAgents(): Promise<MigrationRecord[]> {
    const { data } = await apiClient.post<MigrationRecord[]>(`${BASE}/agents/migration/classify`)
    return data
  },
  async migrationRecords(batchId?: string): Promise<MigrationRecord[]> {
    const suffix = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : ''
    const { data } = await apiClient.get<MigrationRecord[]>(`${BASE}/agents/migration/records${suffix}`)
    return data
  },

  // --- Lifecycle & audit history (§21, §38 Lifecycle/Audit tabs) --- //
  async agentLifecycleEvents(id: ID): Promise<AgentLifecycleEventEntry[]> {
    const { data } = await apiClient.get<AgentLifecycleEventEntry[]>(`${BASE}/agents/${id}/lifecycle-events`)
    return data
  },
  async agentEvents(id: ID): Promise<RuntimeEvent[]> {
    const { data } = await apiClient.get<RuntimeEvent[]>(`${BASE}/agents/${id}/events`)
    return data
  },

  // --- Agent versions (§11, §12, §66) --- //
  async versions(agentId: ID): Promise<AgentVersion[]> {
    const { data } = await apiClient.get<AgentVersion[]>(`${BASE}/agents/${agentId}/versions`)
    return data
  },
  async version(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.get<AgentVersion>(`${BASE}/agents/${agentId}/versions/${versionId}`)
    return data
  },
  async createVersion(agentId: ID, payload: {
    semantic_version?: string
    release_channel?: string
    model_configuration: Record<string, unknown>
    prompt_snapshot?: Record<string, unknown>
    capability_ids?: ID[]
    tool_ids?: ID[]
    policy_snapshot?: Record<string, unknown>
    release_notes?: string
  }): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(`${BASE}/agents/${agentId}/versions`, payload)
    return data
  },
  async validateVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/validate`)
    return data
  },
  async approveVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/approve`)
    return data
  },
  async publishVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/publish`)
    return data
  },
  async deprecateVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/deprecate`)
    return data
  },
  async revokeVersion(agentId: ID, versionId: ID, reason?: string): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/revoke`, { reason })
    return data
  },
  async retireVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/retire`)
    return data
  },

  // --- Version release management (Phase 5.2 Part 1) --- //
  async versionSnapshot(agentId: ID, versionId: ID): Promise<VersionSnapshot | null> {
    const { data } = await apiClient.get<VersionSnapshot | null>(
      `${BASE}/agents/${agentId}/versions/${versionId}/snapshot`)
    return data
  },
  async versionStatusHistory(agentId: ID, versionId: ID): Promise<VersionStatusHistoryEntry[]> {
    const { data } = await apiClient.get<VersionStatusHistoryEntry[]>(
      `${BASE}/agents/${agentId}/versions/${versionId}/status-history`)
    return data
  },
  async setRollbackTarget(agentId: ID, versionId: ID, targetVersionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/rollback-target`,
      { target_version_id: targetVersionId })
    return data
  },
  async releaseMetadata(agentId: ID, versionId: ID): Promise<ReleaseMetadata | null> {
    const { data } = await apiClient.get<ReleaseMetadata | null>(
      `${BASE}/agents/${agentId}/versions/${versionId}/release-metadata`)
    return data
  },
  async upsertReleaseMetadata(agentId: ID, versionId: ID, payload: {
    release_name?: string
    release_description?: string
    business_justification?: string
    change_category?: ChangeCategory
    release_window_start?: string
    release_window_end?: string
    support_end_date?: string
    approval_ticket?: string
    source_branch?: string
    commit_reference?: string
    build_reference?: string
    risk_score?: number
    documentation_url?: string
  }): Promise<ReleaseMetadata> {
    const { data } = await apiClient.post<ReleaseMetadata>(
      `${BASE}/agents/${agentId}/versions/${versionId}/release-metadata`, payload)
    return data
  },
  async releaseArtifacts(agentId: ID, versionId: ID): Promise<ReleaseArtifact[]> {
    const { data } = await apiClient.get<ReleaseArtifact[]>(
      `${BASE}/agents/${agentId}/versions/${versionId}/artifacts`)
    return data
  },
  async addReleaseArtifact(agentId: ID, versionId: ID, payload: {
    artifact_type: ReleaseArtifactType; reference: string
  }): Promise<ReleaseArtifact> {
    const { data } = await apiClient.post<ReleaseArtifact>(
      `${BASE}/agents/${agentId}/versions/${versionId}/artifacts`, payload)
    return data
  },
  async releaseNotes(agentId: ID, versionId: ID): Promise<ReleaseNote[]> {
    const { data } = await apiClient.get<ReleaseNote[]>(
      `${BASE}/agents/${agentId}/versions/${versionId}/notes`)
    return data
  },
  async addReleaseNote(agentId: ID, versionId: ID, payload: {
    category: ReleaseNoteCategory; note: string
  }): Promise<ReleaseNote> {
    const { data } = await apiClient.post<ReleaseNote>(
      `${BASE}/agents/${agentId}/versions/${versionId}/notes`, payload)
    return data
  },
  async releaseChannels(): Promise<ReleaseChannel[]> {
    const { data } = await apiClient.get<ReleaseChannel[]>(`${BASE}/release-channels`)
    return data
  },
  async compareVersions(agentId: ID, versionId: ID, otherVersionId: ID): Promise<VersionComparison> {
    const { data } = await apiClient.get<VersionComparison>(
      `${BASE}/agents/${agentId}/versions/${versionId}/compare/${otherVersionId}`)
    return data
  },
  async versionReadiness(agentId: ID, versionId: ID): Promise<VersionReadiness> {
    const { data } = await apiClient.get<VersionReadiness>(
      `${BASE}/agents/${agentId}/versions/${versionId}/readiness`)
    return data
  },

  // --- Deployments (§14, §15, §57, §66) --- //
  async deployments(filters: { agent_id?: ID; status?: string } = {}): Promise<Deployment[]> {
    const q = new URLSearchParams()
    if (filters.agent_id) q.set('agent_id', filters.agent_id)
    if (filters.status) q.set('status', filters.status)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<Deployment[]>(`${BASE}/deployments${suffix}`)
    return data
  },
  async deployment(id: ID): Promise<Deployment> {
    const { data } = await apiClient.get<Deployment>(`${BASE}/deployments/${id}`)
    return data
  },
  async createDeployment(agentId: ID, payload: {
    agent_version_id: ID
    environment: string
    deployment_strategy?: string
    desired_replicas?: number
    runtime_limits?: Record<string, unknown>
  }): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(
      `${BASE}/deployments?agent_id=${agentId}`, payload)
    return data
  },
  async deploy(id: ID): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(`${BASE}/deployments/${id}/deploy`)
    return data
  },
  async suspendDeployment(id: ID): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(`${BASE}/deployments/${id}/suspend`)
    return data
  },
  async resumeDeployment(id: ID): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(`${BASE}/deployments/${id}/resume`)
    return data
  },
  async rollbackDeployment(id: ID, targetVersionId: ID): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(`${BASE}/deployments/${id}/rollback`, {
      target_version_id: targetVersionId,
    })
    return data
  },
  async retireDeployment(id: ID): Promise<Deployment> {
    const { data } = await apiClient.post<Deployment>(`${BASE}/deployments/${id}/retire`)
    return data
  },
  async deploymentHealth(id: ID): Promise<DeploymentHealth[]> {
    const { data } = await apiClient.get<DeploymentHealth[]>(`${BASE}/deployments/${id}/health`)
    return data
  },

  // --- Executions (§24-§28, §66) --- //
  async executions(filters: { agent_id?: ID; status?: string; limit?: number } = {}): Promise<AgentExecution[]> {
    const q = new URLSearchParams()
    if (filters.agent_id) q.set('agent_id', filters.agent_id)
    if (filters.status) q.set('status', filters.status)
    if (filters.limit) q.set('limit', String(filters.limit))
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<AgentExecution[]>(`${BASE}/executions${suffix}`)
    return data
  },
  async execution(id: ID): Promise<AgentExecution> {
    const { data } = await apiClient.get<AgentExecution>(`${BASE}/executions/${id}`)
    return data
  },
  async requestExecution(payload: {
    agent_id: ID
    deployment_id?: ID
    input_payload: Record<string, unknown>
    idempotency_key?: string
    correlation_id?: string
    priority?: string
  }): Promise<AgentExecution> {
    const { data } = await apiClient.post<AgentExecution>(`${BASE}/executions`, payload)
    return data
  },
  async cancelExecution(id: ID): Promise<AgentExecution> {
    const { data } = await apiClient.post<AgentExecution>(`${BASE}/executions/${id}/cancel`)
    return data
  },
  async retryExecution(id: ID): Promise<AgentExecution> {
    const { data } = await apiClient.post<AgentExecution>(`${BASE}/executions/${id}/retry`)
    return data
  },
  async replayExecution(id: ID): Promise<AgentExecution> {
    const { data } = await apiClient.post<AgentExecution>(`${BASE}/executions/${id}/replay`)
    return data
  },
  async executionAttempts(id: ID): Promise<ExecutionAttempt[]> {
    const { data } = await apiClient.get<ExecutionAttempt[]>(`${BASE}/executions/${id}/attempts`)
    return data
  },
  async executionToolCalls(id: ID): Promise<ToolCall[]> {
    const { data } = await apiClient.get<ToolCall[]>(`${BASE}/executions/${id}/tool-calls`)
    return data
  },
  async executionEvents(id: ID): Promise<RuntimeEvent[]> {
    const { data } = await apiClient.get<RuntimeEvent[]>(`${BASE}/executions/${id}/events`)
    return data
  },

  // --- Capabilities (§18, §19, §66) --- //
  async capabilities(): Promise<Capability[]> {
    const { data } = await apiClient.get<Capability[]>(`${BASE}/capabilities`)
    return data
  },
  async createCapability(payload: {
    name: string
    display_name: string
    description?: string
    category?: string
    risk_level?: string
    requires_approval?: boolean
  }): Promise<Capability> {
    const { data } = await apiClient.post<Capability>(`${BASE}/capabilities`, payload)
    return data
  },
  async agentCapabilities(agentId: ID): Promise<AgentCapability[]> {
    const { data } = await apiClient.get<AgentCapability[]>(`${BASE}/agents/${agentId}/capabilities`)
    return data
  },
  async assignCapability(agentId: ID, capabilityId: ID): Promise<AgentCapability> {
    const { data } = await apiClient.post<AgentCapability>(`${BASE}/agents/${agentId}/capabilities`, {
      capability_id: capabilityId,
    })
    return data
  },
  async decideCapability(agentId: ID, assignmentId: ID, approve: boolean): Promise<AgentCapability> {
    const { data } = await apiClient.post<AgentCapability>(
      `${BASE}/agents/${agentId}/capabilities/${assignmentId}/decide?approve=${approve}`)
    return data
  },
  async revokeCapability(agentId: ID, assignmentId: ID): Promise<AgentCapability> {
    const { data } = await apiClient.delete<AgentCapability>(
      `${BASE}/agents/${agentId}/capabilities/${assignmentId}`)
    return data
  },

  // --- Tools (§20, §23, §66) --- //
  async tools(): Promise<RuntimeTool[]> {
    const { data } = await apiClient.get<RuntimeTool[]>(`${BASE}/tools`)
    return data
  },
  async createTool(payload: {
    name: string
    display_name: string
    description?: string
    tool_type?: string
    risk_level?: string
    requires_approval?: boolean
  }): Promise<RuntimeTool> {
    const { data } = await apiClient.post<RuntimeTool>(`${BASE}/tools`, payload)
    return data
  },
  async agentTools(agentId: ID): Promise<AgentTool[]> {
    const { data } = await apiClient.get<AgentTool[]>(`${BASE}/agents/${agentId}/tools`)
    return data
  },
  async assignTool(agentId: ID, toolId: ID, allowedActions: string[] = ['EXECUTE']): Promise<AgentTool> {
    const { data } = await apiClient.post<AgentTool>(`${BASE}/agents/${agentId}/tools`, {
      tool_id: toolId, allowed_actions: allowedActions,
    })
    return data
  },
  async decideTool(agentId: ID, assignmentId: ID, approve: boolean): Promise<AgentTool> {
    const { data } = await apiClient.post<AgentTool>(
      `${BASE}/agents/${agentId}/tools/${assignmentId}/decide?approve=${approve}`)
    return data
  },
  async revokeTool(agentId: ID, assignmentId: ID): Promise<AgentTool> {
    const { data } = await apiClient.delete<AgentTool>(`${BASE}/agents/${agentId}/tools/${assignmentId}`)
    return data
  },

  // --- Runtime approvals (§39, §66) --- //
  async approvals(status?: string): Promise<RuntimeApproval[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<RuntimeApproval[]>(`${BASE}/approvals${suffix}`)
    return data
  },
  async decideApproval(id: ID, decision: 'APPROVED' | 'REJECTED', comment?: string): Promise<RuntimeApproval> {
    const { data } = await apiClient.post<RuntimeApproval>(`${BASE}/approvals/${id}/decide`, {
      decision, comment,
    })
    return data
  },

  // --- Health & workers (§49, §50, §66) --- //
  async platformHealth(): Promise<Record<string, number>> {
    const { data } = await apiClient.get<Record<string, number>>(`${BASE}/health`)
    return data
  },
  async workers(): Promise<WorkerStatus[]> {
    const { data } = await apiClient.get<WorkerStatus[]>(`${BASE}/workers`)
    return data
  },

  // --- Kill switch (§60, §66) --- //
  async killExecution(id: ID, reason: string): Promise<{ executions_cancelled: number }> {
    const { data } = await apiClient.post(`${BASE}/kill-switch/executions/${id}`, { reason })
    return data
  },
  async killAgent(id: ID, reason: string): Promise<{ executions_cancelled: number }> {
    const { data } = await apiClient.post(`${BASE}/kill-switch/agents/${id}`, { reason })
    return data
  },
  async killOrganization(id: ID, reason: string): Promise<{ executions_cancelled: number }> {
    const { data } = await apiClient.post(`${BASE}/kill-switch/organizations/${id}`, { reason })
    return data
  },
  async killProject(id: ID, reason: string): Promise<{ executions_cancelled: number }> {
    const { data } = await apiClient.post(`${BASE}/kill-switch/projects/${id}`, { reason })
    return data
  },
  async killPlatform(reason: string): Promise<{ executions_cancelled: number }> {
    const { data } = await apiClient.post(`${BASE}/kill-switch/platform`, { reason })
    return data
  },
}
