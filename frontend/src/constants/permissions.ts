/**
 * Backend RBAC permission codes the UI gates on.
 *
 * The backend is the source of truth — every one of these is re-checked
 * server-side. Gating here only hides controls the user could not use anyway;
 * it is never the security boundary.
 */
export const PERMISSIONS = {
  /** View any user's sessions and devices in the organization (SRS §17). */
  SESSION_VIEW: 'session.view',
  /** Force-logout another user's sessions (SRS §17). */
  SESSION_REVOKE: 'session.revoke',
  /** List organization members (needed for the admin user picker). */
  USER_VIEW: 'user.view',
  /** View pending invitations (4.2.2.3.1 §15). */
  INVITATION_VIEW: 'invitation.view',
  /** Create, resend and cancel invitations. */
  INVITATION_MANAGE: 'invitation.manage',
  /** Reset another user's password / issue temporary credentials (4.2.2.3.2 §16). */
  CREDENTIAL_RESET: 'credential.reset',
  /** View the org password/credential dashboard (4.2.2.3.2 §17). */
  CREDENTIAL_DASHBOARD: 'credential.dashboard',
  /** View password-reset & recovery events (4.2.2.3.3 §18). */
  RECOVERY_VIEW: 'recovery.view',
  /** View/manage account protection: locks, blocked IPs, rules (4.2.2.3.4 §20). */
  SECURITY_PROTECTION: 'security.protection',
  /** View roles, permissions, groups and assignments (Phase 4.3.1 §20). */
  ROLE_VIEW: 'role.view',
  /** Create/edit/archive/delete roles, permissions and hierarchy (4.3.1 §20). */
  ROLE_MANAGE: 'role.manage',
  /** Assign and remove roles, including scoped assignments (4.3.1 §20). */
  ROLE_ASSIGN: 'role.assign',
  /** View the organization hierarchy, ownership and delegations (4.3.3 §15). */
  ORGANIZATION_VIEW: 'organization.view',
  /** Manage business units, departments, teams, projects, ownership, delegation. */
  ORGANIZATION_MANAGE: 'organization.manage',
  /** View the resource registry, ACLs, shares and delegations (4.3.4 §16). */
  RESOURCE_VIEW: 'resource.view',
  /** Administer any resource: ACLs, shares, delegations, transfers, policy (4.3.4 §16). */
  RESOURCE_MANAGE: 'resource.manage',
  /** View ABAC policies, versions and the attribute catalog (4.3.5 §37). */
  ABAC_VIEW: 'authorization.abac.view',
  /** Run the ABAC policy simulator (4.3.5 §37). */
  ABAC_SIMULATE: 'authorization.abac.simulate',
  /** View ABAC evaluations and internal explanations (4.3.5 §37). */
  ABAC_AUDIT: 'authorization.abac.audit',
  /** Administration portal (4.3.7 §21). */
  ADMIN_DASHBOARD_VIEW: 'admin.dashboard.view',
  ADMIN_AUDIT_VIEW: 'admin.audit.view',
  ADMIN_ANALYTICS_VIEW: 'admin.analytics.view',
  ADMIN_REVIEWS_MANAGE: 'admin.reviews.manage',
  /** Identity Governance & Administration (Phase 4.3.8 §18). */
  GOVERNANCE_DASHBOARD_VIEW: 'governance.dashboard.view',
  GOVERNANCE_CERTIFICATION_MANAGE: 'governance.certification.manage',
  GOVERNANCE_SOD_MANAGE: 'governance.sod.manage',
  GOVERNANCE_SOD_VIEW: 'governance.sod.view',
  GOVERNANCE_TOXIC_MANAGE: 'governance.toxic.manage',
  GOVERNANCE_PRIVILEGED_MANAGE: 'governance.privileged.manage',
  GOVERNANCE_ORPHANED_MANAGE: 'governance.orphaned.manage',
  GOVERNANCE_FINDINGS_MANAGE: 'governance.findings.manage',
  GOVERNANCE_REMEDIATION_MANAGE: 'governance.remediation.manage',
  GOVERNANCE_COMPLIANCE_VIEW: 'governance.compliance.view',
  GOVERNANCE_ANALYTICS_VIEW: 'governance.analytics.view',
  /** Agent Runtime & Lifecycle Management (Phase 5.0 §67). */
  RUNTIME_AGENT_VIEW: 'runtime.agent.view',
  RUNTIME_AGENT_CREATE: 'runtime.agent.create',
  RUNTIME_AGENT_UPDATE: 'runtime.agent.update',
  RUNTIME_AGENT_DELETE: 'runtime.agent.delete',
  RUNTIME_AGENT_VALIDATE: 'runtime.agent.validate',
  RUNTIME_AGENT_APPROVE: 'runtime.agent.approve',
  RUNTIME_AGENT_ACTIVATE: 'runtime.agent.activate',
  RUNTIME_AGENT_SUSPEND: 'runtime.agent.suspend',
  RUNTIME_AGENT_RETIRE: 'runtime.agent.retire',
  RUNTIME_VERSION_VIEW: 'runtime.version.view',
  RUNTIME_VERSION_CREATE: 'runtime.version.create',
  RUNTIME_VERSION_PUBLISH: 'runtime.version.publish',
  RUNTIME_VERSION_DEPRECATE: 'runtime.version.deprecate',
  RUNTIME_VERSION_REVOKE: 'runtime.version.revoke',
  RUNTIME_DEPLOYMENT_VIEW: 'runtime.deployment.view',
  RUNTIME_DEPLOYMENT_CREATE: 'runtime.deployment.create',
  RUNTIME_DEPLOYMENT_DEPLOY: 'runtime.deployment.deploy',
  RUNTIME_DEPLOYMENT_ROLLBACK: 'runtime.deployment.rollback',
  RUNTIME_EXECUTION_VIEW: 'runtime.execution.view',
  RUNTIME_EXECUTION_CREATE: 'runtime.execution.create',
  RUNTIME_EXECUTION_CANCEL: 'runtime.execution.cancel',
  RUNTIME_EXECUTION_RETRY: 'runtime.execution.retry',
  RUNTIME_CAPABILITY_MANAGE: 'runtime.capability.manage',
  RUNTIME_TOOL_MANAGE: 'runtime.tool.manage',
  RUNTIME_TOOL_ASSIGN: 'runtime.tool.assign',
  RUNTIME_HEALTH_VIEW: 'runtime.health.view',
  RUNTIME_TELEMETRY_VIEW: 'runtime.telemetry.view',
  RUNTIME_COST_VIEW: 'runtime.cost.view',
  RUNTIME_APPROVAL_REVIEW: 'runtime.approval.review',
  RUNTIME_KILL_SWITCH: 'runtime.kill_switch.execute',
  /** Enterprise Agent Registry (Phase 5.1 §57). */
  RUNTIME_AGENT_REGISTER: 'runtime.agent.register',
  RUNTIME_AGENT_SUBMIT: 'runtime.agent.submit',
  RUNTIME_AGENT_REJECT: 'runtime.agent.reject',
  RUNTIME_AGENT_RESUME: 'runtime.agent.resume',
  RUNTIME_AGENT_DEPRECATE: 'runtime.agent.deprecate',
  RUNTIME_AGENT_ARCHIVE: 'runtime.agent.archive',
  RUNTIME_AGENT_RESTORE: 'runtime.agent.restore',
  RUNTIME_AGENT_IDENTITY_ASSOCIATE: 'runtime.agent.identity.associate',
  RUNTIME_AGENT_IDENTITY_CREATE: 'runtime.agent.identity.create',
  RUNTIME_AGENT_IDENTITY_REPLACE: 'runtime.agent.identity.replace',
  RUNTIME_AGENT_OWNERSHIP_VIEW: 'runtime.agent.ownership.view',
  RUNTIME_AGENT_OWNERSHIP_TRANSFER: 'runtime.agent.ownership.transfer',
  RUNTIME_AGENT_VALIDATION_VIEW: 'runtime.agent.validation.view',
  RUNTIME_AGENT_DUPLICATE_REVIEW: 'runtime.agent.duplicate.review',
  RUNTIME_AGENT_IMPORT: 'runtime.agent.import',
  RUNTIME_AGENT_EXPORT: 'runtime.agent.export',
  RUNTIME_AGENT_AUDIT_VIEW: 'runtime.agent.audit.view',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]
