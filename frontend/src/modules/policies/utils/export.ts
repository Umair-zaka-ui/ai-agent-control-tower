import type { Policy } from '../types'

const COLUMNS: { key: keyof Policy; header: string }[] = [
  { key: 'name', header: 'Name' },
  { key: 'resource', header: 'Resource' },
  { key: 'action', header: 'Action' },
  { key: 'decision', header: 'Decision' },
  { key: 'severity', header: 'Severity' },
  { key: 'status', header: 'Status' },
  { key: 'trigger_count', header: 'Trigger Count' },
  { key: 'created_at', header: 'Created' },
]

function escapeCsv(value: unknown): string {
  const text = value == null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** Export the policies table to a CSV download. */
export function exportPoliciesCsv(policies: Policy[]): void {
  const header = COLUMNS.map((c) => c.header).join(',')
  const rows = policies.map((p) => COLUMNS.map((c) => escapeCsv(p[c.key])).join(','))
  const content = [header, ...rows].join('\n')
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'policies.csv'
  link.click()
  URL.revokeObjectURL(url)
}
