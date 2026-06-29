/**
 * Approval UI permissions (SRS §Security / Role-Based UI). The backend RBAC
 * layer is the authority; these only decide which actions are shown.
 *
 * Permission codes come from the RBAC catalog:
 * - approval.review   → approve / reject / comment
 * - approval.escalate → escalate
 * - approval.assign   → assign / reassign reviewer
 */
export function canReviewApprovals(permissions: string[]): boolean {
  return permissions.includes('approval.review')
}

export function canEscalateApprovals(permissions: string[]): boolean {
  return permissions.includes('approval.escalate')
}

export function canAssignApprovals(permissions: string[]): boolean {
  return permissions.includes('approval.assign')
}
