import type { ApprovalDetail, ApprovalListItem } from '../types'

const COLUMNS: { key: keyof ApprovalListItem; header: string }[] = [
  { key: 'id', header: 'Approval ID' },
  { key: 'agent_name', header: 'Agent' },
  { key: 'action', header: 'Action' },
  { key: 'resource', header: 'Resource' },
  { key: 'risk_score', header: 'Risk Score' },
  { key: 'priority', header: 'Priority' },
  { key: 'decision', header: 'Status' },
  { key: 'reviewer_name', header: 'Reviewer' },
  { key: 'created_at', header: 'Created' },
]

function escapeCsv(value: unknown): string {
  const text = value == null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function download(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/** Export the approvals table to a CSV download (SRS §Bulk Actions / Export). */
export function exportApprovalsCsv(items: ApprovalListItem[], filename = 'approvals.csv'): void {
  const header = COLUMNS.map((c) => c.header).join(',')
  const rows = items.map((it) => COLUMNS.map((c) => escapeCsv(it[c.key])).join(','))
  download([header, ...rows].join('\n'), filename, 'text/csv;charset=utf-8')
}

/** Export a single approval's full detail payload as JSON (SRS §Export → JSON). */
export function exportApprovalJson(detail: ApprovalDetail): void {
  download(JSON.stringify(detail, null, 2), `approval-${detail.id}.json`, 'application/json')
}
