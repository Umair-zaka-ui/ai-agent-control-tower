import type {
  AgentCapability,
  AgentDefinition,
  AgentExecution,
  AgentTool,
  AgentVersion,
  Capability,
  Deployment,
  DeploymentHealth,
  ExecutionAttempt,
  ID,
  RuntimeAgent,
  RuntimeApproval,
  RuntimeDashboard,
  RuntimeEvent,
  RuntimeTool,
  ToolCall,
  WorkerStatus,
} from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/runtime'

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

  // --- Agent registry (§16, §66) --- //
  async agents(filters: { lifecycle_status?: string; criticality?: string } = {}): Promise<RuntimeAgent[]> {
    const q = new URLSearchParams()
    if (filters.lifecycle_status) q.set('lifecycle_status', filters.lifecycle_status)
    if (filters.criticality) q.set('criticality', filters.criticality)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<RuntimeAgent[]>(`${BASE}/agents${suffix}`)
    return data
  },
  async agent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.get<RuntimeAgent>(`${BASE}/agents/${id}`)
    return data
  },
  async registerAgent(payload: {
    name: string
    description?: string
    agent_type?: string
    criticality?: string
    data_classification?: string
    default_environment?: string
    definition: {
      name: string
      description?: string
      framework?: string
      entrypoint_type?: string
      entrypoint: string
      system_instructions?: string
    }
  }): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents`, payload)
    return data
  },
  async updateAgent(id: ID, payload: Record<string, unknown>): Promise<RuntimeAgent> {
    const { data } = await apiClient.put<RuntimeAgent>(`${BASE}/agents/${id}`, payload)
    return data
  },
  async deleteAgent(id: ID): Promise<void> {
    await apiClient.delete(`${BASE}/agents/${id}`)
  },
  async agentDefinitions(id: ID): Promise<AgentDefinition[]> {
    const { data } = await apiClient.get<AgentDefinition[]>(`${BASE}/agents/${id}/definitions`)
    return data
  },
  async validateAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/validate`)
    return data
  },
  async approveAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/approve`)
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
  async deprecateAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/deprecate`)
    return data
  },
  async archiveAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/archive`)
    return data
  },
  async retireAgent(id: ID): Promise<RuntimeAgent> {
    const { data } = await apiClient.post<RuntimeAgent>(`${BASE}/agents/${id}/retire`)
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
  async revokeVersion(agentId: ID, versionId: ID): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `${BASE}/agents/${agentId}/versions/${versionId}/revoke`)
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
}
