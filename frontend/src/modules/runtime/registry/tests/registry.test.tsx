// Phase 5.1 frontend tests — registration wizard (incl. draft autosave),
// duplicate review, import, export, and legacy migration pages.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const svc = {
  agent: vi.fn(),
  agents: vi.fn(),
  registerAgent: vi.fn(),
  duplicateMatches: vi.fn(),
  duplicateCheck: vi.fn(),
  reviewDuplicate: vi.fn(),
  importAgents: vi.fn(),
  importJob: vi.fn(),
  importItems: vi.fn(),
  exportAgents: vi.fn(),
  classifyLegacyAgents: vi.fn(),
  migrationRecords: vi.fn(),
}
vi.mock('@/services', () => ({ runtimeService: svc }))
vi.mock('@/services/apiClient', () => ({ apiClient: { get: vi.fn().mockResolvedValue({ data: new Blob() }) } }))
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'owner@example.com' },
    permissions: ['runtime.agent.view', 'runtime.agent.create', 'runtime.agent.import', 'runtime.agent.export'],
  }),
}))

const { RegistrationWizardPage } = await import('../RegistrationWizardPage')
const { DuplicateReviewPage } = await import('../DuplicateReviewPage')
const { ImportPage } = await import('../ImportPage')
const { ExportPage } = await import('../ExportPage')
const { MigrationPage } = await import('../MigrationPage')
const { PermissionProvider } = await import('@/authorization')

function wrap(children: ReactNode, initialRoute = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <PermissionProvider>
          <Routes>
            <Route path="/" element={children} />
            <Route path="/runtime/agents/:id/duplicates" element={children} />
          </Routes>
        </PermissionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const AGENT_FIXTURE = {
  id: 'agent-1', organization_id: 'org-1', name: 'Claims Agent', slug: null,
  description: null, agent_type: 'ASSISTANT', status: 'DRAFT', lifecycle_status: 'DRAFT',
  criticality: 'MEDIUM', data_classification: 'INTERNAL', default_environment: 'DEVELOPMENT',
  project_id: null, owner_type: null, owner_id: null,
  created_at: '2026-07-18T05:00:00Z', updated_at: '2026-07-18T05:00:00Z', archived_at: null,
}

const DUPLICATE_FIXTURE = {
  id: 'dup-1', source_agent_id: 'agent-1', candidate_agent_id: 'agent-2', match_type: 'SIMILAR' as const,
  confidence_score: 82, matching_fields: ['name', 'entrypoint'], status: 'LIKELY_DUPLICATE' as const,
  reviewed_by: null, review_decision: null, review_reason: null,
  created_at: '2026-07-18T05:00:00Z', reviewed_at: null,
}

const IMPORT_JOB_FIXTURE = {
  id: 'job-1', organization_id: 'org-1', file_name: 'agents.json', format: 'JSON' as const,
  mode: 'CREATE_ONLY' as const, status: 'COMPLETED' as const, total_records: 2, successful_records: 1,
  failed_records: 1, warning_records: 0, created_by: 'u1',
  started_at: '2026-07-18T05:00:00Z', completed_at: '2026-07-18T05:00:01Z', created_at: '2026-07-18T05:00:00Z',
}

const EXPORT_JOB_FIXTURE = {
  id: 'exp-1', organization_id: 'org-1', export_type: 'INVENTORY_SUMMARY' as const, format: 'JSON' as const,
  filters: {}, status: 'COMPLETED' as const, record_count: 5, storage_reference: 'ref', expires_at: null,
  created_by: 'u1', created_at: '2026-07-18T05:00:00Z', completed_at: '2026-07-18T05:00:01Z',
}

const MIGRATION_RECORD_FIXTURE = {
  id: 'mig-1', agent_id: 'agent-1', migration_batch_id: 'batch-abc123', legacy_source: 'PHASE_5_0_REGISTRY',
  legacy_id: 'agent-1', migration_status: 'MISSING_IDENTITY', mapping_warnings: ['identity missing'],
  migrated_by: 'u1', migrated_at: '2026-07-18T05:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  svc.agent.mockResolvedValue(AGENT_FIXTURE)
  svc.agents.mockResolvedValue([AGENT_FIXTURE, { ...AGENT_FIXTURE, id: 'agent-2', name: 'Other Agent' }])
  svc.registerAgent.mockResolvedValue({ ...AGENT_FIXTURE, id: 'agent-new' })
  svc.duplicateMatches.mockResolvedValue([DUPLICATE_FIXTURE])
  svc.duplicateCheck.mockResolvedValue([DUPLICATE_FIXTURE])
  svc.reviewDuplicate.mockResolvedValue({ ...DUPLICATE_FIXTURE, status: 'CONFIRMED_DUPLICATE' })
  svc.importAgents.mockResolvedValue(IMPORT_JOB_FIXTURE)
  svc.importJob.mockResolvedValue(IMPORT_JOB_FIXTURE)
  svc.importItems.mockResolvedValue([])
  svc.exportAgents.mockResolvedValue(EXPORT_JOB_FIXTURE)
  svc.classifyLegacyAgents.mockResolvedValue([MIGRATION_RECORD_FIXTURE])
  svc.migrationRecords.mockResolvedValue([MIGRATION_RECORD_FIXTURE])
})

