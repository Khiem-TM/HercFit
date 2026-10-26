export interface UserProfile {
  id: string
  email: string
  fullname: string
  nick_name: string | null
  avatar_url: string | null
  age: number | null
  /** Optional biological sex, used only by the energy (BMR) equation. */
  sex?: 'MALE' | 'FEMALE' | null
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
  sex?: 'MALE' | 'FEMALE' | null
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
  session_id?: string
  user_id?: string
  tool: string
  payload: Record<string, unknown>
  /** Server-rendered text preview (tool name + JSON). */
  preview: string
  revision: number
  expires_at: string
  research_id?: string | null
  /** Server dry-run (MealRead / TrainingRead / TrainingPlanRead) or a catalog candidate. */
  display?: Record<string, unknown> | null
}

export interface ClarifyOption {
  id: string
  label: string
  description?: string | null
  /** Only from catalog records returned in this turn. */
  image_url?: string | null
  ref?: { kind: string; id: string } | null
  /** Sent as the next user message when chosen. */
  value: string
}

export interface ClarifyQuestion {
  id: string
  /** Short topic, prefixes the answer in the composed reply. */
  label: string
  question: string
  /** 'text' has no options: typed answer only. */
  mode: 'single' | 'multiple' | 'quick_reply' | 'text'
  options: ClarifyOption[]
  allow_free_text: boolean
  free_text_hint?: string | null
  /** Optional questions can be skipped. */
  required: boolean
  min_select: number
  max_select: number
}

/** Human-in-the-loop form, asked one question at a time and answered as one message. */
export interface Clarification {
  intro?: string | null
  questions: ClarifyQuestion[]
}

/** Research picture from the web: display only until imported to Cloudinary. */
export interface Illustration {
  url: string
  description?: string | null
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
  clarification?: Clarification | null
  illustrations?: Illustration[]
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
  clarification?: Clarification | null
  illustrations?: Illustration[]
  /** Client-only states: 'streaming' while tokens arrive, 'stopped' after the user cancels. */
  status?: ChatStatus | 'streaming' | 'stopped'
  timestamp: string
}

export interface SessionSummary {
  session_id: string
  title: string
  last_message: string
  message_count: number
  status: string
  created_at: string
  last_interaction_at?: string | null
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

/** GET /api/nutrition/targets — deterministic targets computed by the backend. */
export interface NutritionTargets {
  status: 'ok' | 'incomplete_profile'
  missing: string[]
  inputs: {
    weight_kg: number | null
    height_cm: number | null
    age: number | null
    sex: string | null
    activity_level: string | null
    goal_type: string | null
    target_weight_kg: number | null
    target_date: string | null
    trend_weight_kg: number | null
  }
  bmr_kcal: number | null
  tdee_kcal: number | null
  target_kcal: number | null
  weekly_change_kg: number | null
  goal_type: string
  activity_factor: number | null
  macros: { protein_g: number; fat_g: number; carbohydrate_g: number; fiber_g: number; protein_g_per_kg: number } | null
  adaptive: {
    status: 'ok' | 'insufficient_data'
    expenditure_kcal: number | null
    average_intake_kcal: number | null
    trend_change_kg: number | null
    span_days: number
    complete_intake_days: number
    weight_points: number
    reasons: string[]
  }
  today: { date: string; meal_count: number; energy_kcal: number; protein_g: number; missing_values: number; remaining_kcal: number | null }
  weight_trend: { date: string; weight_kg: number; trend_kg: number }[]
  warnings: string[]
  method: Record<string, string>
}
