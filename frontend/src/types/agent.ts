import type { ID, ISODateString } from './common'

export type AgentStatus = 'ACTIVE' | 'SUSPENDED' | 'DISABLED'

export interface Agent {
  id: ID
  name: string
  description?: string | null
  status: AgentStatus
  organization_id: ID
  created_at: ISODateString
  updated_at?: ISODateString | null
}

export interface ApiKey {
  id: ID
  agent_id: ID
  prefix: string
  last_used_at?: ISODateString | null
  revoked: boolean
  created_at: ISODateString
}

/** Returned once on generation — the raw key is never retrievable again. */
export interface GeneratedApiKey extends ApiKey {
  api_key: string
}
