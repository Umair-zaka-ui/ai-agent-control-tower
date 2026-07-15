import { Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { ABACAttribute, ABACConditionGroup, ABACConditionNode, ABACLeafCondition } from '@/types'
import {
  NO_VALUE_OPERATORS,
  dataTypeOf,
  isLeaf,
  operatorsFor,
  parseTypedValue,
  valueToText,
} from '../lib'

/**
 * Recursive visual condition editor (§34): nested ALL/ANY groups with typed
 * leaf conditions — attribute from the registry, operator from the attribute's
 * supported set, value input typed by the attribute's data type.
 */
export function ConditionBuilder({
  node,
  attributes,
  onChange,
  onRemove,
  depth = 0,
}: {
  node: ABACConditionNode
  attributes: ABACAttribute[]
  onChange: (next: ABACConditionNode) => void
  onRemove?: () => void
  depth?: number
}) {
  if (isLeaf(node)) {
    return (
      <LeafEditor leaf={node} attributes={attributes} onChange={onChange} onRemove={onRemove} />
    )
  }

  const group = node as ABACConditionGroup
  const mode: 'all' | 'any' = group.any ? 'any' : 'all'
  const children = group[mode] ?? []

  const setChildren = (next: ABACConditionNode[]) => onChange({ [mode]: next })
  const defaultLeaf = (): ABACLeafCondition => ({
    attribute: attributes[0]?.name ?? 'action.name',
    operator: operatorsFor(attributes[0]?.name ?? '', attributes)[0] ?? 'EQUALS',
    value: '',
  })

  return (
    <div className={`space-y-2 rounded-md border border-border p-3 ${depth ? 'ml-4' : ''}`}
      data-testid={depth === 0 ? 'condition-root' : undefined}>
      <div className="flex items-center gap-2">
        <select
          value={mode}
          aria-label="Group logic"
          onChange={(e) => onChange({ [e.target.value]: children })}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs font-medium"
        >
          <option value="all">ALL of</option>
          <option value="any">ANY of</option>
        </select>
        <Button type="button" size="sm" variant="outline"
          onClick={() => setChildren([...children, defaultLeaf()])}>
          <Plus className="h-3 w-3" /> Condition
        </Button>
        <Button type="button" size="sm" variant="outline"
          onClick={() => setChildren([...children, { all: [defaultLeaf()] }])}>
          <Plus className="h-3 w-3" /> Group
        </Button>
        {onRemove && (
          <Button type="button" size="sm" variant="ghost" onClick={onRemove}
            aria-label="Remove group">
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        )}
      </div>
      {children.length === 0 && (
        <p className="text-xs text-muted-foreground">Empty group — add a condition.</p>
      )}
      {children.map((child, index) => (
        <ConditionBuilder
          key={index}
          node={child}
          attributes={attributes}
          depth={depth + 1}
          onChange={(next) => setChildren(children.map((c, i) => (i === index ? next : c)))}
          onRemove={() => setChildren(children.filter((_, i) => i !== index))}
        />
      ))}
    </div>
  )
}

function LeafEditor({
  leaf,
  attributes,
  onChange,
  onRemove,
}: {
  leaf: ABACLeafCondition
  attributes: ABACAttribute[]
  onChange: (next: ABACConditionNode) => void
  onRemove?: () => void
}) {
  const operators = operatorsFor(leaf.attribute, attributes)
  const dataType = dataTypeOf(leaf.attribute, attributes)
  const needsValue = !NO_VALUE_OPERATORS.includes(leaf.operator)

  const setAttribute = (attribute: string) => {
    const ops = operatorsFor(attribute, attributes)
    onChange({ attribute, operator: ops[0] ?? 'EQUALS', value: '' })
  }

  return (
    <div className="ml-4 flex flex-wrap items-center gap-2" data-testid="condition-leaf">
      <select value={leaf.attribute} aria-label="Attribute"
        onChange={(e) => setAttribute(e.target.value)}
        className="min-w-40 rounded-md border border-border bg-background px-2 py-1 text-xs">
        {attributes.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
      </select>
      <select value={leaf.operator} aria-label="Operator"
        onChange={(e) => onChange({ ...leaf, operator: e.target.value,
          value: NO_VALUE_OPERATORS.includes(e.target.value) ? undefined : leaf.value })}
        className="rounded-md border border-border bg-background px-2 py-1 text-xs">
        {operators.map((op) => <option key={op} value={op}>{op}</option>)}
      </select>
      {needsValue && (dataType === 'BOOLEAN' && !['IN', 'NOT_IN'].includes(leaf.operator) ? (
        <select value={String(leaf.value ?? 'true')} aria-label="Value"
          onChange={(e) => onChange({ ...leaf, value: e.target.value === 'true' })}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs">
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <Input
          aria-label="Value"
          className="h-7 w-44 text-xs"
          value={valueToText(leaf.value)}
          placeholder={['IN', 'NOT_IN', 'BETWEEN'].includes(leaf.operator) ? 'a, b, c' : 'value'}
          onChange={(e) => onChange({
            ...leaf, value: parseTypedValue(e.target.value, dataType, leaf.operator),
          })}
        />
      ))}
      {onRemove && (
        <Button type="button" size="sm" variant="ghost" onClick={onRemove}
          aria-label="Remove condition">
          <Trash2 className="h-3 w-3 text-destructive" />
        </Button>
      )}
    </div>
  )
}
