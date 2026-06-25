import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '@/services/apiClient'
import { agentService } from '../services/agentService'

vi.mock('@/services/apiClient', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const api = vi.mocked(apiClient)

describe('agentService', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.post.mockReset()
    api.put.mockReset()
    api.patch.mockReset()
    api.delete.mockReset()
  })

  it('lists agents with the full param set', async () => {
    api.get.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 25 } })
    const params = { search: 'bot', page: 2, page_size: 25, sort_by: 'name' as const, sort_dir: 'asc' as const }
    await agentService.list(params)
    expect(api.get).toHaveBeenCalledWith('/agents', { params })
  })

  it('creates an agent', async () => {
    api.post.mockResolvedValue({ data: { id: '1' } })
    await agentService.create({ name: 'A', agent_type: 'custom' })
    expect(api.post).toHaveBeenCalledWith('/agents', { name: 'A', agent_type: 'custom' })
  })

  it('updates an agent via PUT', async () => {
    api.put.mockResolvedValue({ data: { id: '1' } })
    await agentService.update('1', { department: 'R&D' })
    expect(api.put).toHaveBeenCalledWith('/agents/1', { department: 'R&D' })
  })

  it('changes status via PATCH', async () => {
    api.patch.mockResolvedValue({ data: { id: '1' } })
    await agentService.updateStatus('1', 'ARCHIVED')
    expect(api.patch).toHaveBeenCalledWith('/agents/1/status', { status: 'ARCHIVED' })
  })

  it('deletes an agent', async () => {
    api.delete.mockResolvedValue({ data: undefined })
    await agentService.remove('1')
    expect(api.delete).toHaveBeenCalledWith('/agents/1')
  })

  it('fetches per-agent stats', async () => {
    api.get.mockResolvedValue({ data: {} })
    await agentService.stats('1')
    expect(api.get).toHaveBeenCalledWith('/agents/1/stats')
  })
})
