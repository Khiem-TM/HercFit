export interface UserProfile {
  id: string
  email: string
  fullname: string
  nick_name: string | null
  avatar_url: string | null
  age: number | null
  /** Giới tính sinh học tuỳ chọn, chỉ dùng cho phương trình năng lượng (BMR). */
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
  /** Mẫu từ thiết bị (source GOOGLE_HEALTH) có thể chỉ mang chiều cao hoặc mỡ cơ thể. */
  weight_kg: number | null
  height_cm: number | null
  body_fat_pct: number | null
  muscle_mass_kg: number | null
  /** Vòng ngực / eo / hông (cm), chỉ có trong HercFit (Google không có). */
  chest_cm?: number | string | null
  waist_cm?: number | string | null
  hip_cm?: number | string | null
  recorded_at: string
  additional_metrics: Record<string, unknown>
  source?: 'MANUAL' | 'GOOGLE_HEALTH'
}

export type HealthConnectionStatus = 'ACTIVE' | 'NEEDS_REAUTH' | 'REVOKED' | 'ERROR'

/** Cột thập phân được tuần tự hoá thành chuỗi JSON để giữ độ chính xác. */
export type Numeric = number | string | null

export type ValueSource = 'DECLARED' | 'MEASURED' | 'PROVIDER' | 'DERIVED'

export interface ProfileValue {
  value: number | string | null
  source: ValueSource
  observed_at: string | null
  label: string | null
}

/** GET /api/health/profile: giá trị khai báo, đo được và suy ra kèm nguồn. */
export interface HealthProfile {
  as_of: string
  timezone: string
  connected: boolean
  age: ProfileValue | null
  sex: ProfileValue | null
  height_cm: ProfileValue | null
  weight_kg: ProfileValue | null
  body_fat_pct: ProfileValue | null
  bmi: ProfileValue | null
  resting_hr_bpm: ProfileValue | null
  max_hr_bpm: ProfileValue | null
  hrv_ms: ProfileValue | null
  vo2_max: ProfileValue | null
  activity_level: ProfileValue | null
  observed_activity_level: ProfileValue | null
  steps_avg_7d: number | null
  steps_avg_28d: number | null
  active_minutes_7d: number | null
  sleep_avg_minutes_7d: number | null
  worn_days_28d: number
  missing_fields: string[]
  conflicts: string[]
}

/** Nhịp tim trong một giờ (GET /api/health/heart-rate/hourly); giờ không có mẫu thì không có dòng. */
export interface HeartRateHour {
  start_at: string
  end_at: string
  hour: number
  bpm_avg: Numeric
  bpm_min: number | null
  bpm_max: number | null
}

export interface DailyHealth {
  id: string
  local_date: string
  source: string
  timezone: string
  steps: number | null
  distance_m: Numeric
  floors: number | null
  active_minutes: number | null
  active_minutes_by_level: Record<string, number>
  active_zone_minutes: number | null
  total_kcal: Numeric
  active_kcal: Numeric
  resting_hr_bpm: number | null
  hr_avg_bpm: Numeric
  hr_min_bpm: number | null
  hr_max_bpm: number | null
  hrv_ms: Numeric
  spo2_avg_pct: Numeric
  respiratory_rate: Numeric
  vo2_max: Numeric
  hydration_ml: Numeric
  sleep_minutes: number | null
  skin_temp_delta_c: Numeric
}

export interface SleepSession {
  id: string
  start_at: string
  end_at: string
  local_date: string
  sleep_type: string | null
  is_main: boolean
  is_nap: boolean
  minutes_asleep: number | null
  minutes_awake: number | null
  minutes_in_period: number | null
  minutes_to_fall_asleep: number | null
  deep_minutes: number | null
  light_minutes: number | null
  rem_minutes: number | null
  awake_minutes: number | null
  efficiency_pct: Numeric
  /** Reconcile không trả thiết bị ghi; chỉ biết điểm có phải do HercFit ghi hay không. */
  data_source: { written_by_hercfit?: boolean }
}

export interface DeviceWorkout {
  id: string
  started_at: string
  ended_at: string
  local_date: string
  exercise_type: string | null
  display_name: string | null
  active_seconds: number | null
  energy_kcal: Numeric
  distance_m: Numeric
  steps: number | null
  avg_hr_bpm: number | null
  active_zone_minutes: number | null
  hr_zone_seconds: Record<string, number>
  elevation_gain_m: Numeric
  avg_speed_mps: Numeric
  run_vo2_max: Numeric
  /** Reconcile không trả thiết bị ghi; chỉ biết điểm có phải do HercFit ghi hay không. */
  data_source: { written_by_hercfit?: boolean }
}

