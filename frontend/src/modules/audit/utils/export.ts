import type { AuditEventDetail, AuditEventListItem } from '../types'

export type ExportFormat = 'csv' | 'json'

const COLUMNS: { key: keyof AuditEventListItem; header: string }[] = [
  { key: 'created_at', header: 'Timestamp' },
  { key: 'id', header: 'Event ID' },
  { key: 'actor_name', header: 'Actor' },
  { key: 'actor_type', header: 'Actor Type' },
  { key: 'event_type', header: 'Event Type' },
  { key: 'category', header: 'Category' },
  { key: 'resource', header: 'Resource' },
  { key: 'decision', header: 'Decision' },
  { key: 'severity', header: 'Severity' },
  { key: 'status', header: 'Status' },
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

function stamp(): string {
  return new Date().toISOString().slice(0, 10)
}

/** Export the audit event set to a CSV download (SRS §Export Center → CSV). */
export function exportAuditCsv(items: AuditEventListItem[], filename = `audit-${stamp()}.csv`): void {
  const header = COLUMNS.map((c) => c.header).join(',')
  const rows = items.map((it) => COLUMNS.map((c) => escapeCsv(it[c.key])).join(','))
  download([header, ...rows].join('\n'), filename, 'text/csv;charset=utf-8')
}

/** Export the audit event set as JSON (SRS §Export Center → JSON). */
export function exportAuditJson(items: AuditEventListItem[], filename = `audit-${stamp()}.json`): void {
  download(JSON.stringify(items, null, 2), filename, 'application/json')
}

/** Export a single event's full forensic detail as JSON. */
export function exportAuditEventJson(detail: AuditEventDetail): void {
  download(JSON.stringify(detail, null, 2), `audit-event-${detail.id}.json`, 'application/json')
}
