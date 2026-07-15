import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ABACAttribute, ABACPolicy, ABACSimulation } from '@/types'

const svc = {
  policies: vi.fn(),
  policy: vi.fn(),
  createPolicy: vi.fn(),
  updatePolicy: vi.fn(),
  deletePolicy: vi.fn(),
  validatePolicy: vi.fn(),
  publishPolicy: vi.fn(),
  disablePolicy: vi.fn(),
  archivePolicy: vi.fn(),
  clonePolicy: vi.fn(),
  versions: vi.fn(),
  rollback: vi.fn(),
  simulate: vi.fn(),
  simulatePolicy: vi.fn(),
  evaluate: vi.fn(),
  evaluations: vi.fn(),
  evaluation: vi.fn(),
  metrics: vi.fn(),
  attributes: vi.fn(),
  createAttribute: vi.fn(),
  updateAttribute: vi.fn(),
  exceptions: vi.fn(),
  createException: vi.fn(),
  revokeException: vi.fn(),
}
vi.mock('@/services', () => ({ abacService: svc }))
vi.mock('@/services/authService', () => ({
  adminSessionService: {
    listUsers: vi.fn().mockResolvedValue([
      { id: 'u1', email: 'alice@example.com' },
      { id: 'u2', email: 'bob@example.com' },
    ]),
  },
}))

const { ABACPoliciesPage } = await import('../ABACPoliciesPage')
const { CreateABACPolicyPage } = await import('../CreateABACPolicyPage')
const { ABACPolicyVersionsPage } = await import('../ABACPolicyVersionsPage')
const { AttributeCatalogPage } = await import('../AttributeCatalogPage')
const { PolicySimulatorPage } = await import('../PolicySimulatorPage')
const { ABACEvaluationsPage } = await import('../ABACEvaluationsPage')
const { PolicyExceptionsPage } = await import('../PolicyExceptionsPage')

function makeWrapper(initialEntry = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
}

const attributes: ABACAttribute[] = [
  { id: 'a1', name: 'environment.network_zone', category: 'ENVIRONMENT', data_type: 'STRING',
    description: null, sensitivity: 'INTERNAL',
    supported_operators: ['EQUALS', 'NOT_EQUALS', 'IN', 'NOT_IN', 'EXISTS'],
    source: 'system', is_system: true, enabled: true },
  { id: 'a2', name: 'identity.risk_score', category: 'SUBJECT', data_type: 'INTEGER',
    description: null, sensitivity: 'RESTRICTED',
    supported_operators: ['EQUALS', 'GREATER_THAN', 'LESS_THAN', 'BETWEEN'],
    source: 'system', is_system: true, enabled: true },
]

const policy: ABACPolicy = {
  id: 'p1', policy_family_id: 'f1', organization_id: 'o1',
  name: 'Restrict PHI export', description: null, version: 1, status: 'DRAFT',
  priority: 100, combining_algorithm: 'DENY_OVERRIDES', scope_type: 'ORGANIZATION',
  scope_id: null, target: { actions: ['dataset.export'] },
  conditions: { all: [{ attribute: 'environment.network_zone', operator: 'EQUALS', value: 'PUBLIC' }] },
  effect: 'DENY', obligations: null, valid_from: null, valid_until: null,
  created_by: null, updated_by: null, published_at: null, created_at: null, updated_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.attributes.mockResolvedValue(attributes)
  svc.policies.mockResolvedValue([policy])
  svc.policy.mockResolvedValue(policy)
  svc.versions.mockResolvedValue([])
  svc.evaluations.mockResolvedValue([])
  svc.exceptions.mockResolvedValue([])
})

describe('ABACPoliciesPage', () => {
  it('lists policies with status and lifecycle actions', async () => {
    const user = userEvent.setup()
    svc.publishPolicy.mockResolvedValue({ ...policy, status: 'ACTIVE' })
    render(<ABACPoliciesPage />, { wrapper: makeWrapper() })
    const list = await screen.findByTestId('abac-policies-list')
    expect(within(list).getByText('Restrict PHI export')).toBeInTheDocument()
    expect(within(list).getByText('DRAFT')).toBeInTheDocument()
    await user.click(within(list).getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(svc.publishPolicy).toHaveBeenCalledWith('p1'))
  })
})

