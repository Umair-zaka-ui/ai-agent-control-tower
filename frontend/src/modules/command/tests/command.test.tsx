// Phase 5.8 frontend tests — the Enterprise Agent Command Center.
//
// The sharpest tests are the truthful-affordance set: that an OBSERVED or
// DISCOVERED agent shows NO containment affordance, that a GATEWAY_ENFORCED
// agent is never labelled "governed", that a NATIVE agent shows full
// containment, and — the structural one — that the frontend derives none of
// this itself but reads it from server-sent fields. After that: shadow shows
// WHY, NOT_MEASURABLE renders honestly, "you cannot see this" is distinct from
// zero, dangerous actions are confirmation-gated, and a failed read shows a
// truthful error instead of an empty state.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const MODULE_DIR = resolve(process.cwd(), 'src/modules/command')

const cc = {
  estate: vi.fn(),
  inventory: vi.fn(),
  agent: vi.fn(),
  controlState: vi.fn(),
  claim: vi.fn(),
  transitionControlState: vi.fn(),
  discoverySources: vi.fn(),
  discoveryFindings: vi.fn(),
  edges: vi.fn(),
  dependencies: vi.fn(),
  unapprovedMcp: vi.fn(),
  mcpServers: vi.fn(),
  postureSummary: vi.fn(),
  postureFindings: vi.fn(),
  agentShadow: vi.fn(),
  shadowAgents: vi.fn(),
  resolvePostureFinding: vi.fn(),
  suppressPostureFinding: vi.fn(),
  threatFindings: vi.fn(),
  containmentActions: vi.fn(),
  resolveThreatFinding: vi.fn(),
  executeContainment: vi.fn(),
  enforcementMode: vi.fn(),
  setEnforcementMode: vi.fn(),
  modes: vi.fn(),
  grants: vi.fn(),
  revokeGrant: vi.fn(),
  gatewayCalls: vi.fn(),
}
const assurance = {
  controls: vi.fn(), frameworks: vi.fn(), frameworkReport: vi.fn(),
  evaluations: vi.fn(), evaluateTenant: vi.fn(), evaluateAgent: vi.fn(),
  recordException: vi.fn(), exportBundle: vi.fn(),
}
vi.mock('@/services', () => ({
  commandCenterService: cc, assuranceService: assurance,
  observabilityService: {}, operationsService: {}, runtimeService: {},
}))
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
  Toaster: () => null,
}))

let permissions: string[] = []
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'o@x.com' },
    permissions,
  }),
}))

let routeParams: Record<string, string> = { agentId: 'agent-1' }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => routeParams }
})

const { EstateOverviewPage } = await import('../EstateOverviewPage')
const { AgentInventoryPage } = await import('../AgentInventoryPage')
const { AgentDrilldownPage } = await import('../AgentDrilldownPage')
const { ShadowAgentsPage } = await import('../ShadowAgentsPage')
const { PostureFindingsPage } = await import('../PostureFindingsPage')
const { ThreatsPage } = await import('../ThreatsPage')
const { ExternalPlatformsPage } = await import('../ExternalPlatformsPage')
const { CostExposurePage } = await import('../CostExposurePage')
const { AssurancePage } = await import('../AssurancePage')
const { affordancesFor } = await import('../affordances')
const { COMMAND_VIEWS, viewsForPersona } = await import('../personas')
const { PermissionProvider } = await import('@/authorization')

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PermissionProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </PermissionProvider>
    </QueryClientProvider>,
  )
}

// --- server-shaped fixtures -------------------------------------------------
const NATIVE_SIGNAL = {
  enforcement_mode: 'NATIVE_ENFORCED',
  enforcement_display: 'ACT runs this agent and enforces it in full.',
  enforcement_limits: 'None beyond the platform’s own.',
  reaches_boundary_calls: true,
  reaches_agent_execution: true,
}
const GATEWAY_SIGNAL = {
  enforcement_mode: 'GATEWAY_ENFORCED',
  enforcement_display:
    "ACT authorizes this agent's capability calls that route through ACT's gateway.",
  enforcement_limits:
    "ACT's reach is the boundary only. ACT does not run this agent and cannot stop it.",
  reaches_boundary_calls: true,
  reaches_agent_execution: false,
}
const OBSERVED_SIGNAL = {
  enforcement_mode: 'OBSERVED',
  enforcement_display: 'ACT observes this agent.',
  enforcement_limits:
    'ACT performs no enforcement of any kind on this agent. It ingests events as evidence '
    + 'and cannot deny, stop or constrain anything it does.',
  reaches_boundary_calls: false,
  reaches_agent_execution: false,
}

