import type { AnalyticsReport } from '../types'

export type ReportFormat = 'csv' | 'json'

function download(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function escapeCsv(value: unknown): string {
  const text = value == null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** Flatten a generated report to CSV (section, label, value). */
export function exportReportCsv(report: AnalyticsReport): void {
  const header = ['Section', 'Metric', 'Value'].join(',')
  const rows = report.sections.flatMap((s) =>
    s.rows.map((r) => [s.title, r.label, r.value].map(escapeCsv).join(',')),
  )
  download(
    [header, ...rows].join('\n'),
    `analytics-${report.period}-${report.generated_at.slice(0, 10)}.csv`,
    'text/csv;charset=utf-8',
  )
}

/** Export the full report payload as JSON. */
export function exportReportJson(report: AnalyticsReport): void {
  download(
    JSON.stringify(report, null, 2),
    `analytics-${report.period}-${report.generated_at.slice(0, 10)}.json`,
    'application/json',
  )
}
