import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount and clear the DOM between tests (no globals → register cleanup ourselves).
afterEach(() => cleanup())
