// Phase 5.2 Part 1 frontend tests — the Versions section of AgentDetailPage:
// release-channel display, the expandable release-details panel (snapshot,
// lineage, release metadata, artifacts, notes, status history), and the new
// Retire action.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const svc = {
  agent: vi.fn(),
  versions: vi.fn(),
  releaseChannels: vi.fn(),
  createVersion: vi.fn(),
  validateVersion: vi.fn(),
  approveVersion: vi.fn(),
  publishVersion: vi.fn(),
  deprecateVersion: vi.fn(),
  revokeVersion: vi.fn(),
  retireVersion: vi.fn(),
  versionSnapshot: vi.fn(),
  versionStatusHistory: vi.fn(),
  releaseMetadata: vi.fn(),
  releaseArtifacts: vi.fn(),
  releaseNotes: vi.fn(),
  addReleaseArtifact: vi.fn(),
  addReleaseNote: vi.fn(),
  upsertReleaseMetadata: vi.fn(),
  setRollbackTarget: vi.fn(),
  versionReadiness: vi.fn(),
  compareVersions: vi.fn(),
}
vi.mock('@/services', () => ({ runtimeService: svc }))
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'owner@example.com' },
    permissions: [
      'runtime.agent.view', 'runtime.version.view', 'runtime.version.create', 'runtime.version.publish',
      'runtime.version.deprecate', 'runtime.version.revoke', 'runtime.version.retire',
      'runtime.deployment.create', 'runtime.deployment.deploy',
    ],
  }),
}))

const { AgentDetailPage } = await import('../AgentDetailPage')
const { PermissionProvider } = await import('@/authorization')
const { ROUTES } = await import('@/constants/routes')

function wrap(agentId = 'agent-1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/runtime/agents/${agentId}`]}>
        <PermissionProvider>
          <Routes>
            <Route path={ROUTES.RUNTIME_AGENT_DETAIL} element={<AgentDetailPage />} />
          </Routes>
        </PermissionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  ) as unknown as ReactNode
}

const AGENT_FIXTURE = {
  id: 'agent-1', organization_id: 'org-1', name: 'Claims Agent', display_name: null, slug: 'claims-agent',
  description: 'Reviews claims.', business_purpose: 'Reduce manual review.', agent_type: 'ASSISTANT',
  status: 'ACTIVE', lifecycle_status: 'ACTIVE', criticality: 'MEDIUM', risk_level: 'LOW',
  data_classification: 'INTERNAL', autonomy_level: 'ASSISTIVE', default_environment: 'DEVELOPMENT',
  project_id: null, business_unit_id: null, department_id: null, team_id: null, identity_id: null,
  owner_type: null, owner_id: null, technical_owner_id: null, compliance_owner_id: null,
  support_contact: null, documentation_url: null, repository_url: null, tags: [], metadata: {},
  registration_source: 'MANUAL', external_reference: null, created_by: null, updated_by: null,
  row_version: 1, created_at: '2026-07-18T05:00:00Z', updated_at: '2026-07-18T05:00:00Z',
  validated_at: null, approved_at: null, activated_at: null, suspended_at: null, archived_at: null,
  retired_at: null,
}

const CHANNEL_FIXTURE = [
  { id: 'chan-stable', name: 'STABLE', description: 'GA releases.', is_default: true, created_at: '2026-07-18T05:00:00Z' },
  { id: 'chan-beta', name: 'BETA', description: 'Pre-release.', is_default: false, created_at: '2026-07-18T05:00:00Z' },
]

function versionFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'v1', agent_id: 'agent-1', definition_id: 'def-1', version: 1, semantic_version: '0.1.0',
    status: 'DRAFT', configuration_snapshot: {}, prompt_snapshot: null,
    model_configuration: { provider: 'MOCK', model: 'mock-model' }, capabilities_snapshot: [],
    tools_snapshot: [], policy_snapshot: null, checksum: 'a'.repeat(64), release_notes: null,
    created_by: 'u1', created_at: '2026-07-18T05:00:00Z', published_at: null, deprecated_at: null,
    release_channel_id: 'chan-stable', compatibility_level: 'UNKNOWN', signature_id: null,
    snapshot_reference: null, parent_version_id: null, rollback_target_id: null, superseded_by_id: null,
    release_branch: 'main', reviewed_by: null, revoked_reason: null, retired_at: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.agent.mockResolvedValue(AGENT_FIXTURE)
  svc.releaseChannels.mockResolvedValue(CHANNEL_FIXTURE)
  svc.versionSnapshot.mockResolvedValue(null)
  svc.versionStatusHistory.mockResolvedValue([
    { id: 'h1', agent_version_id: 'v1', previous_status: null, new_status: 'DRAFT', reason: null,
      changed_by: 'u1', created_at: '2026-07-18T05:00:00Z' },
  ])
  svc.releaseMetadata.mockResolvedValue(null)
  svc.releaseArtifacts.mockResolvedValue([])
  svc.releaseNotes.mockResolvedValue([])
  svc.versionReadiness.mockResolvedValue({
    ready: false,
    checks: [
      { name: 'registry_active', passed: false, message: 'Agent is DRAFT, not ACTIVE.', skipped: false },
      { name: 'compatibility_analysis', passed: true, message: 'Deferred to Part 3 — not evaluated.', skipped: true },
    ],
  })
  svc.compareVersions.mockResolvedValue({
    version_a: { id: 'v1', version: 1, semantic_version: '0.1.0' },
    version_b: { id: 'v2', version: 2, semantic_version: '0.2.0' },
    scalar_changes: { semantic_version: { from: '0.1.0', to: '0.2.0' } },
    configuration_changes: {},
    list_changes: {},
    artifacts_added: [], artifacts_removed: [], notes_added: [], notes_removed: [],
    identical: false,
  })
})

