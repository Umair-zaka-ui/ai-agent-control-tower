import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { permissionGranted } from '../permissions'

// Mock the auth source so the provider has a deterministic permission set.
const mockAuth = vi.fn()
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => mockAuth() }))

const { PermissionProvider } = await import('../PermissionContext')
const { useCan } = await import('../hooks')
const { ProtectedComponent } = await import('../ProtectedComponent')

function withPerms(permissions: string[], children: ReactNode) {
  mockAuth.mockReturnValue({ permissions })
  return render(<PermissionProvider>{children}</PermissionProvider>)
}

describe('permissionGranted (wildcard matching)', () => {
  it('matches exact codes', () => {
    expect(permissionGranted(['agent.view'], 'agent.view')).toBe(true)
    expect(permissionGranted(['agent.view'], 'agent.delete')).toBe(false)
  })
  it('matches resource wildcards', () => {
    expect(permissionGranted(['agent.*'], 'agent.delete')).toBe(true)
    expect(permissionGranted(['agent.*'], 'policy.view')).toBe(false)
  })
  it('matches the global wildcard', () => {
    expect(permissionGranted(['*'], 'anything.at.all')).toBe(true)
  })
  it('denies when nothing matches', () => {
    expect(permissionGranted([], 'agent.view')).toBe(false)
  })
})

function Can({ code }: { code: string }) {
  return <span>{useCan(code) ? 'yes' : 'no'}</span>
}

describe('useCan', () => {
  it('reflects the provider permission set with wildcards', () => {
    withPerms(['agent.*'], <Can code="agent.create" />)
    expect(screen.getByText('yes')).toBeInTheDocument()
  })
  it('is false for an unheld permission', () => {
    withPerms(['policy.view'], <Can code="agent.create" />)
    expect(screen.getByText('no')).toBeInTheDocument()
  })
})

describe('ProtectedComponent', () => {
  it('renders children when permitted', () => {
    withPerms(['agent.create'], (
      <ProtectedComponent permission="agent.create">
        <button>Create agent</button>
      </ProtectedComponent>
    ))
    expect(screen.getByRole('button', { name: /create agent/i })).toBeInTheDocument()
  })
  it('renders the fallback when not permitted', () => {
    withPerms(['agent.view'], (
      <ProtectedComponent permission="agent.create" fallback={<span>denied</span>}>
        <button>Create agent</button>
      </ProtectedComponent>
    ))
    expect(screen.queryByRole('button', { name: /create agent/i })).not.toBeInTheDocument()
    expect(screen.getByText('denied')).toBeInTheDocument()
  })
})
