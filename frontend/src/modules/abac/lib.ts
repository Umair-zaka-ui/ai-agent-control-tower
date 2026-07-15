import type {
  ABACAttribute,
  ABACConditionGroup,
  ABACConditionNode,
  ABACLeafCondition,
  ABACPolicy,
  ABACPolicyWrite,
} from '@/types'

/** Shared helpers for the ABAC pages (Phase 4.3.5 §34). */

export const EFFECTS = [
  'DENY', 'ALLOW', 'REQUIRE_APPROVAL', 'REQUIRE_MFA', 'REQUIRE_JUSTIFICATION',
  'MASK_FIELDS', 'LIMIT_ACTION', 'LOG_ONLY',
] as const

export const ALGORITHMS = [
  'DENY_OVERRIDES', 'ALLOW_OVERRIDES', 'FIRST_APPLICABLE', 'HIGHEST_PRIORITY', 'ALL_MUST_ALLOW',
] as const

export const SCOPES = [
  'ORGANIZATION', 'PLATFORM', 'BUSINESS_UNIT', 'DEPARTMENT', 'TEAM', 'PROJECT', 'RESOURCE',
] as const

export const NO_VALUE_OPERATORS = ['EXISTS', 'NOT_EXISTS']
export const LIST_OPERATORS = ['IN', 'NOT_IN', 'BETWEEN']

export function isLeaf(node: ABACConditionNode): node is ABACLeafCondition {
  return (node as ABACLeafCondition).attribute !== undefined
}

export function isGroup(node: ABACConditionNode): node is ABACConditionGroup {
  return !isLeaf(node)
}

/** Parse a typed value from the builder's text input (§34 typed value controls). */
export function parseTypedValue(raw: string, dataType: string, operator: string): unknown {
  if (NO_VALUE_OPERATORS.includes(operator)) return undefined
  const scalar = (text: string): unknown => {
    const t = text.trim()
    if (dataType === 'BOOLEAN') return t.toLowerCase() === 'true'
    if (dataType === 'INTEGER') return Number.parseInt(t, 10)
    if (dataType === 'DECIMAL') return Number.parseFloat(t)
    return t
  }
  if (LIST_OPERATORS.includes(operator)) return raw.split(',').map((part) => scalar(part))
  return scalar(raw)
}

export function valueToText(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/** Human-readable policy preview (§34). */
export function conditionToText(node: ABACConditionNode | null | undefined, depth = 0): string {
  if (!node) return 'always'
  if (isLeaf(node)) {
    const value = NO_VALUE_OPERATORS.includes(node.operator)
      ? ''
      : ` ${valueToText(node.value)}`
    return `${node.attribute} ${node.operator.replaceAll('_', ' ').toLowerCase()}${value}`
  }
  const pad = '  '.repeat(depth + 1)
  if (node.not) return `NOT (${conditionToText(node.not, depth + 1)})`
  const children = node.all ?? node.any ?? []
  const joiner = node.all ? 'AND' : 'OR'
  return children.map((child) => `${depth ? pad : ''}${conditionToText(child, depth + 1)}`)
    .join(`\n${pad}${joiner} `)
}

export function policyToText(policy: Pick<ABACPolicy | ABACPolicyWrite, 'conditions' | 'effect' | 'target'>): string {
  const target = policy.target?.actions?.length
    ? `ON ${policy.target.actions.join(', ')}\n`
    : ''
  return `${target}IF\n  ${conditionToText(policy.conditions ?? null)}\nTHEN\n  ${policy.effect ?? 'DENY'}`
}

export function operatorsFor(attribute: string, attributes: ABACAttribute[]): string[] {
  return attributes.find((a) => a.name === attribute)?.supported_operators ?? ['EQUALS']
}

export function dataTypeOf(attribute: string, attributes: ABACAttribute[]): string {
  return attributes.find((a) => a.name === attribute)?.data_type ?? 'STRING'
}

export const STATUS_STYLES: Record<string, string> = {
  DRAFT: 'bg-muted text-muted-foreground',
  VALIDATED: 'bg-blue-500/10 text-blue-600',
  ACTIVE: 'bg-emerald-500/10 text-emerald-600',
  DISABLED: 'bg-amber-500/10 text-amber-600',
  DEPRECATED: 'bg-muted text-muted-foreground',
  ARCHIVED: 'bg-muted text-muted-foreground',
}

export const DECISION_STYLES: Record<string, string> = {
  ALLOW: 'bg-emerald-500/10 text-emerald-600',
  DENY: 'bg-destructive/10 text-destructive',
  REQUIRE_APPROVAL: 'bg-amber-500/10 text-amber-600',
  REQUIRE_MFA: 'bg-amber-500/10 text-amber-600',
  REQUIRE_JUSTIFICATION: 'bg-amber-500/10 text-amber-600',
  MASK_FIELDS: 'bg-blue-500/10 text-blue-600',
  LIMIT_ACTION: 'bg-blue-500/10 text-blue-600',
  NOT_APPLICABLE: 'bg-muted text-muted-foreground',
}
