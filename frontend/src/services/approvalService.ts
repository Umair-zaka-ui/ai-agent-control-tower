import type { Approval, ApprovalComment, ApprovalDecisionInput, ID } from '@/types'
import { httpClient } from './httpClient'

/** Approval queue API (Phase 1 /approvals, Phase 2 comments). */
export const approvalService = {
  async listPending(): Promise<Approval[]> {
    const { data } = await httpClient.get<Approval[]>('/approvals/pending')
    return data
  },

  async approve(id: ID, payload: ApprovalDecisionInput = {}): Promise<Approval> {
    const { data } = await httpClient.post<Approval>(`/approvals/${id}/approve`, payload)
    return data
  },

  async reject(id: ID, payload: ApprovalDecisionInput = {}): Promise<Approval> {
    const { data } = await httpClient.post<Approval>(`/approvals/${id}/reject`, payload)
    return data
  },

  async listComments(id: ID): Promise<ApprovalComment[]> {
    const { data } = await httpClient.get<ApprovalComment[]>(`/approvals/${id}/comments`)
    return data
  },

  async addComment(id: ID, body: string): Promise<ApprovalComment> {
    const { data } = await httpClient.post<ApprovalComment>(`/approvals/${id}/comments`, { body })
    return data
  },
}
