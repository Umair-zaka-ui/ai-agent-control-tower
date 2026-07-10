import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Permission, PermissionGroup, Role, RoleHierarchyEdge } from '@/types'

const svc = {
  listRoles: vi.fn(),
  getRole: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
  effectivePermissions: vi.fn(),
  listPermissions: vi.fn(),
  createPermission: vi.fn(),
  deletePermission: vi.fn(),
  listPermissionGroups: vi.fn(),
  listAssignments: vi.fn(),
  createAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
  listHierarchy: vi.fn(),
  createHierarchyEdge: vi.fn(),
  deleteHierarchyEdge: vi.fn(),
  audit: vi.fn(),
}
vi.mock('@/services', () => ({ authorizationService: svc }))
vi.mock('@/services/authService', () => ({
  adminSessionService: {
    listUsers: vi.fn().mockResolvedValue([
      {
        id: 'u1',
        email: 'member@acme.com',
        display_name: 'Member',
        organization_id: 'o1',
        role: 'VIEWER',
        is_active: true,
        status: 'ACTIVE',
      },
    ]),
  },
}))

const { RolesPage } = await import('../RolesPage')
const { PermissionsPage } = await import('../PermissionsPage')
const { RoleHierarchyPage } = await import('../RoleHierarchyPage')
const { PermissionGroupsPage } = await import('../PermissionGroupsPage')
const { RoleAssignmentsPage } = await import('../RoleAssignmentsPage')
const { AuthorizationAuditPage } = await import('../AuthorizationAuditPage')

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const role = (o: Partial<Role> = {}): Role => ({
  id: 'r1',
  organization_id: 'o1',
  name: 'analyst',
  display_name: 'Analyst',
  description: null,
  category: 'CUSTOM',
  status: 'ACTIVE',
  is_system: false,
  is_assignable: true,
  priority: 40,
  permissions: ['agent.view'],
  assignment_count: 0,
  created_at: null,
  updated_at: null,
  ...o,
})

const perm = (code: string, group_id: string | null): Permission => ({
  id: code,
  code,
  display_name: code,
  description: null,
  group_id,
  resource_type: code.split('.')[0],
  action: code.split('.')[1] ?? null,
  is_system: true,
  created_at: null,
})

const group: PermissionGroup = { id: 'g1', name: 'agents', display_name: 'Agents', description: null, sort_order: 10 }

beforeEach(() => {
  vi.clearAllMocks()
  svc.listRoles.mockResolvedValue([
    role(),
    role({ id: 'r2', name: 'ROLE_VIEWER', display_name: 'Viewer', is_system: true, category: 'SYSTEM' }),
  ])
  svc.listPermissions.mockResolvedValue([perm('agent.view', 'g1'), perm('policy.view', null)])
  svc.listPermissionGroups.mockResolvedValue([group])
  svc.createRole.mockResolvedValue(role({ id: 'r3', name: 'new-role' }))
  svc.listHierarchy.mockResolvedValue([])
  svc.createHierarchyEdge.mockResolvedValue({ id: 'e1' } as RoleHierarchyEdge)
  svc.listAssignments.mockResolvedValue([])
  svc.createAssignment.mockResolvedValue({ id: 'as1' })
  svc.audit.mockResolvedValue([
    {
      id: 'au1',
      organization_id: 'o1',
      actor_id: 'a1',
      identity_id: null,
      event_type: 'ROLE_CREATED',
      permission: null,
      resource_type: null,
      resource_id: null,
      decision: null,
      reason: null,
      meta: { role_id: 'r1', name: 'analyst' },
      created_at: new Date().toISOString(),
    },
  ])
})

describe('RolesPage', () => {
  it('lists roles and marks system roles as non-deletable', async () => {
    render(<RolesPage />, { wrapper })
    expect(await screen.findByText('Analyst')).toBeInTheDocument()
    // The system role has no delete button; the custom role does.
    expect(screen.getByRole('button', { name: /delete analyst/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete ROLE_VIEWER/i })).not.toBeInTheDocument()
  })

  it('creates a role with selected permissions', async () => {
    const user = userEvent.setup()
    render(<RolesPage />, { wrapper })
    await screen.findByText('Analyst')
    await user.type(screen.getByLabelText(/^name$/i), 'auditor2')
    await user.click(screen.getByRole('button', { name: 'agent.view' }))
    await user.click(screen.getByRole('button', { name: /^create$/i }))
    await waitFor(() =>
      expect(svc.createRole).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'auditor2', permissions: ['agent.view'] }),
      ),
    )
  })
})

describe('PermissionsPage', () => {
  it('groups permissions by domain', async () => {
    render(<PermissionsPage />, { wrapper })
    expect(await screen.findByText(/Agents/)).toBeInTheDocument()
    expect(screen.getByText('agent.view')).toBeInTheDocument()
    // policy.view has no group -> "Other"
    expect(screen.getByText('Other')).toBeInTheDocument()
  })
})

describe('RoleHierarchyPage', () => {
  it('adds an inheritance edge', async () => {
    const user = userEvent.setup()
    render(<RoleHierarchyPage />, { wrapper })
    await screen.findByText(/no hierarchy edges yet/i)
    const [parent, child] = screen.getAllByRole('combobox')
    await user.selectOptions(parent, 'r1')
    await user.selectOptions(child, 'r2')
    await user.click(screen.getByRole('button', { name: /add edge/i }))
    await waitFor(() => expect(svc.createHierarchyEdge).toHaveBeenCalledWith('r1', 'r2'))
  })
})

describe('PermissionGroupsPage', () => {
  it('lists the permission groups', async () => {
    render(<PermissionGroupsPage />, { wrapper })
    expect(await screen.findByText('Agents')).toBeInTheDocument()
    expect(screen.getByTestId('permission-groups-list')).toBeInTheDocument()
  })
})

describe('RoleAssignmentsPage', () => {
  it('assigns a scoped role to a user', async () => {
    const user = userEvent.setup()
    render(<RoleAssignmentsPage />, { wrapper })
    // wait for the user option to load
    await screen.findByRole('option', { name: 'member@acme.com' })
    await user.selectOptions(screen.getByLabelText(/^user$/i), 'u1')
    await user.selectOptions(screen.getByLabelText(/^role$/i), 'r1')
    await user.selectOptions(screen.getByLabelText(/^scope$/i), 'ORGANIZATION')
    await user.click(screen.getByRole('button', { name: /^assign$/i }))
    await waitFor(() =>
      expect(svc.createAssignment).toHaveBeenCalledWith(
        expect.objectContaining({ user_id: 'u1', role_id: 'r1', scope: 'ORGANIZATION' }),
      ),
    )
  })
})

describe('AuthorizationAuditPage', () => {
  it('lists audit entries and filters by event type', async () => {
    const user = userEvent.setup()
    render(<AuthorizationAuditPage />, { wrapper })
    expect((await screen.findAllByText('ROLE_CREATED')).length).toBeGreaterThan(0)
    // changing the filter re-queries with the chosen event type
    await user.selectOptions(screen.getByRole('combobox'), 'ROLE_ASSIGNED')
    await waitFor(() =>
      expect(svc.audit).toHaveBeenCalledWith(expect.objectContaining({ eventType: 'ROLE_ASSIGNED' })),
    )
  })
})
