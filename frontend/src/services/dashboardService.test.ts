import { describe, expect, it, vi, beforeEach } from 'vitest'

import { apiClient } from './apiClient'
import { dashboardService } from './dashboardService'

vi.mock('./apiClient', () => ({
  apiClient: { get: vi.fn() },
}))

const mockGet = vi.mocked(apiClient.get)

describe('dashboardService', () => {
  beforeEach(() => mockGet.mockReset())

  it('requests the summary endpoint', async () => {
    mockGet.mockResolvedValue({ data: { agents: 3 } })
    await dashboardService.getSummary()
    expect(mockGet).toHaveBeenCalledWith('/dashboard/summary')
  })

  it('requests activity with a days param', async () => {
    mockGet.mockResolvedValue({ data: [] })
    await dashboardService.getActivity(7)
    expect(mockGet).toHaveBeenCalledWith('/dashboard/activity', { params: { days: 7 } })
  })

  it('requests the risk-trend endpoint with days', async () => {
    mockGet.mockResolvedValue({ data: [] })
    await dashboardService.getRiskTrend(30)
    expect(mockGet).toHaveBeenCalledWith('/dashboard/risk-trend', { params: { days: 30 } })
  })

  it('requests recent audit logs with a limit', async () => {
    mockGet.mockResolvedValue({ data: [] })
    await dashboardService.getRecentAuditLogs(6)
    expect(mockGet).toHaveBeenCalledWith('/audit-logs', { params: { limit: 6 } })
  })
})
