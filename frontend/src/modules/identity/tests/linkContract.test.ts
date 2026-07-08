import { describe, expect, it } from 'vitest'

import { ROUTES } from '@/constants/routes'

/**
 * Cross-layer contract.
 *
 * The backend emails `{APP_BASE_URL}/invite/{token}` and
 * `{APP_BASE_URL}/verify-email/{token}` (`identity/email/service.py`). If either side
 * renames its path, every invitation and verification link in flight lands on a 404 —
 * and no test on either side alone would notice. `backend/tests/identity/registration/
 * test_link_contract.py` pins the other half.
 */
describe('onboarding link contract', () => {
  it('matches the invitation link the backend emails', () => {
    expect(ROUTES.ACCEPT_INVITATION).toBe('/invite/:token')
  })

  it('matches the verification link the backend emails', () => {
    expect(ROUTES.VERIFY_EMAIL).toBe('/verify-email/:token')
  })
})
