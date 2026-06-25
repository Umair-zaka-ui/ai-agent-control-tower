import { RISK_THRESHOLDS } from '@/constants/app'

export type RiskLevel = 'low' | 'medium' | 'high'

/** Bucket a 0–100 risk score into a level using the backend thresholds. */
export function getRiskLevel(score: number): RiskLevel {
  if (score <= RISK_THRESHOLDS.ALLOW_MAX) return 'low'
  if (score <= RISK_THRESHOLDS.APPROVAL_MAX) return 'medium'
  return 'high'
}

/** Tailwind text-color class for a risk level (uses semantic theme tokens). */
export function getRiskColorClass(score: number): string {
  switch (getRiskLevel(score)) {
    case 'low':
      return 'text-success'
    case 'medium':
      return 'text-warning'
    case 'high':
      return 'text-destructive'
  }
}
