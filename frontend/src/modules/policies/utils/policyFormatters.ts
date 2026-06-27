import type { JsonObject } from '@/types'

const OPS: { suffix: string; phrase: string }[] = [
  { suffix: '_gte', phrase: 'is at least' },
  { suffix: '_lte', phrase: 'is at most' },
  { suffix: '_gt', phrase: 'is greater than' },
  { suffix: '_lt', phrase: 'is less than' },
  { suffix: '_ne', phrase: 'is not' },
  { suffix: '_in', phrase: 'is one of' },
  { suffix: '_contains', phrase: 'contains' },
  { suffix: '_eq', phrase: 'is' },
]

function humanizeField(field: string): string {
  return field.replace(/_/g, ' ')
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/** Turn a conditions object into human-readable clauses (AND-joined). */
export function humanizeConditions(conditions: JsonObject): string[] {
  const entries = Object.entries(conditions ?? {})
  if (entries.length === 0) return ['Always matches (no conditions).']
  return entries.map(([key, value]) => {
    const op = OPS.find((o) => key.endsWith(o.suffix))
    if (op) {
      const field = key.slice(0, -op.suffix.length)
      return `${humanizeField(field)} ${op.phrase} ${formatValue(value)}`
    }
    return `${humanizeField(key)} is ${formatValue(value)}`
  })
}

/** A one-line plain-English summary of a policy rule. */
export function summarizeRule(
  conditions: JsonObject,
  decision: string,
): string {
  const clauses = humanizeConditions(conditions)
  const condition =
    clauses.length === 1 && clauses[0].startsWith('Always')
      ? 'any matching action'
      : `If ${clauses.join(' AND ')}`
  const verb =
    decision === 'BLOCK' ? 'block it' : decision === 'ALLOW' ? 'allow it' : 'require human approval'
  return `${condition}, then ${verb}.`
}
