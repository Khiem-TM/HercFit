/**
 * Thẻ món thiếu: catalog không có món nào trùng tên món người dùng nói. Người dùng tìm món trong catalog
 * (GET /api/foods?search=, tìm không dấu + xếp hạng có dấu của backend) hoặc tạo món riêng trên 100 g
 * (POST /api/foods, ảnh qua PUT /api/media/foods/{id}/image). Nút gợi ý điền 4 chỉ số từ một truy vấn web
 * (POST /api/v1/chat/food-nutrition). Lựa chọn được gửi kèm tin nhắn tiếp theo dưới dạng food_choices; agent dựng
 * bản xem trước bữa ăn bằng code và người dùng vẫn xác nhận trên thẻ xác nhận.
 */
import type { FoodChoice, FoodGap, FoodGapItem, FoodNutrition, FoodRecord, FoodUnit, HouseholdPortion, MeasureUnit } from '@/types/api'
import { type Fetcher, HealthApiError } from '@/features/health-integration/api'

/** Khớp kiểm tra của server: FoodChoice.quantity trong (0, 5000]; số liệu trên 100 g như kiểm tra của gợi ý AI. */
export const LIMITS = { kcal: 900, macro: 100, quantity: 5000, name: 120 } as const
const UNITS: FoodUnit[] = ['G', 'ML', 'SERVING']

export interface QuantityUnit {
  unit: MeasureUnit
  label: string
  step: number
}

/** Lượng ăn luôn ghi bằng gam hoặc mililít, đúng đơn vị bản ghi tính dinh dưỡng. */
export function unitFor(food: Pick<FoodRecord, 'serving_unit'>): QuantityUnit {
  if (food.serving_unit === 'ML') return { unit: 'ML', label: 'ml', step: 10 }
  return { unit: 'G', label: 'g', step: 10 }
}

/** Khẩu phần hộ gia đình đầu tiên đo bằng đơn vị của món ("1 tô" = 500 g), hoặc null. */
export function householdPortion(food: Pick<FoodRecord, 'serving_unit' | 'portions'>): { label: string; quantity: number } | null {
  const portion = (food.portions ?? []).find((p: HouseholdPortion) => p.unit === food.serving_unit)
  const quantity = portion ? number(portion.quantity) : null
  return portion && quantity !== null && quantity > 0 ? { label: portion.label, quantity } : null
}

/** Lượng g/ml điền sẵn từ bản nháp của router: cùng đơn vị thì giữ nguyên, "1 tô" (SERVING) quy ra theo khẩu phần. */
export function draftQuantity(item: FoodGapItem, food: Pick<FoodRecord, 'serving_unit' | 'portions'>): number | null {
  if (typeof item.quantity !== 'number' || item.quantity <= 0) return null
  if (item.unit === food.serving_unit) return item.quantity
  const portion = item.unit === 'SERVING' ? householdPortion(food) : null
  return portion ? Math.round(item.quantity * portion.quantity * 10) / 10 : null
}

export function validQuantity(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= LIMITS.quantity
}

function number(value: unknown): number | null {
  const parsed = typeof value === 'string' && value.trim() ? Number(value) : value
  return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null
}

/** "250 kcal / 100 g" theo đúng cách bản ghi tính dinh dưỡng. */
export function energyLabel(food: FoodRecord): string {
  const kcal = number(food.energy_kcal)
  const size = number(food.serving_size)
  const basis = `${size ?? 100} ${food.serving_unit === 'ML' ? 'ml' : 'g'}`
  return kcal === null ? 'chưa rõ kcal' : `${Math.round(kcal)} kcal / ${basis}`
}

export interface CustomFoodForm {
  name: string
  energy_kcal: number | null
  carbohydrate_g: number | null
  fat_g: number | null
  protein_g: number | null
  /** Số gram đã ăn. */
  grams: number | null
}

/** Form món riêng điền sẵn tên người dùng nói (viết hoa chữ đầu như tên món trong catalog). */
export function emptyCustomForm(name: string, item?: FoodGapItem): CustomFoodForm {
  const trimmed = name.trim()
  return { name: trimmed.charAt(0).toLocaleUpperCase('vi-VN') + trimmed.slice(1), energy_kcal: null, carbohydrate_g: null, fat_g: null, protein_g: null,
           grams: item ? draftQuantity(item, { serving_unit: 'G' }) : null }
}

/** Lỗi đầu tiên của form món riêng, hoặc null khi lưu được. Năng lượng bắt buộc; macro bỏ trống là chưa biết. */
export function customFoodError(form: CustomFoodForm): string | null {
  const name = form.name.trim()
  if (!name) return 'Nhập tên món.'
  if (name.length > LIMITS.name) return `Tên món tối đa ${LIMITS.name} ký tự.`
  const kcal = number(form.energy_kcal)
  if (kcal === null) return 'Nhập năng lượng (kcal trên 100 g).'
  if (kcal < 0 || kcal > LIMITS.kcal) return `Năng lượng trên 100 g phải trong khoảng 0–${LIMITS.kcal} kcal.`
  const macros = [form.carbohydrate_g, form.fat_g, form.protein_g].map(number)
  if (macros.some((value) => value !== null && (value < 0 || value > LIMITS.macro))) {
    return `Mỗi chất trên 100 g phải trong khoảng 0–${LIMITS.macro} g.`
  }
  if (macros.reduce((sum: number, value) => sum + (value ?? 0), 0) > LIMITS.macro) {
    return 'Tổng carb, chất béo và protein không thể vượt 100 g trên 100 g món.'
  }
  if (!validQuantity(number(form.grams))) return `Nhập số gram đã ăn (1–${LIMITS.quantity} g).`
  return null
}