describe('CreateABACPolicyPage (visual builder §34)', () => {
  it('builds a typed nested condition and shows a human-readable preview', async () => {
    const user = userEvent.setup()
    svc.createPolicy.mockResolvedValue(policy)
    render(<CreateABACPolicyPage />, { wrapper: makeWrapper() })

    await user.type(screen.getByLabelText(/^name$/i), 'Restrict PHI export')
    await user.type(screen.getByLabelText(/^actions$/i), 'dataset.export')

    // Add a condition leaf inside the root ALL group.
    await screen.findByTestId('condition-root')
    await user.click(screen.getByRole('button', { name: /^condition$/i }))
    const leaf = await screen.findByTestId('condition-leaf')
    await user.selectOptions(within(leaf).getByLabelText('Attribute'), 'environment.network_zone')
    await user.selectOptions(within(leaf).getByLabelText('Operator'), 'NOT_IN')
    await user.type(within(leaf).getByLabelText('Value'), 'CORPORATE, TRUSTED_VPN')

    // Preview reflects the built policy (§34).
    const preview = screen.getByTestId('policy-preview')
    expect(preview).toHaveTextContent('ON dataset.export')
    expect(preview).toHaveTextContent('environment.network_zone not in CORPORATE, TRUSTED_VPN')
    expect(preview).toHaveTextContent('THEN')
    expect(preview).toHaveTextContent('DENY')

    await user.click(screen.getByRole('button', { name: /create draft/i }))
    await waitFor(() => expect(svc.createPolicy).toHaveBeenCalled())
    const payload = svc.createPolicy.mock.calls[0][0]
    expect(payload.target).toEqual({ actions: ['dataset.export'] })
    expect(payload.conditions).toEqual({ all: [{
      attribute: 'environment.network_zone', operator: 'NOT_IN',
      value: ['CORPORATE', 'TRUSTED_VPN'],
    }] })
  })
})

describe('ABACPolicyVersionsPage', () => {
  it('lists versions and rolls back', async () => {
    const user = userEvent.setup()
    svc.versions.mockResolvedValue([
      { id: 'v2', policy_family_id: 'f1', version: 2, snapshot: { name: 'v2' },
        created_by: null, created_at: null },
      { id: 'v1', policy_family_id: 'f1', version: 1, snapshot: { name: 'v1' },
        created_by: null, created_at: null },
    ])
    svc.rollback.mockResolvedValue({ ...policy, version: 3, status: 'ACTIVE' })
    render(
      <Routes>
        <Route path="/authorization/abac/:id/versions" element={<ABACPolicyVersionsPage />} />
      </Routes>,
      { wrapper: makeWrapper('/authorization/abac/p1/versions') },
    )
    const list = await screen.findByTestId('versions-list')
    expect(within(list).getByText('Version 2')).toBeInTheDocument()
    await user.click(within(list).getByRole('button', { name: /rollback to v1/i }))
    await waitFor(() => expect(svc.rollback).toHaveBeenCalled())
  })
})

describe('AttributeCatalogPage', () => {
  it('lists the catalog and registers a custom attribute', async () => {
    const user = userEvent.setup()
    svc.createAttribute.mockResolvedValue(attributes[0])
    render(<AttributeCatalogPage />, { wrapper: makeWrapper() })
    const list = await screen.findByTestId('attributes-list')
    expect(within(list).getByText('environment.network_zone')).toBeInTheDocument()
    expect(within(list).getByText(/RESTRICTED/)).toBeInTheDocument()

    await user.type(screen.getByLabelText(/^name$/i), 'resource.contains_trade_secrets')
    await user.selectOptions(screen.getByLabelText(/data type/i), 'BOOLEAN')
    await user.click(screen.getByRole('button', { name: /register/i }))
    await waitFor(() => expect(svc.createAttribute).toHaveBeenCalledWith({
      name: 'resource.contains_trade_secrets', category: 'RESOURCE', data_type: 'BOOLEAN',
    }))
  })
})

