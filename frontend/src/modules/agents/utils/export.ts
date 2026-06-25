import type { Agent } from '../types'

const CSV_COLUMNS: { key: keyof Agent; header: string }[] = [
  { key: 'id', header: 'ID' },
  { key: 'name', header: 'Name' },
  { key: 'agent_type', header: 'Type' },
  { key: 'status', header: 'Status' },
  { key: 'owner', header: 'Owner' },
  { key: 'department', header: 'Department' },
  { key: 'risk_level', header: 'Risk Level' },
  { key: 'version', header: 'Version' },
  { key: 'created_at', header: 'Created' },
]

function escapeCsv(value: unknown): string {
  const text = value == null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function triggerDownload(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/** Export agents to a CSV file download. */
export function exportAgentsCsv(agents: Agent[]): void {
  const header = CSV_COLUMNS.map((c) => c.header).join(',')
  const rows = agents.map((a) => CSV_COLUMNS.map((c) => escapeCsv(a[c.key])).join(','))
  triggerDownload([header, ...rows].join('\n'), 'agents.csv', 'text/csv;charset=utf-8')
}

/** Export agents to a JSON file download. */
export function exportAgentsJson(agents: Agent[]): void {
  triggerDownload(JSON.stringify(agents, null, 2), 'agents.json', 'application/json')
}
