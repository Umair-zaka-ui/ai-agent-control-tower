import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Bot, Download, Gavel, ShieldCheck } from 'lucide-react'

import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { formatDateTime, formatRelativeTime } from '@/utils/format'
import {
  ApprovalSummary,
  ApprovalTimeline,
  PayloadViewer,
  PolicyExplanation,
  RiskBreakdownChart,
  ReviewerComments,
} from '../components'
import { useApproval, useApprovalTimeline, useOrgUsers } from '../hooks'
import type { ApprovalDetail } from '../types'
import { exportApprovalJson } from '../utils/export'
import { humanizeToken } from '../utils/format'
import { canReviewApprovals } from '../utils/permissions'

export function ApprovalDetailsPage() {
  const { id } = useParams<{ id: string }>()
  const { permissions } = useAuth()
  const canReview = canReviewApprovals(permissions)

  const { data: approval, isLoading, isError } = useApproval(id)
  const { data: timeline } = useApprovalTimeline(id)
  const { data: users } = useOrgUsers()

  if (isLoading) return <FullPageSpinner />
  if (isError || !approval) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Approval not found or failed to load.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.APPROVALS}>Back to queue</Link>
        </Button>
      </div>
    )
  }

  const reviewable = approval.decision === 'PENDING' || approval.decision === 'ESCALATED'
  const nameFor = (userId: string | null) =>
    users?.find((u) => u.id === userId)?.name ?? 'Reviewer'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to={ROUTES.APPROVALS}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          All approvals
        </Link>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => exportApprovalJson(approval)}>
            <Download className="h-4 w-4" />
            Export JSON
          </Button>
          {canReview && reviewable && (
            <Button size="sm" asChild>
              <Link to={`${ROUTES.APPROVALS}/${approval.id}/review`}>
                <Gavel className="h-4 w-4" />
                Open workbench
              </Link>
            </Button>
          )}
        </div>
      </div>

      <ApprovalSummary approval={approval} />

      <div className="grid gap-6 lg:grid-cols-2">
        <AgentCard approval={approval} />
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-4 w-4 text-primary" />
              Policy Information
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PolicyExplanation policy={approval.policy} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Risk Assessment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            <span>
              <span className="text-muted-foreground">Overall Risk: </span>
              <span className="font-semibold">{approval.risk.score}/100</span>
            </span>
            <span>
              <span className="text-muted-foreground">Confidence: </span>
              <span className="font-semibold">{approval.risk.confidence}%</span>
            </span>
            <span className="text-primary">{approval.risk.recommendation}</span>
          </div>
          <RiskBreakdownChart risk={approval.risk} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Request Payload</CardTitle>
        </CardHeader>
        <CardContent>
          <PayloadViewer payload={approval.action?.input_payload ?? {}} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Decision History</CardTitle>
          </CardHeader>
          <CardContent>
            <ApprovalTimeline events={timeline ?? []} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Reviewer Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <ReviewerComments comments={approval.comments} authorName={nameFor} canComment={false} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function AgentCard({ approval }: { approval: ApprovalDetail }) {
  const agent = approval.agent
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="h-4 w-4 text-primary" />
          Agent Information
        </CardTitle>
      </CardHeader>
      <CardContent>
        {agent ? (
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field label="Agent" value={agent.name} />
            <Field label="Version" value={agent.version ?? '—'} />
            <Field label="Owner" value={agent.owner ?? '—'} />
            <Field label="Department" value={agent.department ?? '—'} />
            <Field label="Health" value={humanizeToken(agent.health)} />
            <Field label="Status" value={humanizeToken(agent.status)} />
            <Field
              label="Last Activity"
              value={agent.last_activity ? formatRelativeTime(agent.last_activity) : '—'}
            />
            <Field
              label="Action"
              value={`${humanizeToken(approval.action?.action)} · ${approval.action?.resource ?? ''}`}
            />
            <Field label="Requested" value={formatDateTime(approval.created_at)} />
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">Agent record unavailable.</p>
        )}
      </CardContent>
    </Card>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  )
}
