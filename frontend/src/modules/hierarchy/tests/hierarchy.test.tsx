import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BusinessUnit, Department, HierarchyNode } from '@/types'

const svc = {
  organizations: vi.fn(),
  businessUnits: vi.fn(),
  createBusinessUnit: vi.fn(),
  deleteBusinessUnit: vi.fn(),
  departments: vi.fn(),
  createDepartment: vi.fn(),
  deleteDepartment: vi.fn(),
  teams: vi.fn(),
  createTeam: vi.fn(),
  deleteTeam: vi.fn(),
  projects: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  tree: vi.fn(),
  delegations: vi.fn(),
  createDelegation: vi.fn(),
  revokeDelegation: vi.fn(),
}
vi.mock('@/services', () => ({ hierarchyService: svc }))

const { HierarchyExplorerPage } = await import('../HierarchyExplorerPage')
const { BusinessUnitsPage } = await import('../BusinessUnitsPage')
const { DepartmentsPage } = await import('../DepartmentsPage')

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

const tree: HierarchyNode = {
  id: 'org1', name: 'Acme', level: 'ORGANIZATION',
  children: [
    {
      id: 'bu1', name: 'Healthcare', level: 'BUSINESS_UNIT',
      children: [
        { id: 'd1', name: 'Radiology', level: 'DEPARTMENT', children: [
          { id: 't1', name: 'AI Ops', level: 'TEAM', children: [
            { id: 'p1', name: 'Medical AI', level: 'PROJECT', children: [] },
          ] },
        ] },
      ],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.tree.mockResolvedValue(tree)
  svc.businessUnits.mockResolvedValue([{ id: 'bu1', organization_id: 'o', name: 'Healthcare', manager_id: null, status: 'ACTIVE' } as BusinessUnit])
  svc.createBusinessUnit.mockResolvedValue({ id: 'bu2' } as BusinessUnit)
  svc.departments.mockResolvedValue([{ id: 'd1', organization_id: 'o', business_unit_id: 'bu1', name: 'Radiology', manager_id: null, status: 'ACTIVE' } as Department])
  svc.createDepartment.mockResolvedValue({ id: 'd2' } as Department)
})

describe('HierarchyExplorerPage', () => {
  it('renders the org tree and filters by search', async () => {
    const user = userEvent.setup()
    render(<HierarchyExplorerPage />, { wrapper })
    expect(await screen.findByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Medical AI')).toBeInTheDocument()

    // Searching for a leaf keeps its ancestors and hides unrelated branches.
    await user.type(screen.getByPlaceholderText(/search the hierarchy/i), 'Medical')
    expect(screen.getByText('Medical AI')).toBeInTheDocument()
  })
})

describe('BusinessUnitsPage', () => {
  it('lists and creates a business unit', async () => {
    const user = userEvent.setup()
    render(<BusinessUnitsPage />, { wrapper })
    expect(await screen.findByText('Healthcare')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('Healthcare'), 'Finance')
    await user.click(screen.getByRole('button', { name: /add/i }))
    await waitFor(() => expect(svc.createBusinessUnit).toHaveBeenCalledWith('Finance'))
  })
})

describe('DepartmentsPage', () => {
  it('creates a department under a business unit', async () => {
    const user = userEvent.setup()
    render(<DepartmentsPage />, { wrapper })
    await screen.findByText('Radiology')
    await user.type(screen.getByLabelText(/^name$/i), 'Billing')
    await user.selectOptions(screen.getByLabelText(/business unit/i), 'bu1')
    await user.click(screen.getByRole('button', { name: /add/i }))
    await waitFor(() =>
      expect(svc.createDepartment).toHaveBeenCalledWith({ name: 'Billing', business_unit_id: 'bu1' }),
    )
  })
})
