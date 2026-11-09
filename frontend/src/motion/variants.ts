import type { MotionProps } from 'motion-v'
import { DISTANCE, DURATION, EASE, SPRING, STAGGER } from './tokens'

/** Kiểu theo props của <motion.*> trong motion-v (khác kiểu Variants của motion-dom). */
export type Variants = NonNullable<MotionProps['variants']>
export type Transition = NonNullable<MotionProps['transition']>

/**
 * Variants dùng chung cho motion-v. Mỗi variant có ba trạng thái initial/animate/exit (gọi bằng tên khi dùng
 * `:variants`, hoặc trải ra bằng `presence()`), nên hiệu ứng vào và ra luôn đi đôi (fadeIn/fadeOut...).
 * Giảm chuyển động: MotionConfig reduced-motion="user" ở App.vue tắt transform, chỉ giữ opacity.
 */
const out = (duration: number = DURATION.base): Transition => ({ duration, ease: EASE.out })
const leave = (duration: number = DURATION.fast): Transition => ({ duration, ease: EASE.in })

export const fade: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: out() },
  exit: { opacity: 0, transition: leave() },
}

export const slideUp: Variants = {
  initial: { opacity: 0, y: DISTANCE.sm },
  animate: { opacity: 1, y: 0, transition: out() },
  exit: { opacity: 0, y: DISTANCE.xs, transition: leave() },
}

export const slideDown: Variants = {
  initial: { opacity: 0, y: -DISTANCE.sm },
  animate: { opacity: 1, y: 0, transition: out() },
  exit: { opacity: 0, y: -DISTANCE.xs, transition: leave() },
}

export const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: SPRING.gentle },
  exit: { opacity: 0, scale: 0.98, transition: leave() },
}

/** Khung chứa danh sách/lưới: các con (staggerItem) hiện so le. */
export const staggerContainer = (step: number = STAGGER.base, delay = 0): Variants => ({
  initial: {},
  animate: { transition: { staggerChildren: step, delayChildren: delay } },
  exit: {},
})

export const staggerItem: Variants = {
  initial: { opacity: 0, y: DISTANCE.sm },
  animate: { opacity: 1, y: 0, transition: out(DURATION.slow) },
  exit: { opacity: 0, transition: leave() },
}

/** Modal: lớp phủ mờ dần, khung phóng nhẹ và trượt lên. */
export const modalScrim: Variants = fade
export const modalPanel: Variants = {
  initial: { opacity: 0, y: DISTANCE.md, scale: 0.985 },
  animate: { opacity: 1, y: 0, scale: 1, transition: SPRING.gentle },
  exit: { opacity: 0, y: DISTANCE.sm, scale: 0.99, transition: leave() },
}
export const modalTransition = { scrim: modalScrim, panel: modalPanel }

/** Chuyển trang (Landing ↔ Onboarding ↔ Chat): chỉ mờ dần, không transform, để phần tử position: fixed của trang
 * (header Landing, lớp nhiễu) không bị lệch trong lúc chuyển. */
export const pageTransition: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: out(DURATION.page) },
  exit: { opacity: 0, transition: leave(DURATION.fast) },
}

/** Section Landing hiện dần khi cuộn tới (một lần). Dùng: v-bind="reveal". */
export const reveal = {
  initial: { opacity: 0, y: DISTANCE.lg },
  whileInView: { opacity: 1, y: 0, transition: out(DURATION.slow * 1.6) },
  inViewOptions: { once: true, amount: 0.15 },
} as const

/** Lớp chi tiết trượt từ phải (Dashboard › Sẵn sàng/Buổi tập/Dinh dưỡng). */
export const sheetRight: Variants = {
  initial: { opacity: 0, x: DISTANCE.lg },
  animate: { opacity: 1, x: 0, transition: out(DURATION.slow) },
  exit: { opacity: 0, x: DISTANCE.md, transition: leave() },
}

/** Bước tiếp theo/quay lại (Onboarding): hướng truyền qua `custom` (1 tiến, -1 lùi). */
export const stepSlide: Variants = {
  initial: (direction: number) => ({ opacity: 0, x: DISTANCE.md * direction }),
  animate: { opacity: 1, x: 0, transition: out(DURATION.slow) },
  exit: (direction: number) => ({ opacity: 0, x: -DISTANCE.md * direction, transition: leave() }),
}

/** Popover (hộp thư chuông): mọc ra từ nút bấm. */
export const popover: Variants = {
  initial: { opacity: 0, scale: 0.96, y: -DISTANCE.xs },
  animate: { opacity: 1, scale: 1, y: 0, transition: SPRING.snappy },
  exit: { opacity: 0, scale: 0.97, y: -DISTANCE.xs, transition: leave(DURATION.instant) },
}

export const toast: Variants = {
  initial: { opacity: 0, y: DISTANCE.md, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1, transition: SPRING.gentle },
  exit: { opacity: 0, y: DISTANCE.sm, transition: leave() },
}

/** Thanh bên đẩy nội dung: đây là chỗ duy nhất animate kích thước (độ rộng), vì bố cục phải nhường chỗ thật. */
export const collapseWidth = (width: number): Variants => ({
  initial: { width: 0, opacity: 0 },
  animate: { width, opacity: 1, transition: out(DURATION.slow) },
  exit: { width: 0, opacity: 0, transition: { duration: DURATION.base, ease: EASE.inOut } },
})

/** Tương tác con trỏ cho phần tử motion: nổi nhẹ khi hover, ấn xuống khi chạm. */
export const hoverInteraction = { y: -2, transition: { duration: DURATION.fast, ease: EASE.out } }
export const tapInteraction = { scale: 0.97, transition: { duration: DURATION.instant } }

/** Chỉ báo tab dùng layoutId: trượt theo lò xo nhanh. */
export const indicatorTransition: Transition = SPRING.snappy

/** Trải một variant ra props của <motion.*>: v-bind="presence(slideUp)". */
export function presence(variants: Variants) {
  return { variants, initial: 'initial', animate: 'animate', exit: 'exit' } as const
}
