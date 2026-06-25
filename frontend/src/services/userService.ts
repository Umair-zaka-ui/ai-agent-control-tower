import type { ID, User } from '@/types'
import { apiClient } from './apiClient'

/** Users API (Phase 1 /users). */
export const userService = {
  async list(): Promise<User[]> {
    const { data } = await apiClient.get<User[]>('/users')
    return data
  },

  async get(id: ID): Promise<User> {
    const { data } = await apiClient.get<User>(`/users/${id}`)
    return data
  },
}