describe('PolicySimulatorPage (§35)', () => {
  it('runs a simulation and renders all layers', async () => {
    const user = userEvent.setup()
    const sim: ABACSimulation = {
      baseline_rbac: { allowed: true, reason: 'Granted by legacy:ADMIN' },
      resource_authorization: null,
      abac: {
        decision: 'DENY', allowed: false, reason: "Denied by policy 'Restrict PHI export'.",
        matched_policies: [{ policy_id: 'p1', name: 'Restrict PHI export', effect: 'DENY', priority: 100 }],
        obligations: [],
        explanation: {
          matched_policies: [{
            policy_id: 'p1', name: 'Restrict PHI export', effect: 'DENY', priority: 100,
            conditions: [{ attribute: 'environment.network_zone', operator: 'NOT_IN',
                           expected: ['CORPORATE'], result: true, missing: false }],
          }],
          winning_effect: 'DENY',
        },
        evaluation_time_ms: 4.2, request_id: null, applicable: true,
      },
    }
    svc.simulate.mockResolvedValue(sim)
    render(<PolicySimulatorPage />, { wrapper: makeWrapper() })

    await screen.findByRole('option', { name: 'bob@example.com' })
    await user.selectOptions(screen.getByLabelText(/identity/i), 'u2')
    await user.click(screen.getByRole('button', { name: /simulate/i }))

    const panel = await screen.findByTestId('simulation-result')
    expect(panel).toHaveTextContent('DENY')
    expect(panel).toHaveTextContent('Granted by legacy:ADMIN')
    expect(panel).toHaveTextContent("Denied by policy 'Restrict PHI export'.")
    expect(panel).toHaveTextContent('environment.network_zone')
    await waitFor(() => expect(svc.simulate).toHaveBeenCalledWith(expect.objectContaining({
      identity_id: 'u2',
      context: expect.objectContaining({ 'environment.network_zone': 'PUBLIC' }),
    })))
  })
})

describe('ABACEvaluationsPage (§36)', () => {
  it('lists decisions and expands the explanation', async () => {
    const user = userEvent.setup()
    svc.evaluations.mockResolvedValue([{
      id: 'e1', organization_id: 'o1', identity_id: 'u1', resource_type: null,
      resource_id: null, action: 'dataset.export', decision: 'DENY',
      matched_policy_ids: ['p1'], obligations: [],
      explanation: { winning_effect: 'DENY' }, evaluation_time_ms: 3.4,
      request_id: 'req-1', correlation_id: null, created_at: null,
    }])
    render(<ABACEvaluationsPage />, { wrapper: makeWrapper() })
    const list = await screen.findByTestId('evaluations-list')
    expect(within(list).getByText('dataset.export')).toBeInTheDocument()
    await user.click(within(list).getByText('dataset.export'))
    expect(await screen.findByTestId('evaluation-detail')).toHaveTextContent('winning_effect')
  })
})

describe('PolicyExceptionsPage', () => {
  it('grants a time-boxed exception', async () => {
    const user = userEvent.setup()
    svc.policies.mockResolvedValue([{ ...policy, status: 'ACTIVE' }])
    svc.createException.mockResolvedValue({})
    render(<PolicyExceptionsPage />, { wrapper: makeWrapper() })

    await screen.findByRole('option', { name: 'Restrict PHI export' })
    await user.selectOptions(screen.getByLabelText(/^policy$/i), 'p1')
    await user.selectOptions(screen.getByLabelText(/^subject$/i), 'u2')
    // Set the expiry via fireEvent-compatible typing on the date input.
    const dateInput = screen.getByLabelText(/expires/i)
    await user.type(dateInput, '2030-01-01')
    await user.click(screen.getByRole('button', { name: /grant exception/i }))
    await waitFor(() => expect(svc.createException).toHaveBeenCalledWith(expect.objectContaining({
      policy_id: 'p1', subject_id: 'u2',
    })))
  })
})
