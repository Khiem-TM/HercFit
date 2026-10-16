import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { BodyMetric, UserProfile } from '@/types'

/**
 * Store quản lý thông tin người dùng và chỉ số cơ thể (Users & Body Metrics).
 * TODO: Kết nối với usersApi.
 */
export const useUserStore = defineStore('user', () => {
  const profile = ref<UserProfile | null>(null)
  const metrics = ref<BodyMetric[]>([])
  const isLoading = ref(false)

  async function fetchProfile() {
    // TODO: Gọi API lấy thông tin hồ sơ
  }

  return {
    profile,
    metrics,
    isLoading,
    fetchProfile,
  }
})
