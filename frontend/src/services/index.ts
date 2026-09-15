export { apiClient } from './apiClient'
export { authService } from './authService'
export { credentialService, adminCredentialService } from './credentialService'
export { recoveryService, adminRecoveryService } from './recoveryService'
export { protectionService } from './protectionService'
export { adminService } from './adminService'
export { governanceService } from './governanceService'
export { runtimeService } from './runtimeService'
export { operationsService } from './operationsService'
export { observabilityService } from './observabilityService'
export { commandCenterService } from './commandCenterService'
export { assuranceService } from './assuranceService'
export type { AgentRegistrationPayload, AgentSearchFilters } from './runtimeService'
// Phase 4.9's TraceDetailPage imports this type from the barrel, but the barrel
// only ever re-exported the *value* `observabilityService` — so the build broke
// while `vitest` stayed green, because vitest does not typecheck. Re-exported
// here alongside the other service types rather than rewriting the import, so
// the barrel stays the single place a consumer reaches for services.
export type { TraceContentResponse } from './observabilityService'
export { authorizationService } from './authorizationService'
export { hierarchyService } from './hierarchyService'
export { approvalService } from './approvalService'
export { auditService } from './auditService'
export { dashboardService } from './dashboardService'
export { systemService } from './systemService'
export { userService } from './userService'
export { resourceAuthzService } from './resourceAuthzService'
export { abacService } from './abacService'
