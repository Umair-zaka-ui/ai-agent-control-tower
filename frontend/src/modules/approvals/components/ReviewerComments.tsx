import { useState } from 'react'
import { MessageSquare, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/utils/format'
import type { ApprovalComment } from '../types'

interface ReviewerCommentsProps {
  comments: ApprovalComment[]
  /** Name lookup for comment authors. */
  authorName?: (userId: string | null) => string
  canComment: boolean
  onAdd?: (comment: string) => void
  submitting?: boolean
}

/** Threaded reviewer comments with a composer (SRS §Reviewer Notes / Comments). */
export function ReviewerComments({
  comments,
  authorName,
  canComment,
  onAdd,
  submitting,
}: ReviewerCommentsProps) {
  const [draft, setDraft] = useState('')

  const handleSubmit = () => {
    const text = draft.trim()
    if (!text) return
    onAdd?.(text)
    setDraft('')
  }

  return (
    <div className="space-y-4">
      {comments.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <MessageSquare className="h-4 w-4" aria-hidden />
          No comments yet.
        </div>
      ) : (
        <ul className="space-y-3">
          {comments.map((c) => (
            <li key={c.id} className="rounded-md border border-border bg-muted/20 p-3">
              <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  {authorName ? authorName(c.user_id) : 'Reviewer'}
                </span>
                <span>{formatDateTime(c.created_at)}</span>
              </div>
              <p className="whitespace-pre-wrap text-sm">{c.comment}</p>
            </li>
          ))}
        </ul>
      )}

      {canComment && onAdd && (
        <div className="space-y-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Add a note… (Markdown supported)"
            rows={3}
            aria-label="Add a comment"
          />
          <div className="flex justify-end">
            <Button size="sm" onClick={handleSubmit} disabled={!draft.trim() || submitting}>
              <Send className="h-4 w-4" />
              {submitting ? 'Posting…' : 'Add comment'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
