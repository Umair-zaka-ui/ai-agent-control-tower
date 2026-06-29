import type { JsonObject } from '@/types'

const OPERATORS: { suffix: string; phrase: string }[] = [
  { suffix: '_gte', phrase: '≥' },
  { suffix: '_lte', phrase: '≤' },
  { suffix: '_gt', phrase: '>' },
  { suffix: '_lt', phrase: '<' },
  { suffix: '_ne', phrase: '≠' },
  { suffix: '_eq', phrase: '=' },
  { suffix: '_in', phrase: 'in' },
  { suffix: '_contains', phrase: 'contains' },
]

function field(name: string): string {
  return name.replace(/_/g, ' ')
}

/** Turn a policy conditions object into readable clauses, mirroring the engine. */
export function humanizeConditions(conditions: JsonObject | null | undefined): string[] {
  if (!conditions) return []
  return Object.entries(conditions).map(([key, value]) => {
    const op = OPERATORS.find((o) => key.endsWith(o.suffix))
    const display = Array.isArray(value) ? value.join(', ') : String(value)
    if (!op) return `${field(key)} = ${display}`
    return `${field(key.slice(0, -op.suffix.length))} ${op.phrase} ${display}`
  })
}