function row(over: Record<string, unknown> = {}) {
  return {
    id: 'agent-1', name: 'Copilot Studio Bot', control_state: 'DISCOVERED',
    origin_category: 'EXTERNAL', origin_provider: 'MICROSOFT', criticality: 'MEDIUM',
    owner_id: null, lifecycle_status: 'DRAFT', last_observed_at: null,
    ...OBSERVED_SIGNAL, shadow: false, shadow_conditions: [], shadow_visible: true,
    ...over,
  }
}

function estate(over: Record<string, unknown> = {}) {
  const section = (data: unknown) => ({ visible: true, permission: 'x', data })
  return {
    generated_at: '2026-09-15T00:00:00Z',
    agents: {
      total: 10, by_control_state: { DISCOVERED: 6, GOVERNED: 4 },
      by_origin_category: { EXTERNAL: 6, NATIVE: 4 },
      by_enforcement_mode: { OBSERVED: 6, NATIVE_ENFORCED: 4 },
      governed: 4, ungoverned: 6, unowned: 3, critical: 1, dormant: 2, dormant_days: 30,
    },
    posture: section({ score: 42, ruleset_version: '1' }),
    shadow: section({ count: 2, shadow_rule_ids: ['unmanaged_external_agent'] }),
    threats: section({
      open_findings: 1, open_by_severity: { CRITICAL: 1 }, containment_window_hours: 24,
      containment_by_status: { REFUSED: 1 }, containment_refused: 1,
    }),
    external: section({
      active_grants: 1, window_hours: 24,
      boundary_calls_by_outcome: { ALLOWED: 3, DENIED: 1 }, boundary_calls_denied: 1,
    }),
    graph: section({ mcp_servers: 2, mcp_by_trust_status: { UNAPPROVED: 1 }, active_edges: 5 }),
    cost: section({
      enabled_budgets: 1, window_hours: 24, boundary_calls_not_measurable: 4,
      note: 'Boundary calls ACT cannot price are counted, not estimated.',
    }),
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  permissions = [
    'agent.view', 'posture.view', 'posture.manage', 'threat.view', 'containment.execute',
    'external_governance.view', 'graph.view', 'runtime.cost.view',
  ]
  routeParams = { agentId: 'agent-1' }
  cc.estate.mockResolvedValue(estate())
  cc.inventory.mockResolvedValue({ total: 1, page: 1, page_size: 50, items: [row()] })
  cc.agent.mockResolvedValue({ id: 'agent-1', name: 'Copilot Studio Bot' })
  cc.enforcementMode.mockResolvedValue({
    enforcement_mode: 'OBSERVED', control_state: 'DISCOVERED',
    display: OBSERVED_SIGNAL.enforcement_display, limits: OBSERVED_SIGNAL.enforcement_limits,
    reaches_boundary_calls: false, reaches_agent_execution: false,
    evaluates_policy: false, derived_from_control_state: false,
  })
  cc.agentShadow.mockResolvedValue({ agent_id: 'agent-1', shadow: false, conditions: [] })
  cc.postureFindings.mockResolvedValue([])
  cc.dependencies.mockResolvedValue({ edges: [] })
  cc.shadowAgents.mockResolvedValue({ shadow_rule_ids: [], count: 0, agents: [] })
  cc.threatFindings.mockResolvedValue([])
  cc.containmentActions.mockResolvedValue([])
  cc.modes.mockResolvedValue([])
  cc.gatewayCalls.mockResolvedValue([])
  cc.mcpServers.mockResolvedValue([])
  cc.edges.mockResolvedValue([])
  cc.unapprovedMcp.mockResolvedValue({})
  assurance.frameworks.mockResolvedValue([])
  assurance.evaluations.mockResolvedValue([])
  assurance.frameworkReport.mockResolvedValue(null)
})