/** Món riêng của người dùng, dinh dưỡng tính trên 100 g. */
export function customFoodPayload(form: CustomFoodForm, aiSuggested: boolean, aiEstimated = false): Record<string, unknown> {
  return {
    name_vi: form.name.trim(),
    serving_size: 100,
    serving_unit: 'G',
    energy_kcal: number(form.energy_kcal),
    carbohydrate_g: number(form.carbohydrate_g),
    fat_g: number(form.fat_g),
    protein_g: number(form.protein_g),
    data_quality: { entry: 'chat_food_card', basis: 'per_100g', ai_suggested: aiSuggested, ai_estimated: aiEstimated },
  }
}

/** Lựa chọn đã chốt cho một món thiếu, kèm phần hiển thị trên thẻ. */
export interface FoodPick extends FoodChoice {
  name: string
  label: string
  custom: boolean
}

function quantityText(value: number): string {
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(value)
}

export function pickText(pick: FoodPick): string {
  return `${pick.name}${pick.custom ? ' (món riêng)' : ''} · ${quantityText(pick.quantity)} ${pick.label}`
}

/** Tin nhắn hiển thị trong luồng chat khi gửi lựa chọn; server đọc food_choices chứ không đọc chữ này. */
export function summary(items: FoodGapItem[], picks: Record<string, FoodPick>): string {
  return items.filter((item) => picks[item.key]).map((item) => pickText(picks[item.key])).join('\n')
}

export function choices(picks: Record<string, FoodPick>): FoodChoice[] {
  return Object.values(picks).map(({ key, food_id, quantity, unit }) => ({ key, food_id, quantity, unit }))
}

/** Thẻ hợp lệ từ server, hoặc null (thẻ sai dạng không bao giờ được vẽ). */
export function normalizeFoodGap(raw: unknown): FoodGap | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  const items = (Array.isArray(data.items) ? data.items : []).flatMap((value): FoodGapItem[] => {
    if (!value || typeof value !== 'object') return []
    const item = value as Record<string, unknown>
    if (typeof item.key !== 'string' || !item.key || typeof item.query !== 'string' || !item.query.trim()) return []
    const unit = UNITS.includes(item.unit as FoodUnit) ? (item.unit as FoodUnit) : null
    return [{ key: item.key, query: item.query.trim(), quantity: validQuantity(item.quantity) ? item.quantity : null, unit }]
  }).slice(0, 5)
  if (!items.length) return null
  const meal = data.meal && typeof data.meal === 'object' ? data.meal as Record<string, unknown> : null
  return {
    items,
    meal: meal ? { name: typeof meal.name === 'string' ? meal.name : null,
                   consumed_at: typeof meal.consumed_at === 'string' ? meal.consumed_at : null } : null,
  }
}

async function failure(response: Response, fallback: string): Promise<HealthApiError> {
  try {
    const detail = (await response.json())?.detail
    if (typeof detail === 'string') return new HealthApiError(detail, response.status)
  } catch { /* thân lỗi không phải JSON */ }
  return new HealthApiError(fallback, response.status)
}

export function createFoodGapApi(fetcher: Fetcher) {
  async function call<T>(url: string, init: RequestInit | undefined, fallback: string): Promise<T> {
    const response = await fetcher(url, init)
    if (!response.ok) throw await failure(response, fallback)
    return (response.status === 204 ? undefined : await response.json()) as T
  }
  return {
    /** Tìm trong catalog (món hệ thống và món riêng của người dùng), xếp theo độ khớp. */
    search: (query: string, signal?: AbortSignal) =>
      call<FoodRecord[]>(`/api/foods?${new URLSearchParams({ search: query.trim(), limit: '8' })}`, { signal },
        'Không tìm được món trong danh mục.'),
    /** Gợi ý AI: 4 chỉ số trên 100 g, hoặc lỗi (404 không có số liệu đáng tin, 503 tạm thời không dùng được). */
    suggest: (name: string) => call<FoodNutrition>('/api/v1/chat/food-nutrition', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }),
    }, 'Chưa gợi ý được số liệu; bạn nhập giúp nhé.'),
    create: (payload: Record<string, unknown>) => call<FoodRecord>('/api/foods', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    }, 'Không lưu được món riêng.'),
    uploadImage: (food: Pick<FoodRecord, 'id' | 'version_id'>, file: File) => {
      const form = new FormData()
      form.append('file', file)
      form.append('expected_version_id', String(food.version_id))
      return call<unknown>(`/api/media/foods/${encodeURIComponent(food.id)}/image`, { method: 'PUT', body: form },
        'Không lưu được ảnh.')
    },
  }
}

export type FoodGapApi = ReturnType<typeof createFoodGapApi>