export interface HealthSample {
  id: string
  sample_type: 'BLOOD_GLUCOSE' | 'CORE_BODY_TEMPERATURE'
  measured_at: string
  value: Numeric
  unit: string
  details: Record<string, string>
}

/** GET /api/health/overview: phân tích tất định trên các ngày đã chọn. */
export interface HealthOverview {
  start_date: string
  end_date: string
  timezone: string
  connected: boolean
  activity: {
    days_with_data: number; steps_avg: number | null; steps_avg_7d: number | null; steps_trend_pct: number | null
    distance_km_avg: number | null; active_minutes_week: number | null; meets_who_guideline: boolean | null
    active_zone_minutes_week: number | null; total_kcal_avg: number | null; active_kcal_avg: number | null
    observed_level: string | null; workouts: number; workout_minutes: number; workout_types: Record<string, number>
  }
  sleep: {
    nights: number; avg_minutes: number | null; avg_minutes_7d: number | null; recommended_hours: [number, number]
    nights_below_recommended: number; deep_pct: number | null; rem_pct: number | null; efficiency_pct: number | null
    bedtime_stdev_minutes: number | null; last_night: SleepSession | null
  }
  recovery: {
    resting_hr_7d: number | null; resting_hr_baseline: number | null; resting_hr_elevated: boolean | null
    hrv_7d: number | null; hrv_baseline: number | null; hrv_suppressed: boolean | null
    spo2_avg: number | null; respiratory_rate_avg: number | null; signals: string[]
  }
  energy: {
    complete_days: number; intake_kcal_avg: number | null; device_expenditure_kcal_avg: number | null
    balance_kcal_avg: number | null; weight_change_kg: number | null; note: string | null
  }
  notes: string[]
}

/** Phần của GET /api/progress mà phần sức khoẻ đọc (lượng ăn đã ghi so với mức tiêu hao của thiết bị). */
export interface ProgressDay {
  date: string
  meal_count: number
  calories_in: { actual: Numeric; known_total: Numeric; missing_count: number }
  calories_out_actual: Numeric
}

/** GET /api/integrations/google-health: không bao giờ chứa token của nhà cung cấp. */
export interface HealthConnection {
  provider: string
  configured: boolean
  connected: boolean
  status: HealthConnectionStatus | null
  account_email: string | null
  granted_scopes: string[]
  missing_scopes: string[]
  share_with_assistant: boolean
  share_sensitive_with_assistant: boolean
  consented_at: string | null
  timezone: string | null
  provider_profile: Record<string, string | number>
  last_sync_at: string | null
  last_success_at: string | null
  last_error_code: string | null
  /** Số điểm đang lưu theo loại dữ liệu Google (steps, sleep, exercise...). */
  records: Record<string, number>
  /** Trạng thái đọc từng loại: khoảng ngày đã đọc trọn và lỗi của lần đọc gần nhất. */
  types: Record<string, HealthTypeStatus>
  /** Nhóm dữ liệu đang đồng bộ (true) và tần suất đồng bộ nền. */
  sync_groups?: Partial<Record<SyncGroup, boolean>>
  sync_frequency?: SyncFrequency
}

export type SyncGroup = 'sleep' | 'rhr' | 'hrv' | 'steps' | 'body'
export type SyncFrequency = 'hourly' | 'open' | 'manual'

export interface HealthTypeStatus {
  from?: string | null
  through?: string | null
  error?: string | null
}

/** Một lần đo: cần ít nhất một số đo; đo lại vòng eo không phải là cân lại. */
export interface BodyMetricCreatePayload {
  weight_kg?: number | null
  height_cm?: number | null
  body_fat_pct?: number | null
  muscle_mass_kg?: number | null
  chest_cm?: number | null
  waist_cm?: number | null
  hip_cm?: number | null
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
  /** Khoá lạc quan cho PATCH /api/goals/{id}. */
  version_id?: number
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
  /** Bản xem trước văn bản do server dựng (tên tool + JSON). */
  preview: string
  revision: number
  expires_at: string
  research_id?: string | null
  /** Kết quả chạy thử của server (MealRead / TrainingRead / TrainingPlanRead) hoặc một ứng viên catalog. */
  display?: Record<string, unknown> | null
}

