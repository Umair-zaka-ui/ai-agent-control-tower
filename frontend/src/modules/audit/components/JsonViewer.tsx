import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Copy, Download } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { JsonObject } from '@/types'
import { cn } from '@/utils/cn'

interface JsonViewerProps {
  payload: JsonObject | null
  title: string
  defaultCollapsed?: boolean
  filename?: string
  /** Shown instead of the JSON when the payload is null (e.g. RBAC-redacted). */
  emptyMessage?: string
}

/** Collapsible JSON viewer with copy + download (SRS §Request/Response Viewer). */
export function JsonViewer({
  payload,
  title,
  defaultCollapsed = false,
  filename = 'payload.json',
  emptyMessage = 'No data available.',
}: JsonViewerProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const [copied, setCopied] = useState(false)
  const hasData = payload != null
  const json = JSON.stringify(payload ?? {}, null, 2)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  const handleDownload = () => {
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-md border border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="inline-flex items-center gap-1 text-sm font-medium"
          aria-expanded={!collapsed}
          disabled={!hasData}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          {title}
        </button>
        {hasData && (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={handleCopy} aria-label="Copy JSON">
              {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button variant="ghost" size="sm" onClick={handleDownload} aria-label="Download JSON">
              <Download className="h-4 w-4" />
              Download
            </Button>
          </div>
        )}
      </div>
      {hasData ? (
        <pre
          className={cn(
            'overflow-x-auto bg-muted/30 p-3 font-mono text-xs text-foreground',
            collapsed && 'hidden',
          )}
        >
          {json}
        </pre>
      ) : (
        <p className="px-3 py-6 text-center text-sm text-muted-foreground">{emptyMessage}</p>
      )}
    </div>
  )
}
