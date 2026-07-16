// Phase 4.3.6 frontend tests (§37) — decision→UI mapping, obligation dialogs,
// MFA challenge, approval dialog, error boundary and the provider wiring.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { useContext } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ permissions: ['agent.view', 'audit.*'] }),
}))

const { AuthorizationProvider, AuthorizationUiContext } = await import(
  '../AuthorizationProvider'
)
const { AuthorizationErrorBoundary } = await import('../AuthorizationErrorBoundary')
const { PermissionGuard } = await import('../PermissionGuard')
const { decisionToUi, maskFields } = await import('../decisionUi')
const { ObligationDialog } = await import('../ObligationDialog')
import type { AuthorizationDecision } from '../types'

function decision(partial: Partial<AuthorizationDecision>): AuthorizationDecision {
  return {
    allowed: false, decision: 'DENY', reason: 'nope', permission: 'x', ...partial,
  }
}

// --------------------------------------------------------------------------- #
// §33 — decision → UI behavior
// --------------------------------------------------------------------------- #
describe('decisionToUi', () => {
  it('maps every gateway decision onto the §33 behavior', () => {
    expect(decisionToUi(decision({ decision: 'ALLOW', allowed: true }))).toEqual(
      { kind: 'continue' })
    expect(decisionToUi(decision({ decision: 'DENY', reason: 'blocked' }))).toEqual(
      { kind: 'denied', reason: 'blocked' })
    expect(decisionToUi(decision({
      decision: 'REQUIRE_APPROVAL', reason: 'needs review',
      obligations: [{ type: 'CREATE_APPROVAL', priority: 'CRITICAL' }],
    }))).toMatchObject({ kind: 'approval', obligation: { priority: 'CRITICAL' } })
    expect(decisionToUi(decision({ decision: 'REQUIRE_MFA', reason: 'mfa' })))
      .toEqual({ kind: 'mfa', reason: 'mfa' })
    expect(decisionToUi(decision({ decision: 'REQUIRE_JUSTIFICATION', reason: 'why' })))
      .toEqual({ kind: 'justification', reason: 'why' })
    expect(decisionToUi(decision({
      decision: 'MASK_FIELDS', allowed: true,
      obligations: [{ type: 'MASK_FIELDS', fields: ['ssn'] }],
    }))).toEqual({ kind: 'masked', fields: ['ssn'] })
    expect(decisionToUi(decision({
      decision: 'LIMIT_ACTION', allowed: true,
      obligations: [{ type: 'LIMIT_ACTION', limits: { maximum_export_rows: 100 } }],
    }))).toEqual({ kind: 'limited', limits: { maximum_export_rows: 100 } })
  })
})

describe('maskFields', () => {
  it('redacts fields recursively without touching the original', () => {
    const data = { ssn: '123', nested: { ssn: '456', keep: 1 }, rows: [{ ssn: '789' }] }
    const masked = maskFields(data, ['ssn'])
    expect(masked.ssn).toBe('***')
    expect(masked.nested.ssn).toBe('***')
    expect(masked.rows[0].ssn).toBe('***')
    expect(masked.nested.keep).toBe(1)
    expect(data.ssn).toBe('123')
  })
})

// --------------------------------------------------------------------------- #
// §32 — provider routes decisions and errors to dialogs
// --------------------------------------------------------------------------- #
function Trigger() {
  const ctx = useContext(AuthorizationUiContext)!
  return (
    <div>
      <button onClick={() => ctx.handleDecision(decision({
        decision: 'REQUIRE_APPROVAL', reason: 'High-risk action needs review',
        obligations: [{ type: 'CREATE_APPROVAL', priority: 'CRITICAL' }],
      }))}>
        approval
      </button>
      <button onClick={() => ctx.handleAuthorizationError({
        code: 'MFA_REQUIRED', message: 'Stronger authentication is required.',
      })}>
        mfa
      </button>
      <button onClick={() => ctx.handleAuthorizationError({
        code: 'JUSTIFICATION_REQUIRED', message: 'A justification is required.',
      })}>
        justify
      </button>
    </div>
  )
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthorizationProvider>
        <Trigger />
      </AuthorizationProvider>
    </MemoryRouter>,
  )
}