export interface ClarifyOption {
  id: string
  label: string
  description?: string | null
  /** Chỉ từ bản ghi catalog trả về trong lượt này. */
  image_url?: string | null
  ref?: { kind: string; id: string } | null
  /** Gửi như tin nhắn tiếp theo của người dùng khi được chọn. */
  value: string
}

/** Các đơn vị khung nhập số có thể hỏi (NUMBER_UNITS của agent). */
export type NumberUnit =
  | 'kg' | 'g' | 'ml' | 'kcal' | 'phút' | 'giờ' | 'km' | 'cm' | '%' | 'bpm' | 'tuổi' | 'RPE' | 'bước' | 'buổi'
  | 'ngày' | 'tuần' | 'hiệp' | 'reps' | 'lần' | 'suất' | 'phần' | 'quả' | 'ly' | 'cốc' | 'chai' | 'lon' | 'hộp'
  | 'bát' | 'tô' | 'đĩa' | 'lát' | 'miếng' | 'cái'

/** Một giá trị chọn bằng bộ tăng giảm hoặc giá trị có sẵn trong [min, max]. */
export interface NumberFrame {
  unit: NumberUnit
  min: number
  max: number
  step: number
  default?: number | null
  presets?: number[]
}

/** Một ngày (ISO 'YYYY-MM-DD') chọn trên lịch hoặc từ mốc gợi ý trong [min, max]; khoảng và mốc do agent dựng. */
export interface DateFrame {
  min: string
  max: string
  default?: string | null
  presets?: { label: string; value: string }[]
}

/** Khung trên thẻ; mọi khung đều trả lời trên thẻ, không bao giờ bằng văn bản tự do gõ tay. */
export type ClarifyMode = 'single' | 'multiple' | 'quick_reply' | 'number' | 'date' | 'sets'

export interface ClarifyQuestion {
  id: string
  /** Chủ đề ngắn, đứng đầu câu trả lời trong tin nhắn được soạn. */
  label: string
  question: string
  /**
   * 'number' chọn một giá trị theo `number`, 'date' chọn một ngày theo `date_frame`. 'sets' sửa sets × reps × kg theo
   * từng bài tập: các bài đã chọn trong `for_questions`, hoặc các lựa chọn riêng của nó.
   */
  mode: ClarifyMode
  options: ClarifyOption[]
  /** Câu hỏi tuỳ chọn có thể bỏ qua. */
  required: boolean
  min_select: number
  max_select: number
  for_questions?: string[]
  /** Chỉ hỏi khi câu hỏi trước đó được trả lời bằng một trong các lựa chọn này. */
  show_if?: { question: string; option_ids: string[] } | null
  number?: NumberFrame | null
  date_frame?: DateFrame | null
}

/** Form để con người quyết định, hỏi từng câu một và trả lời gộp thành một tin nhắn. */
export interface Clarification {
  intro?: string | null
  questions: ClarifyQuestion[]
}

/** Món người dùng nói mà catalog không có món nào trùng tên: thẻ cho tìm món trong catalog hoặc tạo món riêng. */
export interface FoodGapItem {
  key: string
  query: string
  /** Lượng trong bản nháp của router (điền sẵn); null khi người dùng chưa nói. */
  quantity?: number | null
  unit?: FoodUnit | null
}

/** Đơn vị trong bản nháp của router: SERVING là số đếm (tô, cái, suất), quy ra g/ml theo portions của món. */
export type FoodUnit = 'G' | 'ML' | 'SERVING'
/** Đơn vị catalog tính dinh dưỡng và đơn vị ghi lượng ăn. */
export type MeasureUnit = 'G' | 'ML'

/** Khẩu phần hộ gia đình của món, đo bằng đơn vị của món, ví dụ "1 tô" = 500 G. */
export interface HouseholdPortion {
  label: string
  quantity: number | string
  unit: MeasureUnit
}

export interface FoodGap {
  items: FoodGapItem[]
  meal?: { name?: string | null; consumed_at?: string | null } | null
}

/** Lựa chọn trên thẻ món thiếu, gửi kèm tin nhắn tiếp theo (ChatRequest.food_choices). */
export interface FoodChoice {
  key: string
  food_id: string
  quantity: number
  unit: MeasureUnit
}

/** Gợi ý AI cho món riêng: đúng 4 chỉ số trên 100 g. */
export interface FoodNutrition {
  energy_kcal: number
  carbohydrate_g: number
  fat_g: number
  protein_g: number
}

