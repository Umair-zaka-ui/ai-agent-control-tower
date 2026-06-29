import { apiClient } from '@/services/apiClient'
import type { ID } from '@/types'
import type {
  ApprovalComment,
  ApprovalDetail,
  ApprovalListItem,
  ApprovalListParams,
  ApprovalStatistics,
  ApprovalTimelineEvent,
  AssignInput,
  EscalateInput,
  ReviewInput,
} from '../types'

/** Approval / Human Review Workbench API (Phase 3 Part 3.4). */
export const approvalService = {
  async list(params: ApprovalListParams = {}): Promise<ApprovalListItem[]> {
    const { data } = await apiClient.get<ApprovalListItem[]>('/approvals', { params })
    return data
  },

  async get(id: ID): Promise<ApprovalDetail> {
    const { data } = await apiClient.get<ApprovalDetail>(`/approvals/${id}`)
    return data
  },

  async statistics(): Promise<ApprovalStatistics> {
    const { data } = await apiClient.get<ApprovalStatistics>('/approvals/statistics')
    return data
  },

  async history(params: { status?: string; search?: string } = {}): Promise<ApprovalListItem[]> {
    const { data } = await apiClient.get<ApprovalListItem[]>('/approvals/history', { params })
    return data
  },

  async escalations(): Promise<ApprovalListItem[]> {
    const { data } = await apiClient.get<ApprovalListItem[]>('/approvals/escalations')
    return data
  },

  async timeline(id: ID): Promise<ApprovalTimelineEvent[]> {
    const { data } = await apiClient.get<ApprovalTimelineEvent[]>(`/approvals/${id}/timeline`)
    return data
  },

  async comments(id: ID): Promise<ApprovalComment[]> {
    const { data } = await apiClient.get<ApprovalComment[]>(`/approvals/${id}/comments`)
    return data
  },

  async addComment(id: ID, comment: string): Promise<ApprovalComment> {
    const { data } = await apiClient.post<ApprovalComment>(`/approvals/${id}/comments`, { comment })
    return data
  },

  async approve(id: ID, input: ReviewInput = {}): Promise<void> {
    await apiClient.post(`/approvals/${id}/approve`, input)
  },

  async reject(id: ID, input: ReviewInput = {}): Promise<void> {
    await apiClient.post(`/approvals/${id}/reject`, input)
  },

  async escalate(id: ID, input: EscalateInput): Promise<void> {
    await apiClient.post(`/approvals/${id}/escalate`, input)
  },

  async assign(id: ID, input: AssignInput): Promise<void> {
    await apiClient.post(`/approvals/${id}/assign`, input)
  },
}
