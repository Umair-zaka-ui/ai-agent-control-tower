import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { parseConditions } from '../utils/policyValidators'
import { humanizeConditions } from '../utils/policyFormatters'

interface PolicyConditionBuilderProps {
  /** Raw JSON text the user is editing. */
  value: string
  onChange: (value: string) => void
}

const EXAMPLES = ['amount_gt', 'amount_lt', 'risk_score_gt', 'field_eq', 'contains_phi_eq']

/**
 * Conditions editor: simple JSON editing with a live human-readable preview
 * (SRS §Step 4 — "simple JSON editing plus visual preview").
 */
export function PolicyConditionBuilder({ value, onChange }: PolicyConditionBuilderProps) {
  const parsed = parseConditions(value)

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor="conditions">Conditions (JSON)</Label>
        <Textarea
          id="conditions"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={6}
          spellCheck={false}
          className="font-mono text-xs"
          placeholder={'{\n  "amount_gt": 10000,\n  "risk_score_gt": 70\n}'}
        />
        <p className="text-xs text-muted-foreground">
          Keys use <code>field_op</code> form. Supported ops: gt, gte, lt, lte, eq, ne, in,
          contains. Examples: {EXAMPLES.join(', ')}. Empty = always matches.
        </p>
      </div>

      <div className="rounded-md border border-border bg-background p-3">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Preview</p>
        {parsed.ok ? (
          <ul className="space-y-1 text-sm">
            {humanizeConditions(parsed.value).map((clause, i) => (
              <li key={i} className="text-foreground">
                • {clause}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-destructive">{parsed.error}</p>
        )}
      </div>
    </div>
  )
}