describe('RegistrationWizardPage (§22, §23)', () => {
  it('autosaves the draft to localStorage and restores it after remount', async () => {
    const { unmount } = wrap(<RegistrationWizardPage />)
    await userEvent.type(screen.getByPlaceholderText('Claims Denial Review Agent'), 'My Draft Agent')
    await waitFor(() => {
      const raw = localStorage.getItem('runtime.agent.registration.draft.v1')
      expect(raw).toBeTruthy()
      expect(JSON.parse(raw as string).name).toBe('My Draft Agent')
    })
    unmount()

    wrap(<RegistrationWizardPage />)
    expect(await screen.findByText('Restored your unsaved draft from a previous session.')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Claims Denial Review Agent')).toHaveValue('My Draft Agent')
  })

  it('discarding the draft clears localStorage', async () => {
    localStorage.setItem('runtime.agent.registration.draft.v1', JSON.stringify({ name: 'Stale Draft' }))
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', { value: { ...window.location, reload: reloadSpy }, writable: true })

    wrap(<RegistrationWizardPage />)
    await userEvent.click(await screen.findByText('Discard draft'))
    expect(localStorage.getItem('runtime.agent.registration.draft.v1')).toBeNull()
  })

  it('walks the wizard to completion and registers the agent, clearing the draft', async () => {
    wrap(<RegistrationWizardPage />)

    // Step 0 — Basic Info
    await userEvent.type(screen.getByPlaceholderText('Claims Denial Review Agent'), 'My Agent')
    await userEvent.type(screen.getByRole('textbox', { name: 'Description *' }) ?? screen.getByLabelText('Description *'), 'A test agent')
    await userEvent.type(screen.getByLabelText('Business purpose *'), 'Automates a test workflow')
    await userEvent.click(screen.getByText('Next'))

    // Step 1 — Org Placement (optional)
    await userEvent.click(screen.getByText('Next'))

    // Step 2 — Ownership
    await userEvent.type(screen.getByLabelText('Business owner (user ID) *'), 'user-42')
    await userEvent.click(screen.getByText('Next'))

    // Step 3 — Machine Identity (informational)
    await userEvent.click(screen.getByText('Next'))

    // Step 4 — Technical Definition
    await userEvent.type(screen.getByPlaceholderText('agents.claims:handle'), 'agents.test:handle')
    await userEvent.click(screen.getByText('Next'))

    // Step 5 — Contracts (defaults are valid JSON)
    await userEvent.click(screen.getByText('Next'))

    // Step 6 — Risk & Classification
    await userEvent.click(screen.getByText('Next'))

    // Step 7 — Capabilities & Tools
    await userEvent.click(screen.getByText('Next'))

    // Step 8 — Review & submit
    await userEvent.click(screen.getByText('Register agent'))

    await waitFor(() => expect(svc.registerAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'My Agent',
        owner_id: 'user-42',
        definition: expect.objectContaining({ entrypoint: 'agents.test:handle' }),
      }),
    ))
    await waitFor(() => expect(localStorage.getItem('runtime.agent.registration.draft.v1')).toBeNull())
  })
})

