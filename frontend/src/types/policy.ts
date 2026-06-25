import type { Decision } from './agentAction'
import type { ID, ISODateString, JsonObject } from './common'

export interface Policy {
  id: ID
  name: string
  resource: string
  action: string
  conditions: JsonObject
  decision: Decision
  priority: number
  is_active: boolean
  created_at: ISODateString
  updated_at?: ISODateString | null
}

export interface PolicyInput {
  name: string
  resource: string
  action: string
  conditions: JsonObject
  decision: Decision
  priority: number
}