// --------------------------------------------------------------------------- //
// AC-02 — the views render from existing/new read endpoints
// --------------------------------------------------------------------------- //
describe('AC-02 estate views', () => {
  it('renders truthful estate counts, including what ACT does NOT govern', async () => {
    wrap(<EstateOverviewPage />)
    await waitFor(() => expect(screen.getByText('ACT does not govern')).toBeInTheDocument())
    expect(screen.getByText('ACT governs')).toBeInTheDocument()
    // The ungoverned count is stated on its own tile, not folded into a
    // coverage number — named precisely so this cannot pass by accident.
    expect(screen.getByTestId('tile-ACT does not govern')).toHaveTextContent('6')
    expect(screen.getByTestId('tile-ACT governs')).toHaveTextContent('4')
  })

  it('renders the inventory from the aggregation endpoint', async () => {
    wrap(<AgentInventoryPage />)
    await waitFor(() => expect(screen.getByText('Copilot Studio Bot')).toBeInTheDocument())
    expect(cc.inventory).toHaveBeenCalled()
  })
})

// --------------------------------------------------------------------------- //
// AC-03 — per-persona assembly
// --------------------------------------------------------------------------- //
describe('AC-03 personas', () => {
  it('narrows views per persona rather than showing one dashboard to everyone', () => {
    const finops = viewsForPersona('finops').map((v) => v.key)
    const security = viewsForPersona('security').map((v) => v.key)
    expect(finops).toContain('cost')
    expect(finops).not.toContain('threats')
    expect(security).toContain('threats')
    expect(viewsForPersona('all')).toHaveLength(COMMAND_VIEWS.length)
  })
})

