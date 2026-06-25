import type { ID, User } from '@/types'
import { httpClient } from './httpClient'

/** Users API (Phase 1 /users). */
export const userService = {
  async list(): Promise<User[]> {
    const { data } = await httpClient.get<User[]>('/users')
    return data
  },

  async get(id: ID): Promise<User> {
    const { data } = await httpClient.get<User>(`/users/${id}`)
    return data
  },
}
