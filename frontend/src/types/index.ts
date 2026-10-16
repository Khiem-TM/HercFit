// =============================================================================
// HercFit TypeScript Interfaces & Types (Skeleton)
// TODO: Định nghĩa chi tiết các kiểu dữ liệu đồng bộ với Backend Schemas
// =============================================================================

export interface UserProfile {
  user_id: string
  full_name: string
  age?: number | null
  height_cm?: number | null
  fitness_goal?: string | null
}

export interface BodyMetric {
  metric_id: string
  user_id: string
  weight_kg: number
  body_fat_pct?: number | null
  muscle_mass_kg?: number | null
  recorded_at: string
}

export interface Meal {
  meal_id: string
  user_id: string
  name: string
  calories: number
  protein_g: number
  carbs_g: number
  fat_g: number
  logged_at: string
}

export interface WorkoutPlan {
  plan_id: string
  user_id: string
  title: string
  days_per_week: number
  created_at: string
}

export interface WorkoutSession {
  session_id: string
  user_id: string
  workout_name: string
  duration_minutes: number
  calories_burned?: number | null
  performed_at: string
}

export interface ChatMessage {
  type: 'human' | 'ai' | 'tool'
  content: string
  run_id?: string
}
