import type { SystemHealth } from '@/types'
import { apiClient } from './apiClient'

/** System/operational API (Phase 3.1 /system/*). */
export const systemService = {
  async getHealth(): Promise<SystemHealth> {
    const { data } = await apiClient.get<SystemHealth>('/system/health')
    return data
  },
}
