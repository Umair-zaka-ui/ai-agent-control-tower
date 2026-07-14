import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ProtectedResource,
  ResourceACLEntry,
  ResourceAuthorizeResult,
  ResourceShare,
} from '@/types'

const svc = {
  resourceTypes: vi.fn(),
  resources: vi.fn(),
  resource: vi.fn(),
  register: vi.fn(),
  update: vi.fn(),
  transferOwnership: vi.fn(),
  ownershipHistory: vi.fn(),
  acl: vi.fn(),
  addAclEntry: vi.fn(),
  updateAclEntry: vi.fn(),
  deleteAclEntry: vi.fn(),
  shares: vi.fn(),
  share: vi.fn(),
  updateShare: vi.fn(),
  revokeShare: vi.fn(),
  delegations: vi.fn(),
  delegate: vi.fn(),
  revokeDelegation: vi.fn(),
  setPolicy: vi.fn(),
  authorize: vi.fn(),
}
vi.mock('@/services', () => ({ resourceAuthzService: svc }))
vi.mock('@/services/authService', () => ({
  adminSessionService: {
    listUsers: vi.fn().mockResolvedValue([
      { id: 'u1', email: 'alice@example.com' },
      { id: 'u2', email: 'bob@example.com' },
    ]),
  },
}))

const { ResourcePermissionsPage } = await import('../ResourcePermissionsPage')
const { ResourceACLPage } = await import('../ResourceACLPage')
const { ResourceSharingPage } = await import('../ResourceSharingPage')
const { OwnershipTransferPage } = await import('../OwnershipTransferPage')
const { DelegationManagementPage } = await import('../DelegationManagementPage')
const { AuthorizationInspectorPage } = await import('../AuthorizationInspectorPage')

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

const resource: ProtectedResource = {
  id: 'r1', resource_type: 'ai_agent', resource_id: 'ext1', name: 'Radiology agent',
  organization_id: 'o1', project_id: null, owner_id: 'u1', owner_type: 'USER',
  created_by: 'u1', visibility: 'PRIVATE', status: 'ACTIVE', policy: null,
  created_at: null, updated_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.resourceTypes.mockResolvedValue(['ai_agent', 'policy'])
  svc.resources.mockResolvedValue([resource])
  svc.resource.mockResolvedValue(resource)
  svc.acl.mockResolvedValue([])
  svc.shares.mockResolvedValue([])
  svc.delegations.mockResolvedValue([])
  svc.ownershipHistory.mockResolvedValue([])
})

describe('ResourcePermissionsPage', () => {
  it('lists resources and registers a new one', async () => {
    const user = userEvent.setup()
    svc.register.mockResolvedValue({ ...resource, id: 'r2' })
    render(<ResourcePermissionsPage />, { wrapper: makeWrapper() })
    expect(await screen.findByText('Radiology agent')).toBeInTheDocument()

    await user.type(screen.getByLabelText(/^name$/i), 'New KB')
    await user.click(screen.getByRole('button', { name: /register/i }))
    await waitFor(() => expect(svc.register).toHaveBeenCalledWith({
      resource_type: 'ai_agent', name: 'New KB', visibility: 'PRIVATE',
    }))
  })
})

describe('ResourceACLPage', () => {
  it('adds an ACL entry for the selected resource', async () => {
    const user = userEvent.setup()
    const entry: ResourceACLEntry = {
      id: 'a1', resource_id: 'r1', principal_type: 'USER', principal_id: 'u2',
      permission: 'ai_agent.update', effect: 'ALLOW', expires_at: null,
      created_by: 'u1', created_at: null,
    }
    svc.addAclEntry.mockResolvedValue(entry)
    render(<ResourceACLPage />, { wrapper: makeWrapper('/?resource=r1') })

    await screen.findByRole('option', { name: 'bob@example.com' })
    await user.selectOptions(screen.getByLabelText(/^principal$/i), 'u2')
    await user.type(screen.getByLabelText(/^permission$/i), 'ai_agent.update')
    await user.click(screen.getByRole('button', { name: /add entry/i }))
    await waitFor(() => expect(svc.addAclEntry).toHaveBeenCalledWith('r1', {
      principal_type: 'USER', principal_id: 'u2',
      permission: 'ai_agent.update', effect: 'ALLOW',
    }))
  })

  it('renders existing entries with their effect', async () => {
    svc.acl.mockResolvedValue([{
      id: 'a2', resource_id: 'r1', principal_type: 'USER', principal_id: 'u2',
      permission: '*', effect: 'DENY', expires_at: null, created_by: null, created_at: null,
    } satisfies ResourceACLEntry])
    render(<ResourceACLPage />, { wrapper: makeWrapper('/?resource=r1') })
    const list = await screen.findByTestId('acl-list')
    await waitFor(() => expect(within(list).getByText('bob@example.com')).toBeInTheDocument())
    expect(within(list).getByText('DENY')).toBeInTheDocument()
  })
})