describe('DuplicateReviewPage (§32, §33, §64)', () => {
  it('lists duplicate candidates and runs a duplicate check', async () => {
    wrap(<DuplicateReviewPage />, '/runtime/agents/agent-1/duplicates')
    expect(await screen.findByText('Other Agent')).toBeInTheDocument()
    expect(screen.getByText('LIKELY_DUPLICATE')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Run duplicate check'))
    await waitFor(() => expect(svc.duplicateCheck).toHaveBeenCalledWith('agent-1'))
  })

  it('submits a review decision with a reason', async () => {
    wrap(<DuplicateReviewPage />, '/runtime/agents/agent-1/duplicates')
    await screen.findByText('Other Agent')

    await userEvent.selectOptions(screen.getByLabelText('Decision'), 'CONFIRM_DUPLICATE')
    await userEvent.type(screen.getByLabelText('Review reason'), 'Same entrypoint and owner')
    await userEvent.click(screen.getByText('Submit'))

    await waitFor(() => expect(svc.reviewDuplicate).toHaveBeenCalledWith('agent-1', 'dup-1', {
      review_decision: 'CONFIRM_DUPLICATE', review_reason: 'Same entrypoint and owner',
    }))
  })
})

describe('ImportPage (§39-§45, §60)', () => {
  it('shows job status and per-record results after a completed import', async () => {
    svc.importItems.mockResolvedValue([
      { id: 'i1', import_job_id: 'job-1', record_identifier: 'agent-a', status: 'CREATED', agent_id: 'agent-x', errors: [], warnings: [] },
      { id: 'i2', import_job_id: 'job-1', record_identifier: 'agent-b', status: 'FAILED', agent_id: null, errors: [{ code: 'E1', message: 'bad schema' }], warnings: [] },
    ])
    const file = new File(['[{"name":"agent-a"}]'], 'agents.json', { type: 'application/json' })

    wrap(<ImportPage />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(svc.importAgents).toHaveBeenCalledWith(
      expect.objectContaining({ file_name: 'agents.json', format: 'JSON', mode: 'CREATE_ONLY' }),
    ))
    expect(await screen.findByText('agent-a')).toBeInTheDocument()
    expect(screen.getByText('bad schema')).toBeInTheDocument()
  })
})

describe('ExportPage (§39-§45, §60)', () => {
  it('exports agents with the selected type and format', async () => {
    wrap(<ExportPage />)
    await userEvent.selectOptions(screen.getByLabelText('Export type'), 'FULL_CONFIGURATION')
    await userEvent.selectOptions(screen.getByLabelText('Format'), 'YAML')
    await userEvent.click(screen.getByText('Export & download'))

    await waitFor(() => expect(svc.exportAgents).toHaveBeenCalledWith({
      export_type: 'FULL_CONFIGURATION', format: 'YAML',
    }))
  })
})

describe('MigrationPage (§70-§73)', () => {
  it('lists migration records and classifies unclassified agents', async () => {
    wrap(<MigrationPage />)
    expect(await screen.findByText('MISSING_IDENTITY')).toBeInTheDocument()
    expect(screen.getByText('identity missing')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Classify unclassified agents'))
    await waitFor(() => expect(svc.classifyLegacyAgents).toHaveBeenCalled())
  })
})