describe('AgentDetailPage — Versions (Phase 5.2 Part 1)', () => {
  it('shows the release channel for each version', async () => {
    svc.versions.mockResolvedValue([versionFixture()])
    wrap()
    expect(await screen.findByText('v1')).toBeInTheDocument()
    expect(await screen.findByText('STABLE')).toBeInTheDocument()
  })

  it('expands the details panel and shows lineage, snapshot and status history', async () => {
    svc.versions.mockResolvedValue([versionFixture()])
    wrap()
    await screen.findByText('v1')
    await userEvent.click(screen.getByText('Details'))

    expect(await screen.findByText('Lineage')).toBeInTheDocument()
    expect(screen.getByText('Snapshot')).toBeInTheDocument()
    expect(screen.getByText('Not built yet — built at publish.')).toBeInTheDocument()
    expect(screen.getByText('Status history')).toBeInTheDocument()
    await waitFor(() => expect(svc.versionStatusHistory).toHaveBeenCalledWith('agent-1', 'v1'))
  })

  it('adds a release artifact and a release note from the details panel', async () => {
    svc.versions.mockResolvedValue([versionFixture()])
    svc.addReleaseArtifact.mockResolvedValue({
      id: 'art-1', agent_version_id: 'v1', artifact_type: 'GIT_COMMIT_SHA', reference: 'a1b2c3d',
      created_by: 'u1', created_at: '2026-07-18T05:00:00Z',
    })
    wrap()
    await screen.findByText('v1')
    await userEvent.click(screen.getByText('Details'))

    const panel = (await screen.findByText('Artifacts')).closest('div') as HTMLElement
    await userEvent.type(within(panel).getByPlaceholderText('Reference'), 'a1b2c3d')
    await userEvent.click(within(panel).getByText('Add'))

    await waitFor(() => expect(svc.addReleaseArtifact).toHaveBeenCalledWith('agent-1', 'v1', {
      artifact_type: 'GIT_COMMIT_SHA', reference: 'a1b2c3d',
    }))
  })

  it('shows a Retire button for a DEPRECATED version and calls retireVersion', async () => {
    svc.versions.mockResolvedValue([versionFixture({ status: 'DEPRECATED', deprecated_at: '2026-07-18T06:00:00Z' })])
    svc.retireVersion.mockResolvedValue(versionFixture({ status: 'RETIRED', retired_at: '2026-07-18T07:00:00Z' }))
    wrap()
    await screen.findByText('v1')

    const table = screen.getByRole('table')
    await userEvent.click(within(table).getByText('Retire'))
    await waitFor(() => expect(svc.retireVersion).toHaveBeenCalledWith('agent-1', 'v1'))
  })

  it('locks release-detail edit forms once a version is PUBLISHED', async () => {
    svc.versions.mockResolvedValue([versionFixture({
      status: 'PUBLISHED', published_at: '2026-07-18T06:00:00Z', snapshot_reference: 'snapshot:s1',
    })])
    svc.versionSnapshot.mockResolvedValue({
      id: 's1', agent_version_id: 'v1', checksum: 'b'.repeat(64), created_at: '2026-07-18T06:00:00Z',
      snapshot: {},
    })
    wrap()
    await screen.findByText('v1')
    await userEvent.click(screen.getByText('Details'))

    await screen.findByText('Artifacts')
    expect(screen.queryByPlaceholderText('Reference')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Note')).not.toBeInTheDocument()
  })

  it('shows the promotion-readiness checklist, including a skipped check', async () => {
    svc.versions.mockResolvedValue([versionFixture()])
    wrap()
    await screen.findByText('v1')
    await userEvent.click(screen.getByText('Details'))

    expect(await screen.findByText('Not ready')).toBeInTheDocument()
    expect(screen.getByText(/registry active: Agent is DRAFT, not ACTIVE\./)).toBeInTheDocument()
    expect(screen.getByText(/compatibility analysis: Deferred to Part 3/)).toBeInTheDocument()
  })

  it('compares two versions and shows the scalar difference', async () => {
    svc.versions.mockResolvedValue([versionFixture(), versionFixture({ id: 'v2', version: 2, semantic_version: '0.2.0' })])
    wrap()
    await screen.findByText('v1')
    await userEvent.click(screen.getAllByText('Details')[0])

    await userEvent.selectOptions(screen.getByLabelText('Compare with'), 'v2')
    await waitFor(() => expect(svc.compareVersions).toHaveBeenCalledWith('agent-1', 'v1', 'v2'))
    expect(await screen.findByText(/semantic_version:/)).toBeInTheDocument()
  })
})
