import { Check, X } from 'lucide-react'

import { cn } from '@/utils/cn'
import { STRENGTH_LABEL, type PasswordStrength } from '../passwordStrength'

const BAR_COLOR: Record<PasswordStrength['level'], string> = {
  empty: 'bg-border',
  weak: 'bg-destructive',
  fair: 'bg-warning',
  good: 'bg-primary',
  strong: 'bg-success',
}

interface PasswordStrengthMeterProps {
  strength: PasswordStrength
  /** Hidden until the user has typed something, so the form does not shout on load. */
  visible?: boolean
}

/**
 * Real-time password requirements (SRS §17).
 *
 * Accessibility: the meter is `role="status"` + `aria-live="polite"` so a screen
 * reader announces the strength as it changes, without stealing focus. Each rule is a
 * list item whose icon is `aria-hidden` — the text already says whether it is met, so
 * announcing "check mark" twice would be noise.
 */
export function PasswordStrengthMeter({ strength, visible = true }: PasswordStrengthMeterProps) {
  if (!visible || strength.level === 'empty') return null

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div
          className="h-1.5 flex-1 overflow-hidden rounded-full bg-border"
          role="progressbar"
          aria-valuenow={strength.score}
          aria-valuemin={0}
          aria-valuemax={4}
          aria-label="Password strength"
        >
          <div
            className={cn('h-full rounded-full transition-all', BAR_COLOR[strength.level])}
            style={{ width: `${(strength.score / 4) * 100}%` }}
          />
        </div>
        <span
          role="status"
          aria-live="polite"
          className="w-12 shrink-0 text-xs font-medium text-muted-foreground"
        >
          {STRENGTH_LABEL[strength.level]}
        </span>
      </div>

      <ul className="space-y-1" data-testid="password-rules">
        {strength.rules.map((rule) => (
          <li
            key={rule.id}
            className={cn(
              'flex items-center gap-1.5 text-xs',
              rule.satisfied ? 'text-success' : 'text-muted-foreground',
            )}
          >
            {rule.satisfied ? (
              <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            ) : (
              <X className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            )}
            <span>{rule.label}</span>
            <span className="sr-only">{rule.satisfied ? '— met' : '— not met'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