describe('ResourceSharingPage', () => {
  it('shares the resource with a user at READ level', async () => {
    const user = userEvent.setup()
    svc.share.mockResolvedValue({} as ResourceShare)
    render(<ResourceSharingPage />, { wrapper: makeWrapper('/?resource=r1') })

    await screen.findByRole('option', { name: 'bob@example.com' })
    await user.selectOptions(screen.getByLabelText(/^target$/i), 'u2')
    await user.click(screen.getByRole('button', { name: /^share$/i }))
    await waitFor(() => expect(svc.share).toHaveBeenCalledWith('r1', {
      shared_with_type: 'USER', shared_with_id: 'u2', access_level: 'READ',
    }))
  })
})

describe('OwnershipTransferPage', () => {
  it('shows the current owner and transfers ownership', async () => {
    const user = userEvent.setup()
    svc.transferOwnership.mockResolvedValue({ ...resource, owner_id: 'u2' })
    render(<OwnershipTransferPage />, { wrapper: makeWrapper('/?resource=r1') })
    expect(await screen.findByTestId('current-owner')).toHaveTextContent('alice@example.com')

    await user.selectOptions(screen.getByLabelText(/new owner$/i), 'u2')
    await user.type(screen.getByLabelText(/reason/i), 'handover')
    await user.click(screen.getByRole('button', { name: /transfer/i }))
    await waitFor(() => expect(svc.transferOwnership).toHaveBeenCalledWith('r1', {
      new_owner_id: 'u2', new_owner_type: 'USER', reason: 'handover',
    }))
  })
})

describe('DelegationManagementPage', () => {
  it('creates a manage delegation', async () => {
    const user = userEvent.setup()
    svc.delegate.mockResolvedValue({})
    render(<DelegationManagementPage />, { wrapper: makeWrapper('/?resource=r1') })

    await screen.findByRole('option', { name: 'bob@example.com' })
    await user.selectOptions(screen.getByLabelText(/^delegate$/i), 'u2')
    await user.click(screen.getByRole('button', { name: /delegate/i }))
    await waitFor(() => expect(svc.delegate).toHaveBeenCalledWith('r1', {
      delegate_id: 'u2', permissions: ['manage'], expires_at: null, reason: null,
    }))
  })
})

describe('AuthorizationInspectorPage', () => {
  it('simulates a decision and renders the result panel', async () => {
    const user = userEvent.setup()
    const result: ResourceAuthorizeResult = {
      allowed: true, permission: 'ai_agent.view', reason: 'Granted via ACL', source: 'ACL',
      error_code: null, resource_pk: 'r1', resource_type: 'ai_agent',
      owner_id: 'u1', owner_type: 'USER', visibility: 'DEPARTMENT',
      scope: null, source_role: 'ROLE_AI_OPERATOR', matched_rule_id: 'a1',
      steps: ['IDENTITY_VERIFIED', 'ACL_ALLOW_MATCHED'],
    }
    svc.authorize.mockResolvedValue(result)
    render(<AuthorizationInspectorPage />, { wrapper: makeWrapper('/?resource=r1') })

    await screen.findByRole('option', { name: 'bob@example.com' })
    await user.selectOptions(screen.getByLabelText(/identity/i), 'u2')
    await user.type(screen.getByLabelText(/permission/i), 'ai_agent.view')
    await user.click(screen.getByRole('button', { name: /evaluate/i }))

    const panel = await screen.findByTestId('inspector-result')
    expect(panel).toHaveTextContent('ALLOW')
    expect(panel).toHaveTextContent('Granted via ACL')
    expect(panel).toHaveTextContent('ROLE_AI_OPERATOR')
    expect(panel).toHaveTextContent('alice@example.com')
    expect(panel).toHaveTextContent('DEPARTMENT')
    await waitFor(() => expect(svc.authorize).toHaveBeenCalledWith('r1', {
      permission: 'ai_agent.view', identity_id: 'u2',
    }))
  })
})
