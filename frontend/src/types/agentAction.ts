import type { ID, ISODateString, JsonObject } from './common'

export type Decision = 'ALLOW' | 'BLOCK' | 'PENDING_APPROVAL'

export interface AgentAction {
  id: ID
  agent_id: ID
  resource: string
  action: string
  input_payload: JsonObject
  decision: Decision
  risk_score: number
  decision_reason: string
  status: string
  matched_policy?: string | null
  created_at: ISODateString
}
