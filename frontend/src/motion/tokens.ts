/**
 * Token chuyển động dùng chung: một nguồn cho cả variants của motion-v (JS) và biến CSS (--hf-dur-*, --hf-ease-*)
 * mà Tailwind và CSS của component đọc. Chuyển động ngắn, mượt, không nảy quá đà; chỉ transform và opacity.
 */
export const DURATION = { instant: 0.1, fast: 0.15, base: 0.22, slow: 0.32, page: 0.28 } as const
export const EASE = {
  out: [0.2, 0.8, 0.2, 1],
  inOut: [0.4, 0, 0.2, 1],
  in: [0.4, 0, 1, 1],
  emphasized: [0.16, 1, 0.3, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>
export const SPRING = {
  /** Chỉ báo tab, nút bấm: bám nhanh, gần như không nảy. */
  snappy: { type: 'spring', stiffness: 520, damping: 38, mass: 0.9 },
  /** Modal, popover, toast: mềm hơn một chút. */
  gentle: { type: 'spring', stiffness: 320, damping: 32, mass: 1 },
} as const
export const STAGGER = { fast: 0.03, base: 0.05 } as const
export const DISTANCE = { xs: 4, sm: 8, md: 16, lg: 24 } as const

const bezier = (curve: readonly number[]) => `cubic-bezier(${curve.join(', ')})`

/** Các biến CSS sinh từ token (đặt lên :root một lần khi khởi động). */
export function motionVariables(): Record<string, string> {
  const variables: Record<string, string> = {}
  for (const [name, seconds] of Object.entries(DURATION)) variables[`--hf-dur-${name}`] = `${Math.round(seconds * 1000)}ms`
  for (const [name, curve] of Object.entries(EASE)) variables[`--hf-ease-${name.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}`] = bezier(curve)
  variables['--hf-stagger'] = `${Math.round(STAGGER.base * 1000)}ms`
  return variables
}

export function installMotionTokens(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(motionVariables())) root.style.setProperty(name, value)
}
