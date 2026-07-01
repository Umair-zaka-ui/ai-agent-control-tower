import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { IdentityStatusBadge } from '../components/IdentityStatusBadge'
import { canManageIdentity, canViewIdentity } from '../utils/permissions'

describe('identity permissions', () => {
  it('gates viewing on user.view and managing on user.create', () => {
    expect(canViewIdentity(['user.view'])).toBe(true)
    expect(canViewIdentity([])).toBe(false)
    expect(canManageIdentity(['user.create'])).toBe(true)
    expect(canManageIdentity(['user.view'])).toBe(false)
  })
})

describe('IdentityStatusBadge', () => {
  it('renders active and suspended states', () => {
    const { rerender } = render(<IdentityStatusBadge active />)
    expect(screen.getByText('Active')).toBeInTheDocument()
    rerender(<IdentityStatusBadge active={false} />)
    expect(screen.getByText('Suspended')).toBeInTheDocument()
  })
})