/** Một bản ghi catalog trả về từ GET /api/foods (các trường thẻ dùng). */
export interface FoodRecord {
  id: string
  version_id: number
  name_vi: string
  name_en?: string | null
  serving_size?: string | number | null
  serving_unit: MeasureUnit
  energy_kcal?: string | number | null
  protein_g?: string | number | null
  carbohydrate_g?: string | number | null
  fat_g?: string | number | null
  portions?: HouseholdPortion[] | null
  image_url?: string | null
  source_type: 'SYSTEM' | 'CUSTOM'
}

/** Ảnh tra cứu từ web: chỉ hiển thị cho đến khi được nhập lên Cloudinary. */
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
  food_gap?: FoodGap | null
  illustrations?: Illustration[]
  sources: SourceItem[]
  tool_outputs: Record<string, unknown>[]
  /** Chế độ của lượt chạy; suggested_mode = 'plan' khi chế độ thường mời hỏi lại ở chế độ Plan. */
  mode?: ChatMode | null
  suggested_mode?: 'plan' | null
}

/** Nút "Plan" trên ô nhập: normal = ghi nhận dữ liệu; plan = tư vấn chuyên sâu, phân tích, lập kế hoạch tập. */
export type ChatMode = 'normal' | 'plan'

export interface ChatMessage {
  id: string
  role: 'human' | 'ai'
  content: string
  name?: string | null
  sources?: SourceItem[]
  pending_action?: PendingAction | null
  clarification?: Clarification | null
  /** Thẻ món thiếu (tìm món / tạo món riêng), chỉ trả lời được ở lượt needs_input mới nhất. */
  food_gap?: FoodGap | null
  illustrations?: Illustration[]
  /** Trợ lý mời hỏi lại câu trước ở chế độ Plan (chế độ thường không tư vấn). */
  suggested_mode?: 'plan' | null
  /** Tin nhắn người dùng gửi ở chế độ Plan. */
  mode?: ChatMode
  /**
   * Trạng thái chỉ ở client: 'streaming' khi token đang tới, 'stopped' sau khi người dùng huỷ, và 'confirmed' /
   * 'rejected' cho yêu cầu xác nhận mà người dùng đã trả lời.
   */
  status?: ChatStatus | 'streaming' | 'stopped' | 'confirmed' | 'rejected'
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

/** GET /api/nutrition/targets — mục tiêu tất định do backend tính. */
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

// ---- Google Health: ghi xuyên qua (/api/v2/health/records) -----------------------------------
/** Loại Google sở hữu mà HercFit ghi thẳng lên Google (buổi thể thao, số đo cơ thể, nước uống, giấc ngủ ghi tay). */
export type HealthRecordKind = 'exercise' | 'weight' | 'height' | 'body-fat' | 'hydration' | 'sleep'

/** Một điểm Google do HercFit vừa ghi; `pending` khi Google chưa trả điểm (lần đồng bộ sau mang về). */
export interface HealthRecordRead {
  id: string | null
  data_type: string
  local_date: string | null
  start_at: string | null
  end_at: string | null
  value: Record<string, unknown>
  written_by_hercfit: boolean
  pending: boolean
  derived: Record<string, unknown>
}

// ---- Đánh giá hằng ngày (/api/v2/health/daily-assessment) -----------------------------------
// API bỏ các trường null (exclude_none), nên mọi trường có thể thiếu đều là optional.
export type ReadinessState = 'ready' | 'steady' | 'ease_off' | 'recover' | 'needs_review' | 'insufficient_data'
export type ReadinessConfidence = 'high' | 'medium' | 'low'
export type ReasonKind = 'strain' | 'positive' | 'data' | 'review' | 'info'

export interface MetricReading {
  metric: string
  label: string
  unit: string
  value?: number
  measured_on?: string
  state: string
  baseline?: number
  baseline_mad?: number
  baseline_n: number
  delta?: number
  delta_pct?: number
  z?: number
  provider_relative?: boolean
}

export interface ReadinessTrend {
  metric: string
  label: string
  unit: string
  recent?: number
  recent_n: number
  baseline?: number
  baseline_n: number
  delta_pct?: number
  direction: 'up' | 'down' | 'flat' | 'unknown'
}

export interface ReadinessReason {
  code: string
  kind: ReasonKind
  metric?: string
  value?: number
  baseline?: number
  unit?: string
  delta?: number
  text: string
}

export interface SleepNight {
  date: string
  bedtime: string
  wake_time: string
  minutes_asleep?: number
  minutes_in_bed?: number
  efficiency_pct?: number
  minutes_to_fall_asleep?: number
  minutes_awake?: number
  deep_minutes?: number
  rem_minutes?: number
  light_minutes?: number
  deep_pct?: number
  rem_pct?: number
  light_pct?: number
  manual?: boolean
}

export interface SleepDetail {
  last_night?: SleepNight
  week: {
    nights: number
    need_minutes: number
    avg_minutes_asleep?: number
    debt_minutes?: number
    bedtime_sd_minutes?: number
    wake_sd_minutes?: number
  }
}

/** GET /api/v2/health/daily-assessment: chỉ số hôm nay so với nền cá nhân, giấc ngủ và độ sẵn sàng tất định. */
export interface DailyAssessment {
  date: string
  timezone: string
  algorithm_version: string
  state: ReadinessState
  label: string
  /** Điểm 0–100 do backend tính (readiness v3); null khi cần xem lại hoặc chưa đủ dữ liệu. */
  score?: number | null
  confidence: ReadinessConfidence
  summary: string
  reasons: ReadinessReason[]
  recommendations: { code: string; text: string }[]
  metrics: MetricReading[]
  trends: ReadinessTrend[]
  sleep?: SleepDetail
  load?: { yesterday?: number; acute_7d: number; chronic_weekly: number; acwr?: number; sessions_without_rpe: number }
  data_quality: { connected: boolean; last_sync_at?: string; stale: boolean; missing: string[]; baseline_days: number }
  method: string
  disclaimer: string
}

// ---- Thông báo trong ứng dụng (/api/v2/notifications) ---------------------------------------
/** alert/review/reminder/proposal được tạo mới; các loại còn lại chỉ còn trong thông báo cũ chưa hết hạn. */
export type NotificationKind = 'alert' | 'review' | 'reminder' | 'proposal' | 'briefing' | 'insight' | 'praise'
  | 'data_quality' | 'summary'

export interface AppNotification {
  id: string
  kind: NotificationKind
  code: string
  priority: number
  local_date: string
  title: string
  body: string
  payload: Record<string, unknown>
  created_at: string
  seen_at: string | null
  expires_at: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unread: number
}

export type AlertGroup = 'heart' | 'oxygen' | 'sleep' | 'weight' | 'nutrition' | 'activity'
export type AlertSeverity = 'info' | 'warn' | 'urgent'

export interface AlertSource { org: string; title: string; year: number; url: string; tier: 'byt' | 'who' | 'professional' }

/** payload của thông báo `alert`: luật, giá trị so với ngưỡng và nguồn (backend tính, LLM chỉ viết lời). */
export interface AlertPayload {
  severity: AlertSeverity
  group: AlertGroup
  rule: string
  features: {
    metric: string; unit: string; direction: 'high' | 'low'; value: number; threshold: number; window: string
    basis: string[]; evidence: { date: string; value: number }[]; sources: AlertSource[]
  }
  advice: string[]
  ask: string
}

export interface ReviewDimension {
  id: 'nutrition' | 'activity' | 'sleep' | 'recovery' | 'plan'
  label: string
  score: number | null
  rating: 'good' | 'fair' | 'poor' | 'missing'
  detail: string
}

/** payload của thông báo `review`: điểm do backend chấm, lời do LLM (hoặc code) viết. */
export interface ReviewPayload {
  review: { date: string; score: number | null; grade: string | null; dimensions: ReviewDimension[] }
  highlights: string[]
  improvements: string[]
  tomorrow_tip: string
  ask: string
}

/** enabled là consent "proactive" (mặc định tắt); các trường còn lại là tuỳ chọn. */
export interface NotificationPreferences {
  enabled: boolean
  /** Cảnh báo khi chỉ số vượt ngưỡng của bộ luật y tế, theo nhóm. */
  health_alerts: boolean
  alert_groups: AlertGroup[]
  /** Đánh giá chất lượng ngày: tối đa một lần mỗi ngày, từ giờ đã chọn. */
  daily_review: boolean
  daily_review_time: string
  quiet_hours: { enabled: boolean; start: string; end: string }
  max_per_day: number
  /** Đề xuất điều chỉnh buổi tập khi điểm sẵn sàng dưới ngưỡng (người dùng luôn xác nhận qua trợ lý). */
  adjust_on_low_readiness: boolean
  readiness_threshold: 50 | 60 | 70
  /** Buổi đã qua ngày mà chưa ghi nhận: hỏi trước, tự dời sang ngày trống gần nhất, hoặc không làm gì. */
  missed_session: 'ask' | 'auto' | 'none'
  workout_reminder: boolean
  workout_reminder_time: string
  timezone?: string
}