describe('AuthorizationProvider', () => {
  it('opens the approval dialog for REQUIRE_APPROVAL decisions', async () => {
    renderProvider()
    await userEvent.click(screen.getByText('approval'))
    await waitFor(() =>
      expect(screen.getByText('Human approval required')).toBeInTheDocument())
    expect(screen.getByText(/High-risk action needs review/)).toBeInTheDocument()
    expect(screen.getByText(/CRITICAL/)).toBeInTheDocument()
    expect(screen.getByText('Open approval queue')).toBeInTheDocument()
  })

  it('opens the MFA challenge for MFA_REQUIRED errors', async () => {
    renderProvider()
    await userEvent.click(screen.getByText('mfa'))
    await waitFor(() =>
      expect(screen.getByText('Stronger authentication required')).toBeInTheDocument())
  })

  it('collects a justification when the challenge demands one', async () => {
    renderProvider()
    await userEvent.click(screen.getByText('justify'))
    await waitFor(() =>
      expect(screen.getByText('Justification required')).toBeInTheDocument())
    expect(screen.getByLabelText('Justification')).toBeInTheDocument()
  })

  it('returns false for non-authorization errors so callers keep handling them', async () => {
    let handled: boolean | null = null
    function Probe() {
      const ctx = useContext(AuthorizationUiContext)!
      return (
        <button onClick={() => { handled = ctx.handleAuthorizationError({
          code: 'VALIDATION_ERROR', message: 'bad input' }) }}>
          probe
        </button>
      )
    }
    render(
      <MemoryRouter>
        <AuthorizationProvider><Probe /></AuthorizationProvider>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('probe'))
    expect(handled).toBe(false)
  })
})

// --------------------------------------------------------------------------- #
// §32 — obligation dialog submits a justification
// --------------------------------------------------------------------------- #
describe('ObligationDialog', () => {
  it('disables submit until a justification is entered, then hands it back', async () => {
    const onJustify = vi.fn()
    render(
      <ObligationDialog
        behavior={{ kind: 'justification', reason: 'Policy demands a reason' }}
        open
        onClose={() => {}}
        onJustify={onJustify}
      />,
    )
    const submit = screen.getByText('Submit justification')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Justification'), 'quarterly export')
    expect(submit).toBeEnabled()
    await userEvent.click(submit)
    expect(onJustify).toHaveBeenCalledWith('quarterly export')
  })
})

// --------------------------------------------------------------------------- #
// §32 — error boundary
// --------------------------------------------------------------------------- #
describe('AuthorizationErrorBoundary', () => {
  it('renders the access-denied state for authorization errors', () => {
    function Boom(): never {
      throw { code: 'ABAC_DENIED', message: 'Access denied by policy.', status: 403 }
    }
    render(
      <AuthorizationErrorBoundary>
        <Boom />
      </AuthorizationErrorBoundary>,
    )
    expect(screen.getByText('Access denied')).toBeInTheDocument()
    expect(screen.getByText('Access denied by policy.')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- #
// §32 — PermissionGuard (wildcard-aware, redirects on missing permission)
// --------------------------------------------------------------------------- #
describe('PermissionGuard', () => {
  it('renders children when the permission is held (wildcard-aware)', () => {
    render(
      <MemoryRouter>
        <AuthorizationProvider>
          <PermissionGuard permission="audit.view">
            <div>secret audit page</div>
          </PermissionGuard>
        </AuthorizationProvider>
      </MemoryRouter>,
    )
    expect(screen.getByText('secret audit page')).toBeInTheDocument()
  })

  it('redirects when the permission is missing', () => {
    render(
      <MemoryRouter>
        <AuthorizationProvider>
          <PermissionGuard permission="policy.publish">
            <div>forbidden page</div>
          </PermissionGuard>
        </AuthorizationProvider>
      </MemoryRouter>,
    )
    expect(screen.queryByText('forbidden page')).not.toBeInTheDocument()
  })
})
