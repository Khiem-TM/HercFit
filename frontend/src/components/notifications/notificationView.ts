import type { AlertPayload, AlertSeverity, ReviewDimension, ReviewPayload } from '@/types/api'

/** Dữ liệu hiển thị của cảnh báo và đánh giá ngày (hàm thuần, test được không cần DOM). */
export const SEVERITY_LABELS: Record<AlertSeverity, string> = { info: 'Thông tin', warn: 'Lưu ý', urgent: 'Khẩn' }

const number = (value: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(value)

export interface AlertView {
  severity: AlertSeverity
  label: string
  metric: string
  value: string
  threshold: string
  window: string
  basis: string[]
  advice: string[]
  sources: AlertPayload['features']['sources']
}

export function alertView(payload: AlertPayload | undefined): AlertView | null {
  const features = payload?.features
  if (!payload || !features) return null
  const unit = !features.unit ? '' : features.unit === '%' ? '%' : ` ${features.unit}`
  return {
    severity: payload.severity, label: SEVERITY_LABELS[payload.severity] ?? SEVERITY_LABELS.info,
    metric: features.metric, value: number(features.value) + unit, threshold: number(features.threshold) + unit,
    window: features.window, basis: features.basis ?? [], advice: payload.advice ?? [], sources: features.sources ?? [],
  }
}

export interface ReviewView {
  score: number | null
  grade: string | null
  dimensions: ReviewDimension[]
  highlights: string[]
  improvements: string[]
  tip: string
}

export function reviewView(payload: ReviewPayload | undefined): ReviewView | null {
  if (!payload?.review) return null
  return {
    score: payload.review.score, grade: payload.review.grade,
    dimensions: payload.review.score === null ? [] : payload.review.dimensions,
    highlights: payload.highlights ?? [], improvements: payload.improvements ?? [], tip: payload.tomorrow_tip ?? '',
  }
}