// --------------------------------------------------------------------------- //
// AC-04 — truthful affordances (the headline)
// --------------------------------------------------------------------------- //
describe('AC-04 truthful affordances', () => {
  it('offers containment ONLY where the server says ACT reaches the agent', () => {
    expect(affordancesFor(NATIVE_SIGNAL).canContainAgent).toBe(true)
    expect(affordancesFor(GATEWAY_SIGNAL).canContainAgent).toBe(false)
    expect(affordancesFor(OBSERVED_SIGNAL).canContainAgent).toBe(false)
  })

  it('never labels a GATEWAY_ENFORCED agent "governed"', () => {
    const a = affordancesFor(GATEWAY_SIGNAL)
    expect(a.label.toLowerCase()).not.toContain('govern this agent')
    expect(a.label).toContain('authorizes')
    expect(a.label).toContain('gateway')
    // and the bound travels with the claim
    expect(a.limits).toContain('boundary only')
  })

  it('shows NO containment affordance for an OBSERVED agent, and says why', async () => {
    wrap(<AgentDrilldownPage />)
    await waitFor(() => expect(screen.getByTestId('containment-unavailable')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /suspend/i })).not.toBeInTheDocument()
    expect(screen.getByTestId('containment-unavailable')).toHaveTextContent(/no enforcement/i)
  })

  it('shows full containment for a NATIVE agent', async () => {
    cc.enforcementMode.mockResolvedValue({
      enforcement_mode: 'NATIVE_ENFORCED', control_state: 'GOVERNED',
      display: NATIVE_SIGNAL.enforcement_display, limits: NATIVE_SIGNAL.enforcement_limits,
      reaches_boundary_calls: true, reaches_agent_execution: true,
      evaluates_policy: true, derived_from_control_state: true,
    })
    wrap(<AgentDrilldownPage />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suspend agent/i })).toBeInTheDocument())
    expect(screen.queryByTestId('containment-unavailable')).not.toBeInTheDocument()
  })

  it('renders the inventory row label from the server sentence, not a local map', async () => {
    cc.inventory.mockResolvedValue({
      total: 1, page: 1, page_size: 50,
      items: [row({ ...GATEWAY_SIGNAL, control_state: 'REGISTERED' })],
    })
    wrap(<AgentInventoryPage />)
    await waitFor(() =>
      expect(screen.getByText(GATEWAY_SIGNAL.enforcement_display)).toBeInTheDocument())
    expect(screen.queryByText(/^Governed$/)).not.toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// AC-05 — shadow shows why; NOT_MEASURABLE and INSUFFICIENT render honestly
// --------------------------------------------------------------------------- //
describe('AC-05 truthful state', () => {
  it('shows WHY an agent is shadow, not a bare badge', async () => {
    cc.shadowAgents.mockResolvedValue({
      shadow_rule_ids: ['unmanaged_external_agent'],
      count: 1,
      agents: [{
        agent: { id: 'agent-1', name: 'Copilot Studio Bot', control_state: 'DISCOVERED' },
        conditions: [{
          rule_id: 'unmanaged_external_agent', severity: 'HIGH', finding_id: 'f1',
          reason: 'External agent with no owner and no governance policy.',
        }],
      }],
    })
    wrap(<ShadowAgentsPage />)
    await waitFor(() =>
      expect(screen.getByText(/External agent with no owner/)).toBeInTheDocument())
    expect(screen.getByText('unmanaged_external_agent')).toBeInTheDocument()
  })

  it('renders unmeasurable cost as unmeasurable, never as zero', async () => {
    wrap(<CostExposurePage />)
    await waitFor(() => expect(screen.getByText('Not measurable')).toBeInTheDocument())
    expect(screen.getByText(/could not price/i)).toBeInTheDocument()
    expect(screen.getByText(/counted, not estimated/i)).toBeInTheDocument()
  })

  it('shows INSUFFICIENT_DATA as itself rather than as a pass', async () => {
    cc.postureFindings.mockResolvedValue([{
      id: 'f1', rule_id: 'dangerous_dependency', severity: 'INFO', status: 'OPEN',
      outcome: 'INSUFFICIENT_DATA', reason: 'No dependency edges recorded; absence is not safety.',
      remediation: null, subject_id: 'agent-1', subject_type: 'AGENT',
    }])
    wrap(<PostureFindingsPage />)
    await waitFor(() => expect(screen.getByText(/insufficient data/i)).toBeInTheDocument())
    expect(screen.getByText(/absence is not safety/)).toBeInTheDocument()
  })

  it('shows a REFUSED containment as refused, with the reason', async () => {
    cc.containmentActions.mockResolvedValue([{
      id: 'c1', action_type: 'SUSPEND_AGENT', authority: 'KILL_SWITCH', status: 'REFUSED',
      agent_id: 'agent-1', control_state_at_time: 'DISCOVERED',
      refusal_reason: 'ACT has no enforcement authority over this agent.',
    }])
    wrap(<ThreatsPage />)
    await waitFor(() => expect(screen.getByText(/Refused —/)).toBeInTheDocument())
    expect(screen.getByText(/no enforcement authority/)).toBeInTheDocument()
  })

  it('distinguishes "you cannot see this" from a count of zero', async () => {
    cc.estate.mockResolvedValue(estate({
      shadow: { visible: false, permission: 'posture.view', data: null },
    }))
    wrap(<EstateOverviewPage />)
    await waitFor(() =>
      expect(screen.getByText(/not a count of zero/i)).toBeInTheDocument())
  })
})

// --------------------------------------------------------------------------- //
// AC-06 — guarded actions dispatch to the existing endpoints
// --------------------------------------------------------------------------- //
describe('AC-06 guarded actions', () => {
  it('confirmation-gates containment and dispatches to the 5.6 endpoint', async () => {
    cc.enforcementMode.mockResolvedValue({
      enforcement_mode: 'NATIVE_ENFORCED', control_state: 'GOVERNED',
      display: NATIVE_SIGNAL.enforcement_display, limits: NATIVE_SIGNAL.enforcement_limits,
      reaches_boundary_calls: true, reaches_agent_execution: true,
      evaluates_policy: true, derived_from_control_state: true,
    })
    cc.executeContainment.mockResolvedValue({})
    const user = userEvent.setup()
    wrap(<AgentDrilldownPage />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suspend agent/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /suspend agent/i }))

    // The dialog is raised and the action has NOT fired yet.
    expect(await screen.findByText(/genuinely stops it/i)).toBeInTheDocument()
    expect(cc.executeContainment).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText(/type .* to confirm/i), 'Copilot Studio Bot')
    await user.type(screen.getByLabelText(/why is this being contained/i), 'incident 42')
    await user.click(screen.getByRole('button', { name: 'Suspend agent' }))

    await waitFor(() => expect(cc.executeContainment).toHaveBeenCalledWith(
      'agent-1', expect.objectContaining({ action_type: 'SUSPEND_AGENT', confirm: true })))
  })

  it('confirmation-gates suppression and calls the 5.5 endpoint', async () => {
    cc.postureFindings.mockResolvedValue([{
      id: 'f1', rule_id: 'unowned_with_production_access', severity: 'HIGH', status: 'OPEN',
      outcome: 'FINDING', reason: 'No accountable owner.', remediation: 'Assign an owner.',
      subject_id: 'agent-1', subject_type: 'AGENT',
    }])
    cc.suppressPostureFinding.mockResolvedValue({})
    const user = userEvent.setup()
    wrap(<PostureFindingsPage />)

    await user.click(await screen.findByRole('button', { name: 'Suppress' }))
    expect(await screen.findByText(/is not resolution/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/why is this being suppressed/i), 'accepted risk')
    await user.click(screen.getByRole('button', { name: 'Suppress' }))

    await waitFor(() => expect(cc.suppressPostureFinding).toHaveBeenCalledWith(
      'f1', expect.objectContaining({ reason: 'accepted risk' })))
  })
})

