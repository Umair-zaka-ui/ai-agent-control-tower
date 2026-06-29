import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Gavel,
  ShieldAlert,
  UserPlus,
  XCircle,
} from 'lucide-react'

import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import type { ID } from '@/types'
import { apiErrorMessage } from '@/utils/error'
import {
  ApprovalSummary,
  AssignDialog,
  EscalateDialog,
  PayloadViewer,
  PolicyExplanation,
  RejectDialog,
  ReviewDialog,
  ReviewerComments,
  RiskBreakdownChart,
} from '../components'
import {
  useAddComment,
  useApproval,
  useApprove,
  useAssignReviewer,
  useEscalate,
  useOrgUsers,
  useReject,
} from '../hooks'
import type { EscalationTarget } from '../types'
import { canAssignApprovals, canEscalateApprovals, canReviewApprovals } from '../utils/permissions'

type DialogKind = 'approve' | 'reject' | 'escalate' | 'assign' | null

export function ReviewWorkbenchPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const notify = useNotifications()
  const { permissions } = useAuth()

  const canReview = canReviewApprovals(permissions)
  const canEscalate = canEscalateApprovals(permissions)
  const canAssign = canAssignApprovals(permissions)

  const [dialog, setDialog] = useState<DialogKind>(null)

  const { data: approval, isLoading, isError } = useApproval(id)
  const { data: users } = useOrgUsers()
  const approve = useApprove()
  const reject = useReject()
  const escalate = useEscalate()
  const assign = useAssignReviewer()
  const addComment = useAddComment()

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
  const nameFor = (userId: string | null) => users?.find((u) => u.id === userId)?.name ?? 'Reviewer'

  const close = () => setDialog(null)

  const onApprove = (comment: string) =>
    approve.mutate(
      { id: approval.id, input: { review_comment: comment } },
      {
        onSuccess: () => {
          notify.success('Action approved')
          navigate(ROUTES.APPROVALS)
        },
        onError: (e) => notify.error('Could not approve', apiErrorMessage(e)),
      },
    )

  const onReject = (reason: string) =>
    reject.mutate(
      { id: approval.id, input: { review_comment: reason } },
      {
        onSuccess: () => {
          notify.success('Action rejected')
          navigate(ROUTES.APPROVALS)
        },
        onError: (e) => notify.error('Could not reject', apiErrorMessage(e)),
      },
    )

  const onEscalate = (target: EscalationTarget, reason: string) =>
    escalate.mutate(
      { id: approval.id, input: { target, reason } },
      {
        onSuccess: () => {
          notify.success('Approval escalated')
          close()
        },
        onError: (e) => notify.error('Could not escalate', apiErrorMessage(e)),
      },
    )

  const onAssign = (userId: ID) =>
    assign.mutate(
      { id: approval.id, input: { user_id: userId } },
      {
        onSuccess: () => {
          notify.success('Reviewer assigned')
          close()
        },
        onError: (e) => notify.error('Could not assign', apiErrorMessage(e)),
      },
    )

  const onComment = (comment: string) =>
    addComment.mutate(
      { id: approval.id, comment },
      {
        onSuccess: () => notify.success('Comment added'),
        onError: (e) => notify.error('Could not add comment', apiErrorMessage(e)),
      },
    )

  return (
    <div className="space-y-6">
      <Link
        to={`${ROUTES.APPROVALS}/${approval.id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Approval details
      </Link>

      <div className="flex items-center gap-2">
        <Gavel className="h-5 w-5 text-primary" />
        <h1 className="text-2xl font-semibold tracking-tight">Review Workbench</h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main content */}
        <div className="space-y-6 lg:col-span-2">
          <ApprovalSummary approval={approval} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Request Payload</CardTitle>
            </CardHeader>
            <CardContent>
              <PayloadViewer payload={approval.action?.input_payload ?? {}} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Risk Analysis</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-primary">{approval.risk.recommendation}</p>
              <RiskBreakdownChart risk={approval.risk} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Policy Explanation</CardTitle>
            </CardHeader>
            <CardContent>
              <PolicyExplanation policy={approval.policy} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Reviewer Comments</CardTitle>
            </CardHeader>
            <CardContent>
              <ReviewerComments
                comments={approval.comments}
                authorName={nameFor}
                canComment={canReview}
                onAdd={onComment}
                submitting={addComment.isPending}
              />
            </CardContent>
          </Card>
        </div>

        {/* Decision panel */}
        <div className="lg:col-span-1">
          <Card className="lg:sticky lg:top-6">
            <CardHeader>
              <CardTitle className="text-base">Decision</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {!reviewable ? (
                <p className="text-sm text-muted-foreground">
                  This approval is already {approval.decision.toLowerCase()} and can no longer be actioned.
                </p>
              ) : !canReview ? (
                <p className="text-sm text-muted-foreground">
                  You have read-only access to this approval.
                </p>
              ) : (
                <>
                  <Button className="w-full justify-start" onClick={() => setDialog('approve')}>
                    <CheckCircle2 className="h-4 w-4" />
                    Approve
                  </Button>
                  <Button
                    variant="destructive"
                    className="w-full justify-start"
                    onClick={() => setDialog('reject')}
                  >
                    <XCircle className="h-4 w-4" />
                    Reject
                  </Button>
                  {canEscalate && (
                    <Button
                      variant="outline"
                      className="w-full justify-start"
                      onClick={() => setDialog('escalate')}
                    >
                      <ShieldAlert className="h-4 w-4" />
                      Escalate
                    </Button>
                  )}
                  {canAssign && (
                    <Button
                      variant="outline"
                      className="w-full justify-start"
                      onClick={() => setDialog('assign')}
                    >
                      <UserPlus className="h-4 w-4" />
                      {approval.assigned_to_user_id ? 'Reassign reviewer' : 'Assign reviewer'}
                    </Button>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <ReviewDialog
        open={dialog === 'approve'}
        onOpenChange={(o) => !o && close()}
        loading={approve.isPending}
        onConfirm={onApprove}
      />
      <RejectDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && close()}
        loading={reject.isPending}
        onConfirm={onReject}
      />
      <EscalateDialog
        open={dialog === 'escalate'}
        onOpenChange={(o) => !o && close()}
        loading={escalate.isPending}
        onConfirm={onEscalate}
      />
      <AssignDialog
        open={dialog === 'assign'}
        onOpenChange={(o) => !o && close()}
        users={users ?? []}
        currentAssigneeId={approval.assigned_to_user_id}
        loading={assign.isPending}
        onConfirm={onAssign}
      />
    </div>
  )
}
