export interface UserProfile {
  id: string
  email: string
  fullname: string
  nick_name: string | null
  avatar_url: string | null
  age: number | null
  personal_info: Record<string, unknown>
  email_verified: boolean
  last_login_at: string | null
  is_onboarding: boolean
}

export interface UserUpdatePayload {
  fullname?: string
  nick_name?: string | null
  avatar_url?: string | null
  age?: number | null
  personal_info?: Record<string, unknown>
}

export interface BodyMetricRead {
  id: string
  user_id: string
  weight_kg: number
  height_cm: number | null
  body_fat_pct: number | null
  muscle_mass_kg: number | null
  recorded_at: string
  additional_metrics: Record<string, unknown>
}

export interface BodyMetricCreatePayload {
  weight_kg: number
  height_cm?: number | null
  body_fat_pct?: number | null
  muscle_mass_kg?: number | null
  additional_metrics?: Record<string, unknown>
}

export interface GoalRead {
  id: string
  user_id: string
  title: string
  start_date: string
  target_date: string | null
  description: string | null
  goal_types: string[]
  targets: Record<string, unknown>
  context: Record<string, unknown>
  status: string
}

export interface SourceItem {
  title: string
  url: string
  content: string
}

export interface PendingAction {
  action_id: string
  session_id: string
  user_id: string
  tool: string
  payload: Record<string, unknown>
  preview: Record<string, unknown>
  revision: number
  expires_at: string
  research_id?: string | null
}

export type ChatStatus =
  | 'completed'
  | 'needs_input'
  | 'pending_confirmation'
  | 'failed'

export interface ChatResponse {
  session_id: string
  run_id: string
  reply: string
  status: ChatStatus
  intent?: string | null
  pending_action?: PendingAction | null
  sources: SourceItem[]
  tool_outputs: Record<string, unknown>[]
}

export interface ChatMessage {
  id: string
  role: 'human' | 'ai'
  content: string
  name?: string | null
  sources?: SourceItem[]
  pending_action?: PendingAction | null
  status?: ChatStatus
  timestamp: string
}

export interface SessionSummary {
  session_id: string
  title: string
  last_message: string
  message_count: number
  status: string
  created_at: string
}


export interface GoalCreatePayload {
  title: string
  start_date: string
  target_date?: string
  goal_types: string[]
  targets: Record<string, { unit: string; operator: 'eq'; value: number; baseline?: number }>
}
export interface OnboardingPayload extends UserUpdatePayload {
  body_metric?: BodyMetricCreatePayload
  goal?: GoalCreatePayload
}
