import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Meal, WorkoutPlan, WorkoutSession } from '@/types'

/**
 * Store quản lý dữ liệu Tập luyện, Dinh dưỡng và Thói quen (Workouts, Nutrition, Habits).
 * TODO: Kết nối với workoutsApi và nutritionApi.
 */
export const useFitnessStore = defineStore('fitness', () => {
  const meals = ref<Meal[]>([])
  const workoutPlans = ref<WorkoutPlan[]>([])
  const workoutSessions = ref<WorkoutSession[]>([])
  const isLoading = ref(false)

  return {
    meals,
    workoutPlans,
    workoutSessions,
    isLoading,
  }
})