// --------------------------------------------------------------------------- //
// AC-07 — the UI reflects permissions; the server remains the authority
// --------------------------------------------------------------------------- //
describe('AC-07 server-authoritative', () => {
  it('does not offer containment without containment.execute, even for a NATIVE agent', async () => {
    permissions = ['agent.view', 'external_governance.view']
    cc.enforcementMode.mockResolvedValue({
      enforcement_mode: 'NATIVE_ENFORCED', control_state: 'GOVERNED',
      display: NATIVE_SIGNAL.enforcement_display, limits: NATIVE_SIGNAL.enforcement_limits,
      reaches_boundary_calls: true, reaches_agent_execution: true,
      evaluates_policy: true, derived_from_control_state: true,
    })
    wrap(<AgentDrilldownPage />)
    await waitFor(() => expect(screen.getByText(/What ACT can do/)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /suspend agent/i })).not.toBeInTheDocument()
  })

  it('treats the permission list as UX only — every view names a real permission', () => {
    for (const view of COMMAND_VIEWS) {
      expect(view.permission).toMatch(/^[a-z_]+(\.[a-z_]+)+$/)
    }
  })
})

// --------------------------------------------------------------------------- //
// AC-08 — no business logic in React (structural)
// --------------------------------------------------------------------------- //
describe('AC-08 no business logic in React', () => {
  it('derives affordances from server fields only — no mode names in affordances.ts', () => {
    const src = readFileSync(resolve(MODULE_DIR, 'affordances.ts'), 'utf-8')
    const code = src.replace(/\/\*\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
    for (const mode of ['OBSERVED', 'ADVISORY', 'GATEWAY_ENFORCED', 'NATIVE_ENFORCED']) {
      expect(code).not.toContain(mode)
    }
    for (const state of ['GOVERNED', 'DISCOVERED', 'REGISTERED', 'CLAIMED']) {
      expect(code).not.toContain(state)
    }
  })

  it('never decides containment from a control_state or mode comparison anywhere', () => {
    const files = readdirSync(MODULE_DIR).filter((f) => f.endsWith('.tsx') || f.endsWith('.ts'))
    for (const file of files) {
      if (file === 'personas.ts') continue // a static view catalogue, not a decision
      const src = readFileSync(resolve(MODULE_DIR, file), 'utf-8')
      const code = src.replace(/\/\*\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
      // A comparison against a control state or mode literal would be a second
      // opinion about ACT's reach. The server's booleans are the only source.
      expect(code).not.toMatch(/control_state\s*===/)
      expect(code).not.toMatch(/enforcement_mode\s*===/)
    }
  })

  it('reuses the 3.10 guarded-action pattern rather than reimplementing it (AC-13)', () => {
    const drilldown = readFileSync(resolve(MODULE_DIR, 'AgentDrilldownPage.tsx'), 'utf-8')
    expect(drilldown).toContain("from '@/modules/operations/useGuardedAction'")
    expect(drilldown).toContain("from '@/modules/operations/components/ConfirmActionDialog'")
    // no second confirmation dialog in this module
    const files = readdirSync(MODULE_DIR)
    expect(files).not.toContain('ConfirmActionDialog.tsx')
    expect(files).not.toContain('useGuardedAction.ts')
  })
})

// --------------------------------------------------------------------------- //
// AC-14 — truthful failure states
// --------------------------------------------------------------------------- //
describe('AC-14 truthful failure', () => {
  it('shows a read failure as a failure, never as an empty estate', async () => {
    cc.estate.mockRejectedValue({ message: 'Service unavailable' })
    wrap(<EstateOverviewPage />)
    await waitFor(() =>
      expect(screen.getByText(/Could not load the estate overview/i)).toBeInTheDocument())
    expect(screen.getByText(/rather than a result it cannot stand behind/i)).toBeInTheDocument()
    expect(screen.queryByText('ACT governs')).not.toBeInTheDocument()
  })

  it('shows an inventory read failure rather than "no agents"', async () => {
    cc.inventory.mockRejectedValue({ message: 'boom' })
    wrap(<AgentInventoryPage />)
    await waitFor(() =>
      expect(screen.getByText(/Could not load the agent inventory/i)).toBeInTheDocument())
    expect(screen.queryByText(/No agents match these filters/)).not.toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// Assurance
//
// At 5.8's own time this asserted the page said "Not built yet" — the point
// being that a placeholder framework grid would imply evidence ACT did not
// produce. Phase 5.9 has since built it, so the assertion moves to the invariant
// that placeholder was protecting: the page must still never imply evidence ACT
// does not hold. That now means INSUFFICIENT_EVIDENCE is rendered as its own
// state (not folded into a pass), and no compliance badge or score is shown.
// --------------------------------------------------------------------------- //
describe('assurance', () => {
  it('renders insufficient-evidence as its own state and shows no compliance verdict', async () => {
    assurance.frameworks.mockResolvedValue([{
      id: 'NIST_AI_RMF', name: 'NIST AI RMF', revision: '1.0',
      scope_note: 'ACT makes no conformance claim.', mapped_controls: 5,
      mapping_version: '1',
    }])
    assurance.evaluations.mockResolvedValue([
      { id: 'e1', control_id: 'ACT.RUNTIME.TRACEABLE', catalog_version: '1', scope: 'AGENT',
        subject_id: 'agent-1', result: 'INSUFFICIENT_EVIDENCE',
        reason: 'No executions are recorded for this agent.', evidence: { executions: 0 },
        evidence_as_of: null, stale: false, remediation: null, exception_reason: null,
        exception_at: null, evaluated_at: '2026-09-16T00:00:00Z' },
    ])
    assurance.frameworkReport.mockResolvedValue({
      framework: { id: 'NIST_AI_RMF', name: 'NIST AI RMF', revision: '1.0',
                   scope_note: 'ACT makes no conformance claim.' },
      mapping_version: '1', catalog_version: '1', generated_at: '2026-09-16T00:00:00Z',
      controls: [{
        control_ref: 'GOVERN-1.1', title: 'Accountability', rationale: 'Owners are evidenced.',
        act_control_ids: ['ACT.OWNERSHIP.ACCOUNTABLE_OWNER'], evaluations: [],
        counts: { evaluated: 0, passed: 0, failed: 0, insufficient_evidence: 0, stale: 0 },
        evidence_available: false,
      }],
      disclaimer: 'This is not a compliance determination, a certification, or an audit opinion.',
    })

    wrap(<AssurancePage />)

    // Insufficient evidence gets its own tile, with the caveat spelled out.
    await waitFor(() =>
      expect(screen.getByText('Insufficient evidence')).toBeInTheDocument())
    expect(screen.getByText(/not the same as compliant/i)).toBeInTheDocument()

    // The server's disclaimer is rendered verbatim, not paraphrased away.
    await waitFor(() =>
      expect(screen.getByText(/not a compliance determination/i)).toBeInTheDocument())

    // A mapped control with no evidence says so rather than reading as satisfied.
    expect(screen.getByText(/ACT holds no evidence for this control/i)).toBeInTheDocument()

    // And no coverage score anywhere — a percentage would need a denominator
    // ACT does not know (the full control set in the customer's audit scope).
    expect(screen.queryByText(/\d+\s*%/)).not.toBeInTheDocument()
    // The word "compliant" appears only inside a negation, never as a verdict.
    for (const node of screen.queryAllByText(/compliant/i)) {
      expect(node.textContent ?? '').toMatch(/not\b/i)
    }
  })
})

// --------------------------------------------------------------------------- //
// The external-platform view reads the mode catalogue from the server
// --------------------------------------------------------------------------- //
describe('external platforms', () => {
  it('renders each mode with the server sentence and its limit', async () => {
    cc.modes.mockResolvedValue([{
      mode: 'GATEWAY_ENFORCED', display: GATEWAY_SIGNAL.enforcement_display,
      limits: GATEWAY_SIGNAL.enforcement_limits,
      reaches_boundary_calls: true, reaches_agent_execution: false, assignable: true,
    }, {
      mode: 'NATIVE_ENFORCED', display: NATIVE_SIGNAL.enforcement_display,
      limits: NATIVE_SIGNAL.enforcement_limits,
      reaches_boundary_calls: true, reaches_agent_execution: true, assignable: false,
    }])
    wrap(<ExternalPlatformsPage />)
    await waitFor(() =>
      expect(screen.getByText(GATEWAY_SIGNAL.enforcement_display)).toBeInTheDocument())
    expect(screen.getByText(/cannot be claimed, only be true/i)).toBeInTheDocument()
  })
})
